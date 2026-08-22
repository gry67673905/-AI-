package com.example.aicompanion.portal.gateway;

import android.content.ContentResolver;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.SelectedDocument;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.Collections;

public final class OkHttpApplicationGateway implements ApplicationGateway {
    private final NativeApiClient api;
    private final ContentResolver resolver;

    public OkHttpApplicationGateway(NativeApiClient api, ContentResolver resolver) {
        this.api = api;
        this.resolver = resolver;
    }

    @Override
    public void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        String applicationId = GatewayPayload.string(payload, "application_id");
        switch (command) {
            case APPLICATION_CREATE:
                write(NativeApiClient.Action.POST, new String[]{"applications"}, payload, true, callback); return;
            case APPLICATION_LIST:
                api.execute(NativeApiClient.Action.GET, new String[]{"applications"},
                    GatewayPayload.query(payload, "status", "page"), null, true, false, callback); return;
            case APPLICATION_DETAILS:
                read(new String[]{"applications", applicationId}, callback); return;
            case APPLICATION_UPDATE_FORM:
                write(NativeApiClient.Action.PATCH, new String[]{"applications", applicationId, "form"}, payload, false, callback); return;
            case APPLICATION_SUBMIT:
                write(NativeApiClient.Action.POST, new String[]{"applications", applicationId, "submit"}, payload, true, callback); return;
            case APPLICATION_SUPPLEMENT:
                write(NativeApiClient.Action.POST, new String[]{"applications", applicationId, "supplement"}, payload, true, callback); return;
            case APPLICATION_WITHDRAW:
                write(NativeApiClient.Action.POST, new String[]{"applications", applicationId, "withdraw"}, payload, true, callback); return;
            case APPLICATION_DISCARD:
                write(NativeApiClient.Action.POST, new String[]{"applications", applicationId, "discard"}, payload, true, callback); return;
            case APPLICATION_TIMELINE:
                read(new String[]{"applications", applicationId, "timeline"}, callback); return;
            case DELIVERY_SET:
                write(NativeApiClient.Action.POST, new String[]{"applications", applicationId, "delivery"}, payload, true, callback); return;
            case APPOINTMENT_LIST:
                read(new String[]{"appointments"}, callback); return;
            case APPOINTMENT_BOOK:
                write(NativeApiClient.Action.POST, new String[]{"appointments"}, payload, true, callback); return;
            case APPOINTMENT_CANCEL:
                write(NativeApiClient.Action.POST,
                    new String[]{"appointments", GatewayPayload.string(payload, "appointment_id"), "cancel"}, payload, true, callback); return;
            case PAYMENT_CREATE:
                write(NativeApiClient.Action.POST, new String[]{"payments"}, payload, true, callback); return;
            case PAYMENT_CONFIRM:
                write(NativeApiClient.Action.POST,
                    new String[]{"payments", GatewayPayload.string(payload, "payment_id"), "pay"}, payload, true, callback); return;
            case PAYMENT_CANCEL:
                postWithoutBody(
                    new String[]{"payments", GatewayPayload.string(payload, "payment_id"), "cancel"}, callback); return;
            case VERIFICATION_CREATE:
                write(NativeApiClient.Action.POST, new String[]{"verifications"}, payload, true, callback); return;
            case VERIFICATION_CONFIRM:
                write(NativeApiClient.Action.POST,
                    new String[]{"verifications", GatewayPayload.string(payload, "verification_id"), "complete"}, payload, true, callback); return;
            case DELIVERY_CANCEL:
                postWithoutBody(
                    new String[]{"deliveries", GatewayPayload.string(payload, "delivery_id"), "cancel"}, callback); return;
            default:
                callback.onError(new ApiFailure(400, "unsupported_command", "不支持的办件命令"));
        }
    }

    @Override
    public void uploadMaterial(SelectedDocument document, GatewayCallback<JsonElement> callback) {
        java.util.Map<String, String> fields = new java.util.LinkedHashMap<>();
        fields.put("requirement_code", document.getRequirementId());
        fields.put("synthetic_data_confirmed", "true");
        api.upload(new String[]{"applications", document.getApplicationId(), "materials"},
            document, resolver, fields, callback);
    }

    private void read(String[] path, GatewayCallback<JsonElement> callback) {
        api.execute(NativeApiClient.Action.GET, path, Collections.emptyMap(), null, true, false, callback);
    }

    private void write(
        NativeApiClient.Action action,
        String[] path,
        JsonObject payload,
        boolean idempotent,
        GatewayCallback<JsonElement> callback
    ) {
        api.execute(action, path, Collections.emptyMap(), payload, true, idempotent, callback);
    }

    private void postWithoutBody(String[] path, GatewayCallback<JsonElement> callback) {
        api.execute(NativeApiClient.Action.POST, path, Collections.emptyMap(), null, true, true, callback);
    }
}
