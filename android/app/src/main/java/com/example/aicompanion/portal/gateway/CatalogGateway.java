package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.WindowLocation;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

public interface CatalogGateway {
    void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback);
    void resolveWindow(String windowId, GatewayCallback<WindowLocation> callback);
}
