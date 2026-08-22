package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.WindowLocation;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

public final class OkHttpCatalogGateway implements CatalogGateway {
    private final NativeApiClient api;

    public OkHttpCatalogGateway(NativeApiClient api) {
        this.api = api;
    }

    @Override
    public void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        String serviceId = GatewayPayload.string(payload, "service_id");
        switch (command) {
            case CATALOG_SEARCH:
                Map<String, String> query = new LinkedHashMap<>();
                String keyword = GatewayPayload.string(payload, "query");
                if (!keyword.isEmpty()) query.put("q", keyword);
                api.execute(NativeApiClient.Action.GET, new String[]{"services"}, query, null, false, false, callback);
                return;
            case CATALOG_DETAILS:
                get(new String[]{"services", serviceId}, callback); return;
            case ELIGIBILITY_CHECK:
                post(new String[]{"services", serviceId, "eligibility"}, payload, callback); return;
            case MATERIALS_GET:
                get(new String[]{"services", serviceId, "materials"}, callback); return;
            case PROCESS_GET:
                get(new String[]{"services", serviceId, "process"}, callback); return;
            case FORM_SCHEMA_GET:
                get(new String[]{"services", serviceId, "form"}, callback); return;
            case WINDOW_LIST:
                getAndCacheWindows(new String[]{"services", serviceId, "windows"}, callback); return;
            default:
                callback.onError(new ApiFailure(400, "unsupported_command", "不支持的事项目录命令"));
        }
    }

    @Override
    public void resolveWindow(String windowId, GatewayCallback<WindowLocation> callback) {
        WindowLocation cached = windowCache.get(windowId);
        if (cached == null) {
            callback.onError(new ApiFailure(404, "window_not_loaded", "请先在事项详情中加载服务窗口"));
            return;
        }
        callback.onSuccess(cached);
    }

    private final java.util.concurrent.ConcurrentMap<String, WindowLocation> windowCache =
        new java.util.concurrent.ConcurrentHashMap<>();

    private void getAndCacheWindows(String[] path, GatewayCallback<JsonElement> callback) {
        api.execute(NativeApiClient.Action.GET, path, Collections.emptyMap(), null, false, false,
            new GatewayCallback<JsonElement>() {
                @Override public void onSuccess(JsonElement value) {
                    JsonObject root = GatewayPayload.unwrapObject(value);
                    JsonElement items = root.get("items");
                    if (items != null && items.isJsonArray()) {
                        for (JsonElement item : items.getAsJsonArray()) {
                            if (!item.isJsonObject()) continue;
                            cacheWindow(item.getAsJsonObject());
                        }
                    }
                    callback.onSuccess(value);
                }
                @Override public void onError(ApiFailure error) { callback.onError(error); }
            });
    }

    private void cacheWindow(JsonObject window) {
        String id = firstOrEmpty(window, "id", "window_id");
        if (id.isEmpty()) return;
        try {
            double latitude = number(window, "latitude", "lat");
            double longitude = number(window, "longitude", "lng");
            if (latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) return;
            windowCache.put(id, new WindowLocation(id, first(window, "name", "window_name"),
                GatewayPayload.string(window, "address"), latitude, longitude));
        } catch (RuntimeException ignored) {}
    }

    private void get(String[] path, GatewayCallback<JsonElement> callback) {
        api.execute(NativeApiClient.Action.GET, path, Collections.emptyMap(), null, false, false, callback);
    }

    private void post(String[] path, JsonObject body, GatewayCallback<JsonElement> callback) {
        api.execute(NativeApiClient.Action.POST, path, Collections.emptyMap(), body, false, false, callback);
    }

    private static String first(JsonObject object, String... keys) {
        String value = firstOrEmpty(object, keys);
        return value.isEmpty() ? "办事窗口" : value;
    }

    private static String firstOrEmpty(JsonObject object, String... keys) {
        for (String key : keys) {
            String value = GatewayPayload.string(object, key);
            if (!value.isEmpty()) return value;
        }
        return "";
    }

    private static double number(JsonObject object, String... keys) {
        for (String key : keys) {
            JsonElement value = object.get(key);
            if (value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber()) return value.getAsDouble();
        }
        throw new IllegalArgumentException("Missing coordinate");
    }
}
