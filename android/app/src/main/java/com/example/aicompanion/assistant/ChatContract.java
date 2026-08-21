package com.example.aicompanion.assistant;

import com.google.gson.JsonElement;
import com.google.gson.annotations.SerializedName;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Wire contract for POST /api/v1/chat. */
public final class ChatContract {
    private ChatContract() {}

    public static final class ChatRequest {
        @SerializedName("session_id")
        private final String sessionId;
        private final String message;

        public ChatRequest(String sessionId, String message) {
            this.sessionId = sessionId;
            this.message = message;
        }

        public String getSessionId() {
            return sessionId;
        }

        public String getMessage() {
            return message;
        }
    }

    public static final class ChatResponse {
        @SerializedName("request_id")
        private String requestId;
        @SerializedName("session_id")
        private String sessionId;
        private String answer;
        private List<JsonElement> sources;
        @SerializedName("tool_calls")
        private List<JsonElement> toolCalls;
        @SerializedName("cache_hit")
        private boolean cacheHit;
        private List<String> warnings;

        public ChatResponse() {}

        void normalizeCollections() {
            if (sources == null) sources = new ArrayList<>();
            if (toolCalls == null) toolCalls = new ArrayList<>();
            if (warnings == null) warnings = new ArrayList<>();
        }

        public String getRequestId() {
            return requestId;
        }

        public String getSessionId() {
            return sessionId;
        }

        public String getAnswer() {
            return answer;
        }

        public List<JsonElement> getSources() {
            return Collections.unmodifiableList(sources);
        }

        public List<JsonElement> getToolCalls() {
            return Collections.unmodifiableList(toolCalls);
        }

        public boolean isCacheHit() {
            return cacheHit;
        }

        public List<String> getWarnings() {
            return Collections.unmodifiableList(warnings);
        }
    }

    public static final class ChatError {
        private final int statusCode;
        private final String code;
        private final String message;

        public ChatError(int statusCode, String code, String message) {
            this.statusCode = statusCode;
            this.code = code;
            this.message = message;
        }

        public int getStatusCode() {
            return statusCode;
        }

        public String getCode() {
            return code;
        }

        public String getMessage() {
            return message;
        }
    }
}
