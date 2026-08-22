package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

public interface StreamingGateway {
    void streamChat(JsonObject payload, StreamCallback callback);
    void executeConsultation(Command command, JsonObject payload, GatewayCallback<JsonElement> callback);

    interface StreamCallback {
        void onEvent(String type, JsonElement data);
        void onError(ApiFailure error);
    }
}
