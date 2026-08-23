package com.example.aicompanion.assistant;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.assistant.ChatContract.ChatError;
import com.example.aicompanion.assistant.ChatContract.ChatResponse;

import org.junit.Assume;
import org.junit.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import okhttp3.OkHttpClient;

public class LiveBackendTest {
    @Test
    public void optionalConfiguredBackendRoundTrip() throws Exception {
        Assume.assumeTrue(Boolean.parseBoolean(System.getProperty("liveBackendTest", "false")));
        String baseUrl = System.getProperty("liveBackendUrl", "https://123.249.68.176");
        GovAssistantRepository repository = new GovAssistantRepository(new OkHttpClient(), baseUrl);
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<ChatResponse> result = new AtomicReference<>();
        AtomicReference<ChatError> error = new AtomicReference<>();

        // “社保怎么办” deliberately matches more than one demo service. The
        // backend returns its deterministic clarification response before the
        // LLM boundary, so this live transport test never incurs model usage.
        repository.sendChat(null, "社保怎么办", new ChatDataSource.Callback() {
            @Override
            public void onSuccess(ChatResponse response) {
                result.set(response);
                latch.countDown();
            }

            @Override
            public void onError(ChatError value) {
                error.set(value);
                latch.countDown();
            }
        });

        assertTrue("configured backend timed out", latch.await(60, TimeUnit.SECONDS));
        assertNull(error.get() == null ? null : error.get().getMessage(), error.get());
        assertFalse(result.get().getAnswer().trim().isEmpty());
        assertTrue(result.get().isClarificationRequired());
    }
}
