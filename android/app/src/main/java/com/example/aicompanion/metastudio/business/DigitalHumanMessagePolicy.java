package com.example.aicompanion.metastudio.business;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.SemanticIntent;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;

/** Narrow protocol accepted from the isolated wrapper page. Answers and credentials are not accepted. */
public final class DigitalHumanMessagePolicy {
    public static final int MAX_MESSAGE_BYTES = 16 * 1024;
    private static final Pattern ID = Pattern.compile("[A-Za-z0-9._:-]{1,256}");
    private static final Set<String> SDK_STATUSES = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
        "checking_browser", "creating", "ready", "active", "ended",
        "unsupported", "sdk_missing", "error"
    )));

    public Decision validate(String raw) {
        if (raw == null || raw.getBytes(StandardCharsets.UTF_8).length > MAX_MESSAGE_BYTES) {
            return Decision.denied("invalid_web_message", "数字人页面消息无效");
        }
        final JsonObject object;
        try {
            JsonElement parsed = JsonParser.parseString(raw);
            if (!parsed.isJsonObject()) throw new IllegalArgumentException("not an object");
            object = parsed.getAsJsonObject();
        } catch (RuntimeException invalid) {
            return Decision.denied("invalid_web_message", "数字人页面消息不是有效JSON");
        }
        String event = string(object, "event");
        if ("page_ready".equals(event) || "close".equals(event)) return Decision.event(event);
        if ("sdk_status".equals(event)) {
            String status = string(object, "status");
            if (object.size() != 2 || !(SDK_STATUSES.contains(status)
                || DigitalHumanSdkDiagnostics.isAllowedErrorStatus(status)
                || DigitalHumanSdkDiagnostics.isAllowedEndpointStatus(status))) {
                return Decision.denied("invalid_status", "数字人状态消息无效");
            }
            return Decision.status(status);
        }
        if (!"semantic_final".equals(event)) {
            return Decision.denied("unsupported_web_message", "数字人页面消息类型不受支持");
        }
        String chatId = string(object, "chat_id");
        String intentId = string(object, "intent_id");
        if (!ID.matcher(chatId).matches() || !ID.matcher(intentId).matches()) {
            return Decision.denied("invalid_intent", "数字人操作意图标识无效");
        }
        if (!bool(object, "is_last")) {
            return Decision.denied("incomplete_semantic_result", "仅接受最终语义识别结果");
        }
        return Decision.semantic(new SemanticIntent(chatId, intentId));
    }

    private static String string(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()
            ? value.getAsString().trim() : "";
    }

    private static boolean bool(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isBoolean()
            && value.getAsBoolean();
    }

    public static final class Decision {
        private final boolean allowed;
        private final String event;
        private final String status;
        private final SemanticIntent semanticIntent;
        private final String code;
        private final String message;

        private Decision(
            boolean allowed,
            String event,
            String status,
            SemanticIntent semanticIntent,
            String code,
            String message
        ) {
            this.allowed = allowed;
            this.event = event;
            this.status = status;
            this.semanticIntent = semanticIntent;
            this.code = code;
            this.message = message;
        }

        static Decision event(String event) { return new Decision(true, event, "", null, "", ""); }
        static Decision status(String status) { return new Decision(true, "sdk_status", status, null, "", ""); }
        static Decision semantic(SemanticIntent intent) {
            return new Decision(true, "semantic_final", "", intent, "", "");
        }
        static Decision denied(String code, String message) {
            return new Decision(false, "", "", null, code, message);
        }

        public boolean isAllowed() { return allowed; }
        public String getEvent() { return event; }
        public String getStatus() { return status; }
        public SemanticIntent getSemanticIntent() { return semanticIntent; }
        public String getCode() { return code; }
        public String getMessage() { return message; }
    }
}
