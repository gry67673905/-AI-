package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.ApplicantType;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.Collections;

public final class OkHttpAuthGateway implements AuthGateway {
    private final NativeApiClient api;
    private final SecureSessionStore store;

    public OkHttpAuthGateway(NativeApiClient api) {
        this.api = api;
        this.store = api.getSessionStore();
    }

    @Override
    public UserProfile restoredProfile() {
        return store.load().getProfile();
    }

    @Override
    public void restore(GatewayCallback<UserProfile> callback) {
        SecureSessionStore.Snapshot snapshot = store.load();
        if (!snapshot.isAuthenticated()) {
            callback.onSuccess(UserProfile.anonymous());
            return;
        }
        requestMe(snapshot.getProfile(), new GatewayCallback<UserProfile>() {
            @Override public void onSuccess(UserProfile value) { callback.onSuccess(value); }
            @Override public void onError(ApiFailure error) {
                if (error.getStatusCode() != 401) {
                    callback.onSuccess(snapshot.getProfile());
                    return;
                }
                refresh(snapshot, new GatewayCallback<SecureSessionStore.Snapshot>() {
                    @Override public void onSuccess(SecureSessionStore.Snapshot refreshed) {
                        requestMe(refreshed.getProfile(), callback);
                    }
                    @Override public void onError(ApiFailure refreshError) {
                        store.clear();
                        callback.onSuccess(UserProfile.anonymous());
                    }
                });
            }
        });
    }

    @Override
    public void execute(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        switch (command) {
            case AUTH_SEND_CODE:
                api.execute(NativeApiClient.Action.POST, new String[]{"auth", "request-code"},
                    Collections.emptyMap(), payload, false, true, callback);
                return;
            case AUTH_REGISTER:
                api.execute(NativeApiClient.Action.POST, new String[]{"auth", "register"},
                    Collections.emptyMap(), payload, false, true, authResponse(callback, false));
                return;
            case AUTH_LOGIN:
                api.execute(NativeApiClient.Action.POST, new String[]{"auth", "login"},
                    Collections.emptyMap(), payload, false, false, authResponse(callback, true));
                return;
            case AUTH_ME:
                requestMe(store.load().getProfile(), new GatewayCallback<UserProfile>() {
                    @Override public void onSuccess(UserProfile profile) {
                        JsonObject result = new JsonObject();
                        result.add("user", profileJson(profile));
                        callback.onSuccess(result);
                    }
                    @Override public void onError(ApiFailure error) { callback.onError(error); }
                });
                return;
            case AUTH_LOGOUT:
                logout(callback);
                return;
            default:
                callback.onError(new ApiFailure(400, "unsupported_command", "不支持的认证命令"));
        }
    }

    private GatewayCallback<JsonElement> authResponse(GatewayCallback<JsonElement> callback, boolean requireToken) {
        return new GatewayCallback<JsonElement>() {
            @Override
            public void onSuccess(JsonElement value) {
                JsonObject root = GatewayPayload.unwrapObject(value);
                String access = GatewayPayload.string(root, "access_token");
                String refresh = GatewayPayload.string(root, "refresh_token");
                if (access.isEmpty() || refresh.isEmpty()) {
                    if (requireToken) {
                        callback.onError(new ApiFailure(502, "invalid_auth_response", "登录响应缺少安全令牌"));
                    } else {
                        callback.onSuccess(value);
                    }
                    return;
                }
                String type = GatewayPayload.string(root, "token_type");
                JsonObject userJson = root.has("user") && root.get("user").isJsonObject()
                    ? root.getAsJsonObject("user") : root;
                UserProfile profile = parseProfile(userJson, UserProfile.anonymous());
                store.save(new SessionSecrets(access, refresh, type), profile);
                JsonObject safe = new JsonObject();
                safe.addProperty("authenticated", true);
                safe.add("user", profileJson(profile));
                callback.onSuccess(safe);
            }

            @Override public void onError(ApiFailure error) { callback.onError(error); }
        };
    }

    private void requestMe(UserProfile fallback, GatewayCallback<UserProfile> callback) {
        api.execute(NativeApiClient.Action.GET, new String[]{"auth", "me"}, Collections.emptyMap(),
            null, true, false, new GatewayCallback<JsonElement>() {
                @Override public void onSuccess(JsonElement value) {
                    UserProfile profile = parseProfile(GatewayPayload.unwrapObject(value), fallback);
                    SecureSessionStore.Snapshot snapshot = store.load();
                    if (snapshot.isAuthenticated()) store.save(snapshot.getSecrets(), profile);
                    callback.onSuccess(profile);
                }
                @Override public void onError(ApiFailure error) { callback.onError(error); }
            });
    }

    private void refresh(SecureSessionStore.Snapshot snapshot, GatewayCallback<SecureSessionStore.Snapshot> callback) {
        JsonObject body = new JsonObject();
        body.addProperty("refresh_token", snapshot.getSecrets().getRefreshToken());
        api.execute(NativeApiClient.Action.POST, new String[]{"auth", "refresh"}, Collections.emptyMap(),
            body, false, false, new GatewayCallback<JsonElement>() {
                @Override public void onSuccess(JsonElement value) {
                    JsonObject root = GatewayPayload.unwrapObject(value);
                    String access = GatewayPayload.string(root, "access_token");
                    String refreshToken = GatewayPayload.string(root, "refresh_token");
                    if (refreshToken.isEmpty()) refreshToken = snapshot.getSecrets().getRefreshToken();
                    if (access.isEmpty()) {
                        callback.onError(new ApiFailure(502, "invalid_auth_response", "刷新响应缺少访问令牌"));
                        return;
                    }
                    SessionSecrets secrets = new SessionSecrets(access, refreshToken, GatewayPayload.string(root, "token_type"));
                    store.save(secrets, snapshot.getProfile());
                    callback.onSuccess(new SecureSessionStore.Snapshot(secrets, snapshot.getProfile()));
                }
                @Override public void onError(ApiFailure error) { callback.onError(error); }
            });
    }

    private void logout(GatewayCallback<JsonElement> callback) {
        SecureSessionStore.Snapshot snapshot = store.load();
        if (!snapshot.isAuthenticated()) {
            store.clear();
            callback.onSuccess(loggedOut());
            return;
        }
        JsonObject body = new JsonObject();
        body.addProperty("refresh_token", snapshot.getSecrets().getRefreshToken());
        api.execute(NativeApiClient.Action.POST, new String[]{"auth", "logout"}, Collections.emptyMap(),
            body, true, true, new GatewayCallback<JsonElement>() {
                @Override public void onSuccess(JsonElement value) { store.clear(); callback.onSuccess(loggedOut()); }
                @Override public void onError(ApiFailure error) { store.clear(); callback.onSuccess(loggedOut()); }
            });
    }

    private static JsonObject loggedOut() {
        JsonObject result = new JsonObject();
        result.addProperty("authenticated", false);
        result.add("user", profileJson(UserProfile.anonymous()));
        return result;
    }

    private static UserProfile parseProfile(JsonObject object, UserProfile fallback) {
        JsonObject source = object.has("user") && object.get("user").isJsonObject()
            ? object.getAsJsonObject("user") : object;
        String id = first(source, "id", "user_id");
        String name = first(source, "display_name", "name", "username", "account");
        String role = first(source, "role");
        String applicant = first(source, "applicant_type");
        return new UserProfile(
            id.isEmpty() ? fallback.getId() : id,
            name.isEmpty() ? fallback.getDisplayName() : name,
            role.isEmpty() ? fallback.getRole() : Role.fromWire(role),
            applicant.isEmpty() ? fallback.getApplicantType() : ApplicantType.fromWire(applicant)
        );
    }

    private static String first(JsonObject object, String... keys) {
        for (String key : keys) {
            String value = GatewayPayload.string(object, key);
            if (!value.isEmpty()) return value;
        }
        return "";
    }

    private static JsonObject profileJson(UserProfile profile) {
        JsonObject user = new JsonObject();
        user.addProperty("id", profile.getId());
        user.addProperty("display_name", profile.getDisplayName());
        user.addProperty("role", profile.getRole().name());
        user.addProperty("applicant_type", profile.getApplicantType().name());
        return user;
    }
}
