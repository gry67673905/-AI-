package com.example.aicompanion.metastudio.gateway;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.gateway.SecureSessionStore;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.ApplicantType;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.JsonElement;
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

public class OkHttpDigitalHumanGatewayTest {
    private MockWebServer server;
    private MemorySessionStore store;
    private OkHttpDigitalHumanGateway gateway;

    @Before
    public void setUp() {
        server = new MockWebServer();
        store = new MemorySessionStore();
        NativeApiClient api = new NativeApiClient(new OkHttpClient(), server.url("/").toString(), store);
        gateway = new OkHttpDigitalHumanGateway(api);
    }

    @After
    public void tearDown() throws Exception {
        server.shutdown();
    }

    @Test
    public void createsSessionOnFixedPathAndKeepsCredentialsNative() throws Exception {
        store.save(
            new SessionSecrets("native-access", "native-refresh", "Bearer"),
            new UserProfile("u1", "群众", Role.CITIZEN, ApplicantType.INDIVIDUAL)
        );
        server.enqueue(new MockResponse().setResponseCode(200).setBody(
            "{\"data\":{\"session_id\":\"session-1\",\"once_code\":\"one-time-secret\","
                + "\"robot_id\":\"robot-1\",\"server_address\":\"metastudio-api.cn-north-4.myhuaweicloud.com\","
                + "\"expires_at\":\"2026-08-23T10:00:00Z\"}}"
        ));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<ClientSession> result = new AtomicReference<>();
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        gateway.createClientSession(callback(latch, result, failure));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNull(failure.get());
        assertEquals("one-time-secret", result.get().getOnceCode());
        RecordedRequest request = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(request);
        assertEquals("/api/v1/integrations/metastudio/client-sessions", request.getPath());
        assertEquals("Bearer native-access", request.getHeader("Authorization"));
        assertNotNull(request.getHeader("Idempotency-Key"));
    }

    @Test
    public void exchangeUsesFixedEncodedPathAndMinimalBody() throws Exception {
        store.save(
            new SessionSecrets("native-access", "native-refresh", "Bearer"),
            new UserProfile("u1", "群众", Role.CITIZEN, ApplicantType.INDIVIDUAL)
        );
        server.enqueue(new MockResponse().setResponseCode(200).setBody(
            "{\"intent_id\":\"intent-1\",\"type\":\"OPEN_LOGIN\",\"label\":\"登录\","
                + "\"section\":\"login\",\"prefill\":{},\"requires_confirmation\":true}"
        ));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<JsonElement> result = new AtomicReference<>();
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        gateway.exchangeActionIntent("intent-1", "session-1", "chat-1", callback(latch, result, failure));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNull(failure.get());
        RecordedRequest request = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(request);
        assertEquals(
            "/api/v1/integrations/metastudio/action-intents/intent-1/exchange",
            request.getPath()
        );
        assertEquals("Bearer native-access", request.getHeader("Authorization"));
        JsonElement body = JsonParser.parseString(request.getBody().readUtf8());
        assertEquals("session-1", body.getAsJsonObject().get("session_id").getAsString());
        assertEquals("chat-1", body.getAsJsonObject().get("chat_id").getAsString());
        assertEquals(2, body.getAsJsonObject().size());
    }

    private static <T> GatewayCallback<T> callback(
        CountDownLatch latch,
        AtomicReference<T> value,
        AtomicReference<ApiFailure> failure
    ) {
        return new GatewayCallback<T>() {
            @Override public void onSuccess(T result) { value.set(result); latch.countDown(); }
            @Override public void onError(ApiFailure error) { failure.set(error); latch.countDown(); }
        };
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
