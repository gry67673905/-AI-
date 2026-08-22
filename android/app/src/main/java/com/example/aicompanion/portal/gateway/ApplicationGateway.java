package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.SelectedDocument;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

public interface ApplicationGateway {
    void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback);
    void uploadMaterial(SelectedDocument document, GatewayCallback<JsonElement> callback);
}
