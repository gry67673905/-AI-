package com.example.aicompanion.metastudio.gateway;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.VisionSession;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.gateway.SecureSessionStore;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.ApplicantType;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import okhttp3.OkHttpClient;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;

public final class OkHttpVisionSessionGatewayTest {
    private MockWebServer server;
    private OkHttpVisionSessionGateway gateway;

    @Before
    public void setUp() {
        server = new MockWebServer();
        MemorySessionStore store = new MemorySessionStore();
        store.save(
            new SessionSecrets("native-access", "native-refresh", "Bearer"),
            new UserProfile("u1", "群众", Role.CITIZEN, ApplicantType.INDIVIDUAL)
        );
        gateway = new OkHttpVisionSessionGateway(
            new NativeApiClient(new OkHttpClient(), server.url("/").toString(), store)
        );
    }

    @After
    public void tearDown() throws Exception { server.shutdown(); }

    @Test
    public void postsAuthenticatedMinimalRequestAndParsesNativeOnlyCredential() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200).setBody(
            "{\"data\":{\"vision_session_id\":\"vision-1\","
                + "\"vision_websocket_url\":\"wss://api.example.test/api/v1/integrations/metastudio/vision/ws\","
                + "\"vision_token\":\"vision-secret-token\","
                + "\"vision_expires_at\":\"2099-01-01T00:00:00Z\"}}"
        ));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<VisionSession> result = new AtomicReference<>();
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        gateway.create("client-1", new GatewayCallback<VisionSession>() {
            @Override public void onSuccess(VisionSession value) { result.set(value); latch.countDown(); }
            @Override public void onError(ApiFailure error) { failure.set(error); latch.countDown(); }
        });

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNull(failure.get());
        assertEquals("vision-1", result.get().getVisionSessionId());
        assertEquals(
            "wss://api.example.test/api/v1/integrations/metastudio/vision/ws",
            result.get().getWebsocketUrl()
        );
        assertEquals("vision-secret-token", result.get().getVisionToken());
        RecordedRequest request = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(request);
        assertEquals("/api/v1/integrations/metastudio/vision-sessions", request.getPath());
        assertEquals("Bearer native-access", request.getHeader("Authorization"));
        assertNotNull(request.getHeader("Idempotency-Key"));
        JsonObject body = JsonParser.parseString(request.getBody().readUtf8()).getAsJsonObject();
        assertEquals(1, body.size());
        assertEquals("client-1", body.get("client_session_id").getAsString());
    }

    private static final class MemorySessionStore implements SecureSessionStore {
        private Snapshot snapshot = Snapshot.empty();
        @Override public Snapshot load() { return snapshot; }
        @Override public void save(SessionSecrets secrets, UserProfile profile) {
            snapshot = new Snapshot(secrets, profile);
        }
        @Override public void clear() { snapshot = Snapshot.empty(); }
    }
}
