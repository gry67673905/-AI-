package com.example.aicompanion.portal.gateway;

import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import org.junit.Assume;
import org.junit.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import okhttp3.OkHttpClient;

/** Optional read-only integration against the configured cloud API. */
public class PortalLiveBackendTest {
    @Test
    public void optionalCatalogRoundTripUsesNativeGateway() throws Exception {
        Assume.assumeTrue(Boolean.parseBoolean(System.getProperty("liveBackendTest", "false")));
        String baseUrl = System.getProperty("liveBackendUrl", "https://123.249.68.176");
        NativeApiClient api = new NativeApiClient(new OkHttpClient(), baseUrl, new EmptySessionStore());
        JsonObject payload = new JsonObject();
        payload.addProperty("query", "身份证");
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<JsonElement> result = new AtomicReference<>();
        AtomicReference<ApiFailure> error = new AtomicReference<>();

        new OkHttpCatalogGateway(api).execute(Command.CATALOG_SEARCH, payload, new GatewayCallback<JsonElement>() {
            @Override public void onSuccess(JsonElement value) { result.set(value); latch.countDown(); }
            @Override public void onError(ApiFailure value) { error.set(value); latch.countDown(); }
        });

        assertTrue("configured backend timed out", latch.await(10, TimeUnit.SECONDS));
        assertNull(error.get() == null ? null : error.get().getMessage(), error.get());
        assertNotNull(result.get());
        assertTrue(result.get().isJsonObject());
        assertTrue(result.get().getAsJsonObject().has("items"));
    }

    private static final class EmptySessionStore implements SecureSessionStore {
        @Override public Snapshot load() { return Snapshot.empty(); }
        @Override public void save(SessionSecrets secrets, UserProfile profile) {}
        @Override public void clear() {}
    }
}
