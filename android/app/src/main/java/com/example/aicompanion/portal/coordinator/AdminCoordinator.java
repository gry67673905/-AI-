package com.example.aicompanion.portal.coordinator;

import com.example.aicompanion.portal.gateway.AdminGateway;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.SelectedDocument;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

public final class AdminCoordinator {
    private final AdminGateway gateway;

    public AdminCoordinator(AdminGateway gateway) { this.gateway = gateway; }
    public void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        gateway.execute(command, payload, callback);
    }
    public void uploadKnowledge(SelectedDocument document, GatewayCallback<JsonElement> callback) {
        gateway.uploadKnowledge(document, callback);
    }
}
