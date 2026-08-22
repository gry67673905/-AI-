package com.example.aicompanion.portal.coordinator;

import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.StaffGateway;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

public final class StaffTaskCoordinator {
    private final StaffGateway gateway;

    public StaffTaskCoordinator(StaffGateway gateway) { this.gateway = gateway; }
    public void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        gateway.execute(command, payload, callback);
    }
}
