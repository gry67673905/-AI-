package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

public interface AuthGateway {
    UserProfile restoredProfile();
    void restore(GatewayCallback<UserProfile> callback);
    void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback);
}
