package com.example.aicompanion.metastudio.business;

import android.annotation.SuppressLint;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.ClientSession;

import java.time.Instant;
import java.time.format.DateTimeParseException;
import java.util.regex.Pattern;

/** Rejects launch packages that could redirect the Web SDK or expose malformed credentials. */
@SuppressLint("NewApi") // DigitalHumanActivity is hard-gated to API 29+.
public final class DigitalHumanSessionPolicy {
    public static final String BEIJING_FOUR_SERVER = "metastudio-api.cn-north-4.myhuaweicloud.com";

    private static final Pattern OPAQUE_ID = Pattern.compile("[A-Za-z0-9._:-]{1,256}");
    private static final Pattern ROBOT_ID = Pattern.compile("[A-Za-z0-9_-]{1,128}");

    public Decision validate(ClientSession session) {
        if (session == null) return Decision.denied("invalid_session", "数字人会话响应为空");
        if (!OPAQUE_ID.matcher(session.getSessionId()).matches()) {
            return Decision.denied("invalid_session_id", "数字人会话标识无效");
        }
        if (session.getOnceCode().length() < 8 || session.getOnceCode().length() > 4096
            || containsControl(session.getOnceCode())) {
            return Decision.denied("invalid_once_code", "数字人一次性鉴权码无效");
        }
        if (!ROBOT_ID.matcher(session.getRobotId()).matches()) {
            return Decision.denied("invalid_robot_id", "数字人活动标识无效");
        }
        if (!BEIJING_FOUR_SERVER.equals(session.getServerAddress())) {
            return Decision.denied("invalid_server_address", "数字人服务地址不在北京四白名单中");
        }
        if (session.getExpiresAt().isEmpty() || session.getExpiresAt().length() > 80
            || containsControl(session.getExpiresAt())) {
            return Decision.denied("invalid_expiry", "数字人会话有效期格式无效");
        }
        try {
            Instant expiresAt = Instant.parse(session.getExpiresAt());
            if (!expiresAt.isAfter(Instant.now().plusSeconds(3))) {
                return Decision.denied("expired_session", "数字人会话已过期");
            }
        } catch (DateTimeParseException invalid) {
            return Decision.denied("invalid_expiry", "数字人会话有效期格式无效");
        }
        return Decision.allowed();
    }

    private static boolean containsControl(String value) {
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (Character.isISOControl(c)) return true;
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
        static Decision denied(String code, String message) { return new Decision(false, code, message); }
        public boolean isAllowed() { return allowed; }
        public String getCode() { return code; }
        public String getMessage() { return message; }
    }
}
