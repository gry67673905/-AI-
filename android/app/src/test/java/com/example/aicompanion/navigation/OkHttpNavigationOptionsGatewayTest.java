package com.example.aicompanion.navigation;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.navigation.gateway.OkHttpNavigationOptionsGateway;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.NavigationOptions;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.gateway.SecureSessionStore;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;

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

public class OkHttpNavigationOptionsGatewayTest {
    private static final String SERVICE_ID = "11111111-1111-4111-8111-111111111111";
    private MockWebServer server;
    private OkHttpNavigationOptionsGateway gateway;

    @Before public void setUp() {
        server = new MockWebServer();
        NativeApiClient api = new NativeApiClient(new OkHttpClient(), server.url("/").toString(), new EmptyStore());
        gateway = new OkHttpNavigationOptionsGateway(api);
    }

    @After public void tearDown() throws Exception { server.shutdown(); }

    @Test public void publicGetUsesFixedPathNoLocationOrAuthorizationAndParsesTopLevelContract() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200).setBody(validBody()));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<NavigationOptions> value = new AtomicReference<>();
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        gateway.load(SERVICE_ID, callback(latch, value, failure));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNull(failure.get());
        assertEquals("智慧政务事项", value.get().getService().getName());
        assertEquals(1, value.get().getWindows().size());
        assertTrue(value.get().isDemoOnly());
        RecordedRequest request = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(request);
        assertEquals("/api/v1/services/" + SERVICE_ID + "/navigation-options", request.getPath());
        assertEquals("GET", request.getMethod());
        assertNull(request.getHeader("Authorization"));
        assertEquals(0L, request.getBodySize());
    }

    @Test public void rejectsUnsupportedCoordinatesWithoutProducingOptions() throws Exception {
        server.enqueue(new MockResponse().setResponseCode(200)
            .setBody(validBody().replace("GCJ02", "WGS84")));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<NavigationOptions> value = new AtomicReference<>();
        AtomicReference<ApiFailure> failure = new AtomicReference<>();

        gateway.load(SERVICE_ID, callback(latch, value, failure));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNull(value.get());
        assertEquals("invalid_navigation_options", failure.get().getCode());
    }

    private static String validBody() {
        return "{\"service\":{\"id\":\"" + SERVICE_ID + "\",\"code\":\"DEMO-SVC\","
            + "\"name\":\"智慧政务事项\",\"handling_mode\":\"BOTH\",\"online_status\":\"AVAILABLE\","
            + "\"status_reason\":\"\",\"status_updated_at\":\"2026-08-25T00:00:00Z\"},"
            + "\"windows\":[{\"id\":\"11111111-1111-4111-8111-111111111112\",\"code\":\"W-1\","
            + "\"name\":\"服务中心\",\"address\":\"演示路1号\",\"opening_hours\":\"09:00-17:00\","
            + "\"latitude\":39.9,\"longitude\":116.4,\"coordinate_type\":\"GCJ02\",\"priority\":1,"
            + "\"data_mode\":\"DEMO\",\"city_code\":\"110000\",\"source_reference\":\"seed\","
            + "\"verified_at\":\"2026-08-25T00:00:00Z\"}],\"demo_only\":true,\"notice\":\"演示路线\"}";
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

    private static final class EmptyStore implements SecureSessionStore {
        @Override public Snapshot load() { return Snapshot.empty(); }
        @Override public void save(
            com.example.aicompanion.portal.model.PortalContract.SessionSecrets secrets,
            com.example.aicompanion.portal.model.PortalContract.UserProfile profile
        ) {}
        @Override public void clear() {}
    }
}
