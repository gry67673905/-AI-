package com.example.aicompanion.portal.gateway;

import android.content.ContentResolver;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.SelectedDocument;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.Collections;

public final class OkHttpAdminGateway implements AdminGateway {
    private final NativeApiClient api;
    private final ContentResolver resolver;

    public OkHttpAdminGateway(NativeApiClient api, ContentResolver resolver) {
        this.api = api;
        this.resolver = resolver;
    }

    @Override
    public void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        switch (command) {
            case ADMIN_METRICS: read(new String[]{"admin", "metrics"}, payload, callback); return;
            case ADMIN_DEPARTMENTS: read(new String[]{"admin", "departments"}, payload, callback); return;
            case ADMIN_DEPARTMENT_CREATE: write(NativeApiClient.Action.POST, new String[]{"admin", "departments"}, payload, callback); return;
            case ADMIN_WINDOWS: read(new String[]{"admin", "windows"}, payload, callback); return;
            case ADMIN_WINDOW_CREATE: write(NativeApiClient.Action.POST, new String[]{"admin", "windows"}, payload, callback); return;
            case ADMIN_ACCOUNTS: read(new String[]{"admin", "accounts"}, payload, callback); return;
            case ADMIN_SERVICES: read(new String[]{"admin", "services"}, payload, callback); return;
            case ADMIN_AUDIT: read(new String[]{"admin", "audit"}, payload, callback); return;
            case ADMIN_STAFF_CREATE: write(NativeApiClient.Action.POST, new String[]{"admin", "staff"}, payload, callback); return;
            case ADMIN_USER_FREEZE:
                write(NativeApiClient.Action.POST,
                    new String[]{"admin", "accounts", GatewayPayload.string(payload, "account_id"), "status"}, payload, callback); return;
            case ADMIN_SERVICE_CREATE:
                write(NativeApiClient.Action.POST, new String[]{"admin", "services"}, payload, callback); return;
            case ADMIN_SERVICE_VERSION:
                write(NativeApiClient.Action.POST,
                    new String[]{"admin", "services", GatewayPayload.string(payload, "service_id"), "versions"}, payload, callback); return;
            case ADMIN_SERVICE_LIFECYCLE:
                write(NativeApiClient.Action.POST,
                    new String[]{"admin", "services", GatewayPayload.string(payload, "service_id"), "lifecycle"}, payload, callback); return;
            case ADMIN_KNOWLEDGE_RETRY:
                postWithoutBody(
                    new String[]{"admin", "knowledge", GatewayPayload.string(payload, "job_id"), "retry"}, callback); return;
            case ADMIN_KNOWLEDGE_ARCHIVE:
                postWithoutBody(
                    new String[]{"admin", "knowledge", GatewayPayload.string(payload, "job_id"), "archive"}, callback); return;
            default:
                callback.onError(new ApiFailure(400, "unsupported_command", "不支持的管理员命令"));
        }
    }

    @Override
    public void uploadKnowledge(SelectedDocument document, GatewayCallback<JsonElement> callback) {
        java.util.Map<String, String> fields = new java.util.LinkedHashMap<>();
        fields.put("title", document.getDisplayName());
        fields.put("source", "demo://android-upload");
        api.upload(new String[]{"admin", "knowledge"}, document, resolver, fields, callback);
    }

    private void read(String[] path, JsonObject payload, GatewayCallback<JsonElement> callback) {
        api.execute(NativeApiClient.Action.GET, path, GatewayPayload.query(payload, "limit", "q", "department_id"),
            null, true, false, callback);
    }

    private void write(NativeApiClient.Action action, String[] path, JsonObject payload, GatewayCallback<JsonElement> callback) {
        api.execute(action, path, Collections.emptyMap(), payload, true, true, callback);
    }

    private void postWithoutBody(String[] path, GatewayCallback<JsonElement> callback) {
        api.execute(NativeApiClient.Action.POST, path, Collections.emptyMap(), null, true, true, callback);
    }
}
