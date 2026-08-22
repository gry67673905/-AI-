package com.example.aicompanion.assistant;

import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
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
        private List<Source> sources;
        @SerializedName("tool_calls")
        private List<ToolCall> toolCalls;
        @SerializedName("cache_hit")
        private boolean cacheHit;
        private List<String> warnings;
        @SerializedName("candidate_services")
        private List<JsonElement> candidateServices;
        @SerializedName("suggested_actions")
        private List<JsonElement> suggestedActions;
        @SerializedName("clarification_required")
        private boolean clarificationRequired;
        @SerializedName("handoff_status")
        private String handoffStatus;

        public ChatResponse() {}

        void normalizeCollections() {
            if (sources == null) sources = new ArrayList<>();
            if (toolCalls == null) toolCalls = new ArrayList<>();
            if (warnings == null) warnings = new ArrayList<>();
            if (candidateServices == null) candidateServices = new ArrayList<>();
            if (suggestedActions == null) suggestedActions = new ArrayList<>();
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

        public List<Source> getSources() {
            return Collections.unmodifiableList(sources);
        }

        public List<ToolCall> getToolCalls() {
            return Collections.unmodifiableList(toolCalls);
        }

        public boolean isCacheHit() {
            return cacheHit;
        }

        public List<String> getWarnings() {
            return Collections.unmodifiableList(warnings);
        }

        public List<JsonElement> getCandidateServices() {
            return Collections.unmodifiableList(candidateServices);
        }

        public List<JsonElement> getSuggestedActions() {
            return Collections.unmodifiableList(suggestedActions);
        }

        public boolean isClarificationRequired() {
            return clarificationRequired;
        }

        public String getHandoffStatus() {
            return handoffStatus == null ? "" : handoffStatus;
        }
    }

    /** Source.kind intentionally remains a string so newly introduced source kinds stay compatible. */
    public static final class Source {
        private String kind;
        private String title;
        private String reference;
        private String excerpt;
        private Double score;

        public String getKind() { return kind == null ? "" : kind; }
        public String getTitle() { return title == null ? "" : title; }
        public String getReference() { return reference == null ? "" : reference; }
        public String getExcerpt() { return excerpt == null ? "" : excerpt; }
        public Double getScore() { return score; }
    }

    public static final class ToolCall {
        private String name;
        private boolean success;
        private JsonObject arguments;
        private JsonElement result;
        @SerializedName("duration_ms")
        private int durationMs;
        private boolean cached;
        private String error;

        public String getName() { return name == null ? "" : name; }
        public boolean isSuccess() { return success; }
        public JsonObject getArguments() { return arguments == null ? new JsonObject() : arguments.deepCopy(); }
        public JsonElement getResult() { return result == null ? JsonNull.INSTANCE : result.deepCopy(); }
        public int getDurationMs() { return durationMs; }
        public boolean isCached() { return cached; }
        public String getError() { return error == null ? "" : error; }
    }

    public static final class ChatError {
        private final int statusCode;
        private final String code;
        private final String message;
        private final JsonElement details;

        public ChatError(int statusCode, String code, String message) {
            this(statusCode, code, message, JsonNull.INSTANCE);
        }

        public ChatError(int statusCode, String code, String message, JsonElement details) {
            this.statusCode = statusCode;
            this.code = code == null ? "unknown_error" : code;
            this.message = message == null ? "请求失败" : message;
            this.details = details == null ? JsonNull.INSTANCE : details.deepCopy();
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

        public JsonElement getDetails() {
            return details.deepCopy();
        }
    }
}
