package com.example.aicompanion.metastudio.gateway;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.google.gson.JsonElement;

public interface DigitalHumanGateway {
    void createClientSession(GatewayCallback<ClientSession> callback);
    void exchangeActionIntent(
        String intentId,
        String sessionId,
        String chatId,
        GatewayCallback<JsonElement> callback
    );
}
