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
    public void clearLocalSession() {
        store.clear();
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
                        SecureSessionStore.Snapshot current = store.load();
                        if (current.isAuthenticated() && !sameRefreshToken(snapshot, current)) {
                            // Another native process completed refresh first. Its newer session
                            // wins; never erase it because this process used the superseded token.
                            requestMe(current.getProfile(), callback);
                            return;
                        }
                        if (!isDefinitiveRefreshFailure(refreshError)) {
                            // A temporary provider/network failure must not destroy a valid
                            // encrypted login. Keep the last known native profile offline.
                            callback.onSuccess(snapshot.getProfile());
                            return;
                        }
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
        CoordinatedSecureSessionStore coordinated = store instanceof CoordinatedSecureSessionStore
            ? (CoordinatedSecureSessionStore) store : null;
        CoordinatedSecureSessionStore.RefreshLease lease = null;
        if (coordinated != null) {
            try {
                lease = coordinated.acquireRefresh(snapshot);
                if (!lease.isOwner()) {
                    SecureSessionStore.Snapshot current = lease.getSnapshot();
                    if (current.isAuthenticated()) {
                        callback.onSuccess(current);
                    } else {
                        callback.onError(new ApiFailure(401, "authentication_required", "请重新登录"));
                    }
                    return;
                }
            } catch (RuntimeException unavailable) {
                callback.onError(new ApiFailure(503, "session_unavailable", "安全登录状态暂时不可用"));
                return;
            }
        }
        final CoordinatedSecureSessionStore.RefreshLease ownedLease = lease;
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
                        ApiFailure invalid = new ApiFailure(
                            502, "invalid_auth_response", "刷新响应缺少访问令牌"
                        );
                        releaseFailedRefresh(coordinated, ownedLease, invalid);
                        callback.onError(invalid);
                        return;
                    }
                    SessionSecrets secrets = new SessionSecrets(access, refreshToken, GatewayPayload.string(root, "token_type"));
                    try {
                        SecureSessionStore.Snapshot saved;
                        if (coordinated != null) {
                            saved = coordinated.completeRefresh(
                                ownedLease, secrets, snapshot.getProfile()
                            );
                        } else {
                            store.save(secrets, snapshot.getProfile());
                            saved = new SecureSessionStore.Snapshot(secrets, snapshot.getProfile());
                        }
                        callback.onSuccess(saved);
                    } catch (RuntimeException unavailable) {
                        callback.onError(new ApiFailure(
                            503, "session_unavailable", "无法安全保存刷新后的登录状态"
                        ));
                    }
                }
                @Override public void onError(ApiFailure error) {
                    releaseFailedRefresh(coordinated, ownedLease, error);
                    callback.onError(error);
                }
            });
    }

    private void releaseFailedRefresh(
        CoordinatedSecureSessionStore coordinated,
        CoordinatedSecureSessionStore.RefreshLease lease,
        ApiFailure error
    ) {
        boolean invalidate = isDefinitiveRefreshFailure(error);
        if (coordinated != null && lease != null && lease.isOwner()) {
            coordinated.failRefresh(lease, invalidate);
        } else if (invalidate) {
            store.clear();
        }
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

    private static boolean sameRefreshToken(
        SecureSessionStore.Snapshot first,
        SecureSessionStore.Snapshot second
    ) {
        if (!first.isAuthenticated() || !second.isAuthenticated()) return false;
        byte[] left = first.getSecrets().getRefreshToken()
            .getBytes(java.nio.charset.StandardCharsets.UTF_8);
        byte[] right = second.getSecrets().getRefreshToken()
            .getBytes(java.nio.charset.StandardCharsets.UTF_8);
        return java.security.MessageDigest.isEqual(left, right);
    }

    private static boolean isDefinitiveRefreshFailure(ApiFailure error) {
        if (error == null) return false;
        return error.getStatusCode() == 400 || error.getStatusCode() == 401;
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
