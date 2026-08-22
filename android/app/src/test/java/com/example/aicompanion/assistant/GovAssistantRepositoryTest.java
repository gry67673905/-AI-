package com.example.aicompanion.assistant;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.assistant.ChatContract.ChatError;
import com.example.aicompanion.assistant.ChatContract.ChatResponse;
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

public class GovAssistantRepositoryTest {
    private MockWebServer server;
    private GovAssistantRepository repository;

    @Before
    public void setUp() {
        server = new MockWebServer();
        repository = new GovAssistantRepository(new OkHttpClient(), server.url("/").toString());
    }

    @After
    public void tearDown() throws Exception {
        server.shutdown();
    }

    @Test
    public void requestOmitsAbsentSessionAndUsesExpectedMessageField() {
        JsonObject json = JsonParser.parseString(repository.buildRequestJson(null, "补办身份证")).getAsJsonObject();

        assertFalse(json.has("session_id"));
        assertEquals("补办身份证", json.get("message").getAsString());
    }

    @Test
    public void parserPreservesSingleLayerSourcesAndToolCalls() {
        ChatResponse response = repository.parseResponse(successJson());

        assertEquals("req-1", response.getRequestId());
        assertEquals("session-1", response.getSessionId());
        assertEquals("请携带材料。", response.getAnswer());
        assertEquals("local_catalog", response.getSources().get(0).getKind());
        assertEquals("future_catalog", response.getSources().get(1).getKind());
        assertEquals("search_services", response.getToolCalls().get(0).getName());
        assertTrue(response.getToolCalls().get(0).isSuccess());
        assertEquals(18, response.getToolCalls().get(0).getDurationMs());
        assertEquals("身份证补领", response.getToolCalls().get(0).getArguments().get("query").getAsString());
        assertTrue(response.isCacheHit());
        assertTrue(response.getWarnings().isEmpty());
        assertTrue(response.isClarificationRequired());
        assertEquals("QUEUED", response.getHandoffStatus());
    }

    @Test
    public void sendChatPostsContractAndParsesResponse() throws Exception {
        server.enqueue(new MockResponse()
            .setResponseCode(200)
            .setHeader("Content-Type", "application/json")
            .setBody(successJson()));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<ChatResponse> result = new AtomicReference<>();
        AtomicReference<ChatError> error = new AtomicReference<>();

        repository.sendChat("session-old", "社保卡怎么办", callback(latch, result, error));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNull(error.get());
        assertNotNull(result.get());
        RecordedRequest recorded = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(recorded);
        assertEquals("/api/v1/chat", recorded.getPath());
        assertEquals("POST", recorded.getMethod());
        JsonObject body = JsonParser.parseString(recorded.getBody().readUtf8()).getAsJsonObject();
        assertEquals("session-old", body.get("session_id").getAsString());
        assertEquals("社保卡怎么办", body.get("message").getAsString());
    }

    @Test
    public void httpErrorIsBoundedAndSecretsAreRedacted() throws Exception {
        server.enqueue(new MockResponse()
            .setResponseCode(502)
            .setHeader("Content-Type", "application/json")
            .setBody("{\"error\":{\"code\":\"model_error\",\"message\":\"Authorization: Bearer top-secret api_key=sk-1234567890\","
                + "\"detail\":{\"job_id\":\"job-1\",\"refresh_token\":\"must-not-leak\"}}}"));
        CountDownLatch latch = new CountDownLatch(1);
        AtomicReference<ChatError> error = new AtomicReference<>();

        repository.sendChat(null, "测试", callback(latch, new AtomicReference<>(), error));

        assertTrue(latch.await(3, TimeUnit.SECONDS));
        assertNotNull(error.get());
        assertEquals(502, error.get().getStatusCode());
        assertEquals("model_error", error.get().getCode());
        assertFalse(error.get().getMessage().contains("top-secret"));
        assertFalse(error.get().getMessage().contains("sk-1234567890"));
        assertTrue(error.get().getMessage().contains("[REDACTED]"));
        assertEquals("job-1", error.get().getDetails().getAsJsonObject().get("job_id").getAsString());
        assertFalse(error.get().getDetails().getAsJsonObject().has("refresh_token"));
    }

    private static ChatDataSource.Callback callback(
        CountDownLatch latch,
        AtomicReference<ChatResponse> result,
        AtomicReference<ChatError> error
    ) {
        return new ChatDataSource.Callback() {
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
        };
    }

    static String successJson() {
        return "{"
            + "\"request_id\":\"req-1\","
            + "\"session_id\":\"session-1\","
            + "\"answer\":\"请携带材料。\","
            + "\"sources\":[{\"kind\":\"local_catalog\",\"title\":\"演示政务服务\",\"reference\":\"svc-1\"},{\"kind\":\"future_catalog\",\"title\":\"未来来源\"}],"
            + "\"tool_calls\":[{\"name\":\"search_services\",\"success\":true,\"arguments\":{\"query\":\"身份证补领\"},\"result\":{\"items\":[]},\"duration_ms\":18,\"cached\":false}],"
            + "\"cache_hit\":true,"
            + "\"warnings\":[],"
            + "\"candidate_services\":[{\"id\":\"svc-1\"}],"
            + "\"suggested_actions\":[{\"action\":\"open_service\"}],"
            + "\"clarification_required\":true,"
            + "\"handoff_status\":\"QUEUED\""
            + "}";
    }
}
