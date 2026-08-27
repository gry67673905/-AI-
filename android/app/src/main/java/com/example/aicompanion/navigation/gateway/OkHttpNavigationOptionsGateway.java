package com.example.aicompanion.navigation.gateway;

import com.example.aicompanion.navigation.business.ServiceIdPolicy;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.GeoPoint;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.NavigationOptions;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.ServiceSummary;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.WindowOption;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Public, fixed-path adapter. The request contains no user position and no arbitrary URL. */
public final class OkHttpNavigationOptionsGateway implements NavigationOptionsGateway {
    private static final int MAX_WINDOWS = 100;
    private final NativeApiClient api;
    private final ServiceIdPolicy serviceIdPolicy;

    public OkHttpNavigationOptionsGateway(NativeApiClient api) {
        this(api, new ServiceIdPolicy());
    }

    OkHttpNavigationOptionsGateway(NativeApiClient api, ServiceIdPolicy serviceIdPolicy) {
        this.api = api;
        this.serviceIdPolicy = serviceIdPolicy;
    }

    @Override
    public void load(String serviceId, GatewayCallback<NavigationOptions> callback) {
        String normalized = serviceIdPolicy.normalize(serviceId);
        if (normalized == null) {
            callback.onError(new ApiFailure(400, "invalid_service_id", "事项编号格式无效"));
            return;
        }
        api.execute(
            NativeApiClient.Action.GET,
            new String[]{"services", normalized, "navigation-options"},
            Collections.emptyMap(),
            null,
            false,
            false,
            new GatewayCallback<JsonElement>() {
                @Override public void onSuccess(JsonElement value) {
                    try {
                        callback.onSuccess(parse(value, normalized));
                    } catch (IllegalArgumentException invalid) {
                        callback.onError(new ApiFailure(502, "invalid_navigation_options",
                            "服务网点导航数据无效"));
                    }
                }

                @Override public void onError(ApiFailure error) { callback.onError(error); }
            }
        );
    }

    private NavigationOptions parse(JsonElement raw, String expectedServiceId) {
        if (raw == null || !raw.isJsonObject()) throw new IllegalArgumentException("object required");
        JsonObject root = raw.getAsJsonObject();
        JsonObject service = object(root, "service");
        String serviceId = canonicalUuid(text(service, "id"));
        if (!expectedServiceId.equals(serviceId)) throw new IllegalArgumentException("service mismatch");
        ServiceSummary summary = new ServiceSummary(
            serviceId,
            bounded(service, "code", 80, true),
            bounded(service, "name", 160, false),
            bounded(service, "handling_mode", 40, true),
            bounded(service, "online_status", 40, true),
            bounded(service, "status_reason", 500, true),
            bounded(service, "status_updated_at", 64, true)
        );

        JsonElement windowsElement = root.get("windows");
        if (windowsElement == null || !windowsElement.isJsonArray()) {
            throw new IllegalArgumentException("windows required");
        }
        JsonArray windowArray = windowsElement.getAsJsonArray();
        if (windowArray.size() > MAX_WINDOWS) throw new IllegalArgumentException("too many windows");
        List<WindowOption> windows = new ArrayList<>();
        for (JsonElement item : windowArray) {
            if (!item.isJsonObject()) throw new IllegalArgumentException("window object required");
            JsonObject window = item.getAsJsonObject();
            String coordinateType = bounded(window, "coordinate_type", 16, false)
                .toUpperCase(java.util.Locale.ROOT);
            if (!"GCJ02".equals(coordinateType)) {
                throw new IllegalArgumentException("unsupported coordinate system");
            }
            String dataMode = bounded(window, "data_mode", 16, false)
                .toUpperCase(java.util.Locale.ROOT);
            if (!"DEMO".equals(dataMode) && !"VERIFIED".equals(dataMode)) {
                throw new IllegalArgumentException("invalid data mode");
            }
            windows.add(new WindowOption(
                canonicalUuid(text(window, "id")),
                bounded(window, "code", 80, true),
                bounded(window, "name", 160, false),
                bounded(window, "address", 300, false),
                bounded(window, "opening_hours", 300, true),
                new GeoPoint(number(window, "latitude"), number(window, "longitude")),
                coordinateType,
                integer(window, "priority"),
                dataMode,
                bounded(window, "city_code", 32, true),
                bounded(window, "source_reference", 300, true),
                bounded(window, "verified_at", 64, true)
            ));
        }
        boolean demoOnly = bool(root, "demo_only");
        String notice = bounded(root, "notice", 800, true);
        return new NavigationOptions(summary, windows, demoOnly, notice);
    }

    private static JsonObject object(JsonObject source, String key) {
        JsonElement value = source.get(key);
        if (value == null || !value.isJsonObject()) throw new IllegalArgumentException(key);
        return value.getAsJsonObject();
    }

    private static String text(JsonObject source, String key) {
        JsonElement value = source.get(key);
        if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()) {
            throw new IllegalArgumentException(key);
        }
        return value.getAsString().trim();
    }

    private static String bounded(JsonObject source, String key, int max, boolean optional) {
        JsonElement value = source.get(key);
        if ((value == null || value.isJsonNull()) && optional) return "";
        String text = text(source, key);
        if ((!optional && text.isEmpty()) || text.length() > max || containsControl(text)) {
            throw new IllegalArgumentException(key);
        }
        return text;
    }

    private static double number(JsonObject source, String key) {
        JsonElement value = source.get(key);
        if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber()) {
            throw new IllegalArgumentException(key);
        }
        double result = value.getAsDouble();
        if (!Double.isFinite(result)) throw new IllegalArgumentException(key);
        return result;
    }

    private static int integer(JsonObject source, String key) {
        JsonElement value = source.get(key);
        if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber()) {
            throw new IllegalArgumentException(key);
        }
        int result = value.getAsInt();
        if (result < 0 || result > 100_000) throw new IllegalArgumentException(key);
        return result;
    }

    private static boolean bool(JsonObject source, String key) {
        JsonElement value = source.get(key);
        if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isBoolean()) {
            throw new IllegalArgumentException(key);
        }
        return value.getAsBoolean();
    }

    private static String canonicalUuid(String raw) {
        String normalized = new ServiceIdPolicy().normalize(raw);
        if (normalized == null) throw new IllegalArgumentException("invalid uuid");
        return normalized;
    }

    private static boolean containsControl(String value) {
        for (int index = 0; index < value.length(); index++) {
            if (Character.isISOControl(value.charAt(index))) return true;
        }
        return false;
    }
}
