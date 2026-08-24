package com.example.aicompanion.metastudio.model;

import com.google.gson.JsonObject;

/** Native-only wire models. Credentials in ClientSession must never cross back to the portal WebView. */
public final class DigitalHumanContract {
    private DigitalHumanContract() {}

    public static final class ClientSession {
        private final String sessionId;
        private final String onceCode;
        private final String robotId;
        private final String serverAddress;
        private final String expiresAt;

        public ClientSession(
            String sessionId,
            String onceCode,
            String robotId,
            String serverAddress,
            String expiresAt
        ) {
            this.sessionId = clean(sessionId);
            this.onceCode = clean(onceCode);
            this.robotId = clean(robotId);
            this.serverAddress = clean(serverAddress);
            this.expiresAt = clean(expiresAt);
        }

        public String getSessionId() { return sessionId; }
        public String getOnceCode() { return onceCode; }
        public String getRobotId() { return robotId; }
        public String getServerAddress() { return serverAddress; }
        public String getExpiresAt() { return expiresAt; }

        /** Only the dedicated isolated WebView receives this short-lived launch package. */
        public JsonObject toWebMessage() {
            JsonObject payload = new JsonObject();
            payload.addProperty("type", "client_session");
            payload.addProperty("session_id", sessionId);
            payload.addProperty("once_code", onceCode);
            payload.addProperty("robot_id", robotId);
            payload.addProperty("server_address", serverAddress);
            payload.addProperty("expires_at", expiresAt);
            return payload;
        }
    }

    public static final class SemanticIntent {
        private final String chatId;
        private final String intentId;

        public SemanticIntent(String chatId, String intentId) {
            this.chatId = clean(chatId);
            this.intentId = clean(intentId);
        }

        public String getChatId() { return chatId; }
        public String getIntentId() { return intentId; }
    }

    public static final class NavigationIntent {
        private final String intentId;
        private final String type;
        private final String label;
        private final String section;
        private final JsonObject prefill;
        private final boolean requiresConfirmation;

        public NavigationIntent(
            String intentId,
            String type,
            String label,
            String section,
            JsonObject prefill,
            boolean requiresConfirmation
        ) {
            this.intentId = clean(intentId);
            this.type = clean(type);
            this.label = clean(label);
            this.section = clean(section);
            this.prefill = prefill == null ? new JsonObject() : prefill.deepCopy();
            this.requiresConfirmation = requiresConfirmation;
        }

        public String getIntentId() { return intentId; }
        public String getType() { return type; }
        public String getLabel() { return label; }
        public String getSection() { return section; }
        public JsonObject getPrefill() { return prefill.deepCopy(); }
        public boolean isRequiresConfirmation() { return requiresConfirmation; }

        public JsonObject toPortalEvent() {
            JsonObject event = new JsonObject();
            event.addProperty("type", "digital_human_intent");
            event.addProperty("intent_id", intentId);
            event.addProperty("intent_type", type);
            event.addProperty("label", label);
            event.addProperty("section", section);
            event.add("prefill", prefill.deepCopy());
            event.addProperty("requires_confirmation", true);
            return event;
        }
    }

    private static String clean(String value) {
        return value == null ? "" : value.trim();
    }
}
