package com.example.aicompanion.metastudio.gateway;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.Collections;

/** Fixed-path backend adapter. Huawei credentials and arbitrary URLs are never accepted from the WebView. */
public final class OkHttpDigitalHumanGateway implements DigitalHumanGateway {
    private final NativeApiClient api;

    public OkHttpDigitalHumanGateway(NativeApiClient api) {
        this.api = api;
    }

    @Override
    public void createClientSession(GatewayCallback<ClientSession> callback) {
        api.executeOptionalAuth(
            NativeApiClient.Action.POST,
            new String[]{"integrations", "metastudio", "client-sessions"},
            Collections.emptyMap(),
            new JsonObject(),
            true,
            new GatewayCallback<JsonElement>() {
                @Override public void onSuccess(JsonElement value) {
                    JsonObject object = unwrap(value);
                    ClientSession session = new ClientSession(
                        first(object, "session_id", "client_session_id"),
                        first(object, "once_code", "onceCode"),
                        first(object, "robot_id", "robotId"),
                        first(object, "server_address", "serverAddress"),
                        first(object, "expires_at", "expiresAt")
                    );
                    callback.onSuccess(session);
                }

                @Override public void onError(ApiFailure error) { callback.onError(error); }
            }
        );
    }

    @Override
    public void exchangeActionIntent(
        String intentId,
        String sessionId,
        String chatId,
        GatewayCallback<JsonElement> callback
    ) {
        JsonObject body = new JsonObject();
        body.addProperty("session_id", sessionId);
        body.addProperty("chat_id", chatId);
        // Action-intent exchange is private. Anonymous users are routed to login by the native
        // coordinator without sending an exchange request.
        api.execute(
            NativeApiClient.Action.POST,
            new String[]{"integrations", "metastudio", "action-intents", intentId, "exchange"},
            Collections.emptyMap(),
            body,
            true,
            true,
            callback
        );
    }

    private static JsonObject unwrap(JsonElement value) {
        if (value == null || !value.isJsonObject()) return new JsonObject();
        JsonObject root = value.getAsJsonObject();
        JsonElement data = root.get("data");
        if (data != null && data.isJsonObject()) root = data.getAsJsonObject();
        JsonElement session = root.get("session");
        return session != null && session.isJsonObject() ? session.getAsJsonObject() : root;
    }

    private static String first(JsonObject object, String... keys) {
        for (String key : keys) {
            JsonElement value = object.get(key);
            if (value != null && value.isJsonPrimitive()) {
                String text = value.getAsString().trim();
                if (!text.isEmpty()) return text;
            }
        }
        return "";
    }
}
