package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.Collections;

public final class OkHttpStaffGateway implements StaffGateway {
    private final NativeApiClient api;

    public OkHttpStaffGateway(NativeApiClient api) { this.api = api; }

    @Override
    public void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        switch (command) {
            case STAFF_TASKS:
                api.execute(NativeApiClient.Action.GET, new String[]{"staff", "tasks"},
                    GatewayPayload.query(payload, "status", "page"), null, true, false, callback); return;
            case STAFF_CLAIM:
                write(new String[]{"staff", "tasks", GatewayPayload.string(payload, "task_id"), "claim"}, payload, callback); return;
            case STAFF_SUPPLEMENT:
                decision(payload, "supplement", callback); return;
            case STAFF_APPROVE:
                decision(payload, "approve", callback); return;
            case STAFF_REJECT:
                decision(payload, "reject", callback); return;
            case STAFF_COMPLETE:
                decision(payload, "complete", callback); return;
            case STAFF_HANDOFFS:
                api.execute(NativeApiClient.Action.GET, new String[]{"staff", "handoffs"},
                    GatewayPayload.query(payload, "status", "page"), null, true, false, callback); return;
            case STAFF_HANDOFF_REPLY:
                write(new String[]{"staff", "handoffs", GatewayPayload.string(payload, "ticket_id"), "messages"}, payload, callback); return;
            case STAFF_HANDOFF_RESOLVE:
                write(new String[]{"staff", "handoffs", GatewayPayload.string(payload, "ticket_id"), "resolve"}, payload, callback); return;
            default:
                callback.onError(new ApiFailure(400, "unsupported_command", "不支持的工作人员命令"));
        }
    }

    private void decision(JsonObject payload, String action, GatewayCallback<JsonElement> callback) {
        write(new String[]{"staff", "applications", GatewayPayload.string(payload, "application_id"), action}, payload, callback);
    }

    private void write(String[] path, JsonObject payload, GatewayCallback<JsonElement> callback) {
        api.execute(NativeApiClient.Action.POST, path, Collections.emptyMap(), payload, true, true, callback);
    }
}
