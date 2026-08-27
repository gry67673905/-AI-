package com.example.aicompanion.metastudio.gateway;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.VisionSession;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.Collections;

/** Fixed-path authenticated adapter for a native-only visual channel credential. */
public final class OkHttpVisionSessionGateway {
    private final NativeApiClient api;

    public OkHttpVisionSessionGateway(NativeApiClient api) {
        this.api = api;
    }

    public void create(String clientSessionId, GatewayCallback<VisionSession> callback) {
        JsonObject body = new JsonObject();
        body.addProperty("client_session_id", clientSessionId == null ? "" : clientSessionId.trim());
        api.execute(
            NativeApiClient.Action.POST,
            new String[]{"integrations", "metastudio", "vision-sessions"},
            Collections.emptyMap(),
            body,
            true,
            true,
            new GatewayCallback<JsonElement>() {
                @Override public void onSuccess(JsonElement value) {
                    JsonObject object = unwrap(value);
                    callback.onSuccess(new VisionSession(
                        text(object, "vision_session_id"),
                        text(object, "vision_websocket_url"),
                        text(object, "vision_token"),
                        text(object, "vision_expires_at")
                    ));
                }

                @Override public void onError(ApiFailure error) { callback.onError(error); }
            }
        );
    }

    private static JsonObject unwrap(JsonElement value) {
        if (value == null || !value.isJsonObject()) return new JsonObject();
        JsonObject root = value.getAsJsonObject();
        JsonElement data = root.get("data");
        return data != null && data.isJsonObject() ? data.getAsJsonObject() : root;
    }

    private static String text(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() ? value.getAsString().trim() : "";
    }
}
