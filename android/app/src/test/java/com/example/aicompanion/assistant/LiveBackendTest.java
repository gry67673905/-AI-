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
    public void optionalLocalBackendRoundTrip() throws Exception {
        Assume.assumeTrue(Boolean.parseBoolean(System.getProperty("liveBackendTest", "false")));
        String baseUrl = System.getProperty("liveBackendUrl", "http://127.0.0.1:8000");
        GovAssistantRepository repository = new GovAssistantRepository(new OkHttpClient(), baseUrl);
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<ChatResponse> result = new AtomicReference<>();
        AtomicReference<ChatError> error = new AtomicReference<>();

        repository.sendChat(null, "补办身份证需要哪些材料？", new ChatDataSource.Callback() {
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

        assertTrue("local backend timed out", latch.await(60, TimeUnit.SECONDS));
        assertNull(error.get() == null ? null : error.get().getMessage(), error.get());
        assertFalse(result.get().getAnswer().trim().isEmpty());
    }
}
