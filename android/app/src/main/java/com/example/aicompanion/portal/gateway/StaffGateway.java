package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.Command;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

public interface StaffGateway {
    void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback);
}
