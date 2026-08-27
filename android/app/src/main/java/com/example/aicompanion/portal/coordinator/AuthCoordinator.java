package com.example.aicompanion.portal.coordinator;

import com.example.aicompanion.portal.gateway.AuthGateway;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

public final class AuthCoordinator {
    private final AuthGateway gateway;

    public AuthCoordinator(AuthGateway gateway) { this.gateway = gateway; }
    public UserProfile restoredProfile() { return gateway.restoredProfile(); }
    public void restore(GatewayCallback<UserProfile> callback) { gateway.restore(callback); }
    public void clearLocalSession() { gateway.clearLocalSession(); }
    public void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        gateway.execute(command, payload, callback);
    }
}
