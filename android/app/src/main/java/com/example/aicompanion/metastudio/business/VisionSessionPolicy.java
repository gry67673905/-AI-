package com.example.aicompanion.metastudio.business;

import android.annotation.SuppressLint;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.VisionSession;

import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.net.URI;
import java.util.regex.Pattern;

/** Validates native-only visual credentials before a camera or WebSocket is opened. */
@SuppressLint("NewApi") // DigitalHumanActivity is hard-gated to API 29+.
public final class VisionSessionPolicy {
    private static final Pattern OPAQUE_ID = Pattern.compile("[A-Za-z0-9._:-]{1,256}");

    public Decision validate(VisionSession session) {
        if (session == null) return Decision.denied("invalid_vision_session", "视觉会话响应为空");
        if (!OPAQUE_ID.matcher(session.getVisionSessionId()).matches()) {
            return Decision.denied("invalid_vision_session_id", "视觉会话标识无效");
        }
        URI websocketEndpoint;
        try {
            websocketEndpoint = URI.create(session.getWebsocketUrl());
        } catch (RuntimeException invalid) {
            return Decision.denied("invalid_vision_websocket", "视觉通道地址无效");
        }
        if (!"wss".equalsIgnoreCase(websocketEndpoint.getScheme())
            || websocketEndpoint.getHost() == null
            || !"/api/v1/integrations/metastudio/vision/ws".equals(websocketEndpoint.getPath())
            || websocketEndpoint.getUserInfo() != null
            || websocketEndpoint.getRawQuery() != null
            || websocketEndpoint.getRawFragment() != null) {
            return Decision.denied("invalid_vision_websocket", "视觉通道地址无效");
        }
        String token = session.getVisionToken();
        if (token.length() < 16 || token.length() > 4096 || containsControl(token)) {
            return Decision.denied("invalid_vision_token", "视觉会话鉴权信息无效");
        }
        String expiresAt = session.getExpiresAt();
        if (expiresAt.isEmpty() || expiresAt.length() > 80 || containsControl(expiresAt)) {
            return Decision.denied("invalid_vision_expiry", "视觉会话有效期格式无效");
        }
        try {
            if (!Instant.parse(expiresAt).isAfter(Instant.now().plusSeconds(3))) {
                return Decision.denied("expired_vision_session", "视觉会话已过期");
            }
        } catch (DateTimeParseException invalid) {
            return Decision.denied("invalid_vision_expiry", "视觉会话有效期格式无效");
        }
        return Decision.allowed();
    }

    private static boolean containsControl(String value) {
        for (int index = 0; index < value.length(); index++) {
            if (Character.isISOControl(value.charAt(index))) return true;
        }
        return false;
    }

    public static final class Decision {
        private final boolean allowed;
        private final String code;
        private final String message;

        private Decision(boolean allowed, String code, String message) {
            this.allowed = allowed;
            this.code = code;
            this.message = message;
        }

        static Decision allowed() { return new Decision(true, "", ""); }
        static Decision denied(String code, String message) {
            return new Decision(false, code, message);
        }
        public boolean isAllowed() { return allowed; }
        public String getCode() { return code; }
        public String getMessage() { return message; }
    }
}
