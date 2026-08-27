package com.example.aicompanion.portal.gateway;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.ApplicantType;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import okhttp3.OkHttpClient;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;

public class NativeGatewaysTest {
    private MockWebServer server;
    private MemorySessionStore store;
    private NativeApiClient api;

    @Before
    public void setUp() {
        server = new MockWebServer();
        store = new MemorySessionStore();
        api = new NativeApiClient(new OkHttpClient(), server.url("/").toString(), store);
    }

    @After
    public void tearDown() throws Exception {
        server.shutdown();
    }

    @Test
    public void loginStoresSecretsButReturnsOnlySafeProfile() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json").setBody(
            "{\"access_token\":\"access-secret\",\"refresh_token\":\"refresh-secret\",\"token_type\":\"Bearer\",\"user\":{\"id\":\"u1\",\"display_name\":\"演示群众\",\"role\":\"CITIZEN\",\"applicant_type\":\"INDIVIDUAL\"}}"
        ));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<JsonElement> result = new AtomicReference<>();
        AtomicReference<ApiFailure> failure = new AtomicReference<>();
        JsonObject login = new JsonObject();
        login.addProperty("username", "demo");
        login.addProperty("password", "demo-password");

        new OkHttpAuthGateway(api).execute(Command.AUTH_LOGIN, login, callback(latch, result, failure));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNull(failure.get());
        assertTrue(store.load().isAuthenticated());
        assertEquals(Role.CITIZEN, store.load().getProfile().getRole());
        String visible = result.get().toString();
        assertFalse(visible.contains("access-secret"));
        assertFalse(visible.contains("refresh-secret"));
        RecordedRequest request = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(request);
        assertEquals("/api/v1/auth/login", request.getPath());
        assertNull(request.getHeader("Authorization"));
    }

    @Test
    public void catalogAndAuthenticatedApplicationUseFixedPaths() throws Exception {
        store.save(new SessionSecrets("access", "refresh", "Bearer"),
            new UserProfile("u1", "群众", Role.CITIZEN, ApplicantType.INDIVIDUAL));
        server.enqueue(new MockResponse().setResponseCode(200).setBody("{\"id\":\"svc-1\"}"));
        server.enqueue(new MockResponse().setResponseCode(200).setBody("{\"items\":[]}"));
        CountDownLatch latch = new CountDownLatch(2);
        JsonObject details = new JsonObject();
        details.addProperty("service_id", "svc-1");

        new OkHttpCatalogGateway(api).execute(Command.CATALOG_DETAILS, details, counting(latch));
        new OkHttpApplicationGateway(api, null).execute(Command.APPLICATION_LIST, new JsonObject(), counting(latch));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        RecordedRequest first = server.takeRequest(1, TimeUnit.SECONDS);
        RecordedRequest second = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(first);
        assertNotNull(second);
        List<String> paths = java.util.Arrays.asList(first.getPath(), second.getPath());
        assertTrue(paths.contains("/api/v1/services/svc-1"));
        assertTrue(paths.contains("/api/v1/applications"));
        RecordedRequest authenticated = "/api/v1/applications".equals(first.getPath()) ? first : second;
        assertEquals("Bearer access", authenticated.getHeader("Authorization"));
    }

    @Test
    public void streamingGatewayEmitsOfficialEventNames() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "text/event-stream").setBody(
            "event: meta\ndata: {\"session_id\":\"session-1\"}\n\n"
                + "event: delta\ndata: {\"delta\":\"您好\"}\n\n"
                + "event: done\ndata: {\"answer\":\"您好\"}\n\n"
        ));
        CountDownLatch latch = new CountDownLatch(3);
        List<String> events = java.util.Collections.synchronizedList(new ArrayList<>());
        AtomicReference<ApiFailure> failure = new AtomicReference<>();
        JsonObject body = new JsonObject();
        body.addProperty("message", "您好");

        new OkHttpStreamingGateway(api).streamChat(body, new StreamingGateway.StreamCallback() {
            @Override public void onEvent(String type, JsonElement data) { events.add(type); latch.countDown(); }
            @Override public void onError(ApiFailure error) { failure.set(error); }
        });

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNull(failure.get());
        assertEquals(java.util.Arrays.asList("meta", "delta", "done"), events);
        RecordedRequest request = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(request);
        assertEquals("/api/v1/chat/stream", request.getPath());
        assertEquals("text/event-stream", request.getHeader("Accept"));
    }

    @Test
    public void streamingGatewayRejectsEofWithoutTerminalEvent() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200)
            .setHeader("Content-Type", "text/event-stream")
            .setBody("event: meta\ndata: {\"session_id\":\"session-1\"}\n\n"
                + "event: delta\ndata: {\"text\":\"未完成\"}\n\n"));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<ApiFailure> failure = new AtomicReference<>();
        OkHttpStreamingGateway streaming = new OkHttpStreamingGateway(api);

        streaming.streamChat(new JsonObject(), new StreamingGateway.StreamCallback() {
            @Override public void onEvent(String event, JsonElement data) { }
            @Override public void onError(ApiFailure error) {
                failure.set(error);
                latch.countDown();
            }
        });

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNotNull(failure.get());
        assertEquals("incomplete_stream", failure.get().getCode());
    }

    @Test
    public void fastApiValidationErrorDoesNotEchoSensitiveInput() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(422).setHeader("Content-Type", "application/json").setBody(
            "{\"detail\":[{\"loc\":[\"body\",\"password\"],\"msg\":\"String too short\",\"input\":\"plain-secret-password\"}]}"
        ));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<ApiFailure> failure = new AtomicReference<>();
        JsonObject body = new JsonObject();
        body.addProperty("username", "demo");
        body.addProperty("password", "x");

        new OkHttpAuthGateway(api).execute(Command.AUTH_LOGIN, body,
            callback(latch, new AtomicReference<>(), failure));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNotNull(failure.get());
        assertEquals("validation_error", failure.get().getCode());
        assertFalse(failure.get().getMessage().contains("plain-secret-password"));
        assertTrue(failure.get().getMessage().contains("password"));
        assertTrue(failure.get().getDetails().isJsonNull());
    }

    @Test
    public void cancelRetryAndArchiveUseExactNoBodyIdempotentContracts() throws Exception {
        store.save(new SessionSecrets("access", "refresh", "Bearer"),
            new UserProfile("u1", "用户", Role.CITIZEN, ApplicantType.INDIVIDUAL));
        for (int index = 0; index < 5; index++) {
            server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json")
                .setBody("{\"ok\":true}"));
        }
        CountDownLatch latch = new CountDownLatch(5);
        OkHttpApplicationGateway applications = new OkHttpApplicationGateway(api, null);
        OkHttpStreamingGateway consultations = new OkHttpStreamingGateway(api);
        OkHttpAdminGateway admin = new OkHttpAdminGateway(api, null);

        applications.execute(Command.PAYMENT_CANCEL, payload("payment_id", "pay-1"), counting(latch));
        applications.execute(Command.DELIVERY_CANCEL, payload("delivery_id", "delivery-1"), counting(latch));
        consultations.executeConsultation(Command.HANDOFF_CANCEL, payload("ticket_id", "ticket-1"), counting(latch));
        admin.execute(Command.ADMIN_KNOWLEDGE_RETRY, payload("job_id", "job-1"), counting(latch));
        admin.execute(Command.ADMIN_KNOWLEDGE_ARCHIVE, payload("job_id", "job-2"), counting(latch));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        Map<String, RecordedRequest> requests = new LinkedHashMap<>();
        for (int index = 0; index < 5; index++) {
            RecordedRequest request = server.takeRequest(1, TimeUnit.SECONDS);
            assertNotNull(request);
            requests.put(request.getPath(), request);
        }
        assertTrue(requests.keySet().containsAll(java.util.Arrays.asList(
            "/api/v1/payments/pay-1/cancel",
            "/api/v1/deliveries/delivery-1/cancel",
            "/api/v1/consultations/handoffs/ticket-1/cancel",
            "/api/v1/admin/knowledge/job-1/retry",
            "/api/v1/admin/knowledge/job-2/archive"
        )));
        for (RecordedRequest request : requests.values()) {
            assertEquals("POST", request.getMethod());
            assertEquals(0L, request.getBodySize());
            assertNull(request.getHeader("Content-Type"));
            assertEquals("Bearer access", request.getHeader("Authorization"));
            assertNotNull(request.getHeader("Idempotency-Key"));
            assertFalse(request.getHeader("Idempotency-Key").trim().isEmpty());
        }
    }

    @Test
    public void structuredFailureKeepsJobIdButDropsSecrets() throws Exception {
        store.save(new SessionSecrets("access", "refresh", "Bearer"),
            new UserProfile("admin", "管理员", Role.ADMIN, ApplicantType.NONE));
        server.enqueue(new MockResponse().setResponseCode(409).setHeader("Content-Type", "application/json").setBody(
            "{\"error\":{\"code\":\"knowledge_index_failed\",\"message\":\"索引失败\","
                + "\"detail\":{\"job_id\":\"job-failed\",\"access_token\":\"must-not-leak\","
                + "\"hint\":\"retry Authorization: Bearer hidden\"}}}"
        ));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        new OkHttpAdminGateway(api, null).execute(Command.ADMIN_KNOWLEDGE_RETRY,
            payload("job_id", "job-failed"), callback(latch, new AtomicReference<>(), failure));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNotNull(failure.get());
        assertEquals("knowledge_index_failed", failure.get().getCode());
        JsonObject details = failure.get().getDetails().getAsJsonObject();
        assertEquals("job-failed", details.get("job_id").getAsString());
        assertFalse(details.has("access_token"));
        assertFalse(details.toString().contains("hidden"));
    }

    @Test
    public void ordinaryUnauthorizedResponseDoesNotEraseRefreshableSession() throws Exception {
        store.save(new SessionSecrets("expired-access", "still-valid-refresh", "Bearer"),
            new UserProfile("u1", "群众", Role.CITIZEN, ApplicantType.INDIVIDUAL));
        server.enqueue(new MockResponse().setResponseCode(401).setHeader("Content-Type", "application/json")
            .setBody("{\"error\":{\"code\":\"invalid_access_token\"}}"));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        api.execute(NativeApiClient.Action.GET, new String[]{"applications"},
            java.util.Collections.emptyMap(), null, true, false,
            callback(latch, new AtomicReference<>(), failure));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNotNull(failure.get());
        assertEquals(401, failure.get().getStatusCode());
        assertTrue(store.load().isAuthenticated());
        assertEquals("still-valid-refresh", store.load().getSecrets().getRefreshToken());
    }

    @Test
    public void materialGenerationAndStatusUseFixedTypedPaths() throws Exception {
        store.save(new SessionSecrets("access", "refresh", "Bearer"),
            new UserProfile("u1", "群众", Role.CITIZEN, ApplicantType.INDIVIDUAL));
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json")
            .setBody("{\"items\":[]}"));
        server.enqueue(new MockResponse().setResponseCode(202).setHeader("Content-Type", "application/json")
            .setBody("{\"generation_id\":\"generation-1\",\"status\":\"QUEUED\"}"));
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json")
            .setBody("{\"generation_id\":\"generation-1\",\"status\":\"RUNNING\"}"));
        CountDownLatch latch = new CountDownLatch(3);
        OkHttpApplicationGateway applications = new OkHttpApplicationGateway(api, null);
        applications.execute(Command.MATERIAL_TEMPLATE_OPTIONS_GET,
            payload("application_id", "application-1"), counting(latch));
        JsonObject generate = new JsonObject();
        generate.addProperty("application_id", "application-1");
        generate.addProperty("requirement_code", "id-2");
        generate.addProperty("template_id", "template-1");
        generate.addProperty("request_text", "请预填联系人");
        applications.execute(Command.MATERIAL_TEMPLATE_GENERATE, generate, counting(latch));
        applications.execute(Command.MATERIAL_TEMPLATE_STATUS_GET,
            payload("generation_id", "generation-1"), counting(latch));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        RecordedRequest first = server.takeRequest(1, TimeUnit.SECONDS);
        RecordedRequest second = server.takeRequest(1, TimeUnit.SECONDS);
        RecordedRequest third = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(first);
        assertNotNull(second);
        assertNotNull(third);
        Map<String, RecordedRequest> requests = new LinkedHashMap<>();
        requests.put(first.getPath(), first);
        requests.put(second.getPath(), second);
        requests.put(third.getPath(), third);
        RecordedRequest options = requests.get("/api/v1/applications/application-1/material-template-options");
        RecordedRequest post = requests.get("/api/v1/applications/application-1/material-documents");
        RecordedRequest status = requests.get("/api/v1/material-documents/generation-1");
        assertNotNull(options);
        assertNotNull(post);
        assertNotNull(status);
        assertEquals("GET", options.getMethod());
        assertEquals("Bearer access", options.getHeader("Authorization"));
        assertEquals("POST", post.getMethod());
        assertNotNull(post.getHeader("Idempotency-Key"));
        String body = post.getBody().readUtf8();
        assertFalse(body.contains("application_id"));
        assertTrue(body.contains("\"requirement_code\":\"id-2\""));
        assertTrue(body.contains("\"template_id\":\"template-1\""));
        assertEquals("GET", status.getMethod());
        assertEquals("Bearer access", status.getHeader("Authorization"));
    }

    @Test
    public void consultationMessagesAndMaterialConfirmationUseFixedPaths() throws Exception {
        store.save(new SessionSecrets("access", "refresh", "Bearer"),
            new UserProfile("u1", "群众", Role.CITIZEN, ApplicantType.INDIVIDUAL));
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json")
            .setBody("{\"items\":[]}"));
        server.enqueue(new MockResponse().setResponseCode(202).setHeader("Content-Type", "application/json")
            .setBody("{\"generation_id\":\"generation-1\",\"status\":\"QUEUED\"}"));
        CountDownLatch latch = new CountDownLatch(2);
        OkHttpStreamingGateway consultations = new OkHttpStreamingGateway(api);
        JsonObject messages = new JsonObject();
        messages.addProperty("session_id", "session-1");
        messages.addProperty("limit", "50");
        consultations.executeConsultation(Command.CONSULTATION_MESSAGES, messages, counting(latch));
        JsonObject confirm = new JsonObject();
        confirm.addProperty("session_id", "session-1");
        confirm.addProperty("intent_id", "intent-1");
        consultations.executeConsultation(Command.CONSULTATION_MATERIAL_CONFIRM, confirm, counting(latch));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        RecordedRequest first = server.takeRequest(1, TimeUnit.SECONDS);
        RecordedRequest second = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(first);
        assertNotNull(second);
        Map<String, RecordedRequest> requests = new LinkedHashMap<>();
        requests.put(first.getPath(), first);
        requests.put(second.getPath(), second);
        RecordedRequest history = requests.get("/api/v1/consultations/session-1/messages?limit=50");
        RecordedRequest create = requests.get(
            "/api/v1/consultations/session-1/material-intents/intent-1/confirm"
        );
        assertNotNull(history);
        assertEquals("GET", history.getMethod());
        assertEquals("Bearer access", history.getHeader("Authorization"));
        assertNotNull(create);
        assertEquals("POST", create.getMethod());
        assertEquals(0L, create.getBodySize());
        assertNotNull(create.getHeader("Idempotency-Key"));
        assertEquals("Bearer access", create.getHeader("Authorization"));
    }

    @Test
    public void restoreRefreshesExpiredAccessTokenBeforeReturningProfile() throws Exception {
        store.save(new SessionSecrets("expired-access", "refresh-one", "Bearer"),
            new UserProfile("u1", "群众", Role.CITIZEN, ApplicantType.INDIVIDUAL));
        server.enqueue(new MockResponse().setResponseCode(401).setHeader("Content-Type", "application/json")
            .setBody("{\"error\":{\"code\":\"invalid_access_token\"}}"));
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json")
            .setBody("{\"access_token\":\"fresh-access\",\"refresh_token\":\"refresh-two\",\"token_type\":\"Bearer\"}"));
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json")
            .setBody("{\"id\":\"u1\",\"display_name\":\"群众\",\"role\":\"CITIZEN\",\"applicant_type\":\"INDIVIDUAL\"}"));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<UserProfile> profile = new AtomicReference<>();

        new OkHttpAuthGateway(api).restore(new GatewayCallback<UserProfile>() {
            @Override public void onSuccess(UserProfile value) { profile.set(value); latch.countDown(); }
            @Override public void onError(ApiFailure error) { latch.countDown(); }
        });

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNotNull(profile.get());
        assertEquals(Role.CITIZEN, profile.get().getRole());
        assertEquals("fresh-access", store.load().getSecrets().getAccessToken());
        assertEquals("refresh-two", store.load().getSecrets().getRefreshToken());
    }

    @Test
    public void restoreUsesSessionRotatedByRefreshOwnerWithoutSecondRefreshRequest() throws Exception {
        CoordinatedMemoryStore coordinated = new CoordinatedMemoryStore();
        coordinated.save(new SessionSecrets("expired-access", "refresh-one", "Bearer"),
            new UserProfile("u1", "群众", Role.CITIZEN, ApplicantType.INDIVIDUAL));
        coordinated.rotateWhenRefreshIsAcquired = true;
        NativeApiClient coordinatedApi = new NativeApiClient(
            new OkHttpClient(), server.url("/").toString(), coordinated
        );
        server.enqueue(new MockResponse().setResponseCode(401).setHeader("Content-Type", "application/json")
            .setBody("{\"error\":{\"code\":\"invalid_access_token\"}}"));
        server.enqueue(new MockResponse().setResponseCode(200).setHeader("Content-Type", "application/json")
            .setBody("{\"id\":\"u1\",\"display_name\":\"群众\",\"role\":\"CITIZEN\",\"applicant_type\":\"INDIVIDUAL\"}"));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<UserProfile> profile = new AtomicReference<>();

        new OkHttpAuthGateway(coordinatedApi).restore(new GatewayCallback<UserProfile>() {
            @Override public void onSuccess(UserProfile value) { profile.set(value); latch.countDown(); }
            @Override public void onError(ApiFailure error) { latch.countDown(); }
        });

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNotNull(profile.get());
        assertEquals("fresh-access", coordinated.load().getSecrets().getAccessToken());
        RecordedRequest first = server.takeRequest(1, TimeUnit.SECONDS);
        RecordedRequest second = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(first);
        assertNotNull(second);
        assertEquals("/api/v1/auth/me", first.getPath());
        assertEquals("/api/v1/auth/me", second.getPath());
        assertNull(server.takeRequest(150, TimeUnit.MILLISECONDS));
    }

    private static JsonObject payload(String key, String value) {
        JsonObject payload = new JsonObject();
        payload.addProperty(key, value);
        return payload;
    }

    private static GatewayCallback<JsonElement> callback(
        CountDownLatch latch,
        AtomicReference<JsonElement> result,
        AtomicReference<ApiFailure> error
    ) {
        return new GatewayCallback<JsonElement>() {
            @Override public void onSuccess(JsonElement value) { result.set(value); latch.countDown(); }
            @Override public void onError(ApiFailure value) { error.set(value); latch.countDown(); }
        };
    }

    private static GatewayCallback<JsonElement> counting(CountDownLatch latch) {
        return new GatewayCallback<JsonElement>() {
            @Override public void onSuccess(JsonElement value) { latch.countDown(); }
            @Override public void onError(ApiFailure error) { latch.countDown(); }
        };
    }

    static final class MemorySessionStore implements SecureSessionStore {
        private Snapshot snapshot = Snapshot.empty();
        @Override public synchronized Snapshot load() { return snapshot; }
        @Override public synchronized void save(SessionSecrets secrets, UserProfile profile) { snapshot = new Snapshot(secrets, profile); }
        @Override public synchronized void clear() { snapshot = Snapshot.empty(); }
    }

    static final class CoordinatedMemoryStore implements CoordinatedSecureSessionStore {
        private Snapshot snapshot = Snapshot.empty();
        private boolean rotateWhenRefreshIsAcquired;

        @Override public synchronized Snapshot load() { return snapshot; }
        @Override public synchronized void save(SessionSecrets secrets, UserProfile profile) {
            snapshot = new Snapshot(secrets, profile);
        }
        @Override public synchronized void clear() { snapshot = Snapshot.empty(); }

        @Override
        public synchronized RefreshLease acquireRefresh(Snapshot expected) {
            if (rotateWhenRefreshIsAcquired) {
                rotateWhenRefreshIsAcquired = false;
                snapshot = new Snapshot(
                    new SessionSecrets("fresh-access", "refresh-two", "Bearer"),
                    expected.getProfile()
                );
                return new RefreshLease(false, snapshot, null);
            }
            return new RefreshLease(true, snapshot, new Object());
        }

        @Override
        public synchronized Snapshot completeRefresh(
            RefreshLease lease, SessionSecrets secrets, UserProfile profile
        ) {
            save(secrets, profile);
            return snapshot;
        }

        @Override
        public synchronized Snapshot failRefresh(RefreshLease lease, boolean invalidateCurrent) {
            if (invalidateCurrent) clear();
            return snapshot;
        }
    }
}
