package com.example.aicompanion.portal.business;

import com.example.aicompanion.portal.model.PortalContract.Command;
import com.example.aicompanion.portal.model.PortalContract.CommandEnvelope;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParseException;

import java.util.Arrays;
import java.util.Collections;
import java.util.EnumSet;
import java.util.HashSet;
import java.util.Set;
import java.util.regex.Pattern;

/** Pure business policy for the narrow JS command bridge. */
public final class PortalCommandPolicy {
    public static final int MAX_ENVELOPE_BYTES = 64 * 1024;
    private static final int MAX_DEPTH = 8;
    private static final int MAX_STRING_LENGTH = 12 * 1024;
    private static final Pattern REQUEST_ID = Pattern.compile("[A-Za-z0-9._:-]{1,64}");
    private static final Pattern RESOURCE_ID = Pattern.compile("[A-Za-z0-9_-]{1,128}");
    private static final Set<String> FORBIDDEN_KEYS = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
        "url", "uri", "endpoint", "http_method", "method", "native_method", "native_class", "class_name"
    )));
    private static final EnumSet<Command> PUBLIC_COMMANDS = EnumSet.of(
        Command.AUTH_SEND_CODE,
        Command.AUTH_REGISTER,
        Command.AUTH_LOGIN,
        Command.CATALOG_SEARCH,
        Command.CATALOG_DETAILS,
        Command.ELIGIBILITY_CHECK,
        Command.MATERIALS_GET,
        Command.PROCESS_GET,
        Command.FORM_SCHEMA_GET,
        Command.WINDOW_LIST,
        Command.CHAT_SESSION_RESET,
        Command.CHAT_STREAM
    );
    private static final EnumSet<Command> CITIZEN_COMMANDS = EnumSet.of(
        Command.AUTH_LOGOUT,
        Command.AUTH_ME,
        Command.APPLICATION_CREATE,
        Command.APPLICATION_LIST,
        Command.APPLICATION_DETAILS,
        Command.APPLICATION_UPDATE_FORM,
        Command.APPLICATION_SUBMIT,
        Command.APPLICATION_SUPPLEMENT,
        Command.APPLICATION_WITHDRAW,
        Command.APPLICATION_DISCARD,
        Command.APPLICATION_TIMELINE,
        Command.MATERIAL_TEMPLATE_OPTIONS_GET,
        Command.MATERIAL_TEMPLATE_GENERATE,
        Command.MATERIAL_TEMPLATE_STATUS_GET,
        Command.DELIVERY_SET,
        Command.APPOINTMENT_LIST,
        Command.APPOINTMENT_BOOK,
        Command.APPOINTMENT_CANCEL,
        Command.PAYMENT_CREATE,
        Command.PAYMENT_CONFIRM,
        Command.PAYMENT_CANCEL,
        Command.VERIFICATION_CREATE,
        Command.VERIFICATION_CONFIRM,
        Command.DELIVERY_CANCEL,
        Command.CONSULTATION_HISTORY,
        Command.CONSULTATION_MESSAGES,
        Command.CONSULTATION_MATERIAL_CONFIRM,
        Command.CONSULTATION_FEEDBACK,
        Command.HANDOFF_CREATE,
        Command.HANDOFF_MESSAGES,
        Command.HANDOFF_MESSAGE_ADD,
        Command.HANDOFF_CANCEL
    );
    private static final EnumSet<Command> STAFF_COMMANDS = EnumSet.of(
        Command.AUTH_LOGOUT,
        Command.AUTH_ME,
        Command.STAFF_TASKS,
        Command.STAFF_CLAIM,
        Command.STAFF_SUPPLEMENT,
        Command.STAFF_APPROVE,
        Command.STAFF_REJECT,
        Command.STAFF_COMPLETE,
        Command.STAFF_HANDOFFS,
        Command.STAFF_HANDOFF_REPLY,
        Command.STAFF_HANDOFF_RESOLVE
    );
    private static final EnumSet<Command> ADMIN_COMMANDS = EnumSet.of(
        Command.AUTH_LOGOUT,
        Command.AUTH_ME,
        Command.ADMIN_METRICS,
        Command.ADMIN_DEPARTMENTS,
        Command.ADMIN_DEPARTMENT_CREATE,
        Command.ADMIN_WINDOWS,
        Command.ADMIN_WINDOW_CREATE,
        Command.ADMIN_ACCOUNTS,
        Command.ADMIN_SERVICES,
        Command.ADMIN_STAFF_CREATE,
        Command.ADMIN_USER_FREEZE,
        Command.ADMIN_SERVICE_CREATE,
        Command.ADMIN_SERVICE_VERSION,
        Command.ADMIN_SERVICE_LIFECYCLE,
        Command.ADMIN_KNOWLEDGE_RETRY,
        Command.ADMIN_KNOWLEDGE_ARCHIVE,
        Command.ADMIN_AUDIT
    );

    private final Gson gson;

    public PortalCommandPolicy() {
        this(new Gson());
    }

    PortalCommandPolicy(Gson gson) {
        this.gson = gson;
    }

    public Decision validate(String rawEnvelope, Role role) {
        if (rawEnvelope == null || rawEnvelope.trim().isEmpty()) {
            return Decision.denied("invalid_command", "命令不能为空");
        }
        if (rawEnvelope.getBytes(java.nio.charset.StandardCharsets.UTF_8).length > MAX_ENVELOPE_BYTES) {
            return Decision.denied("payload_too_large", "命令数据超过 64KB 限制");
        }

        final CommandEnvelope envelope;
        try {
            envelope = gson.fromJson(rawEnvelope, CommandEnvelope.class);
        } catch (JsonParseException | IllegalStateException error) {
            return Decision.denied("invalid_json", "命令不是有效 JSON");
        }
        if (envelope == null || envelope.getCommand() == null) {
            return Decision.denied("unknown_command", "命令不在允许列表中");
        }
        if (!REQUEST_ID.matcher(envelope.getRequestId()).matches()) {
            return Decision.denied("invalid_request_id", "request_id 格式无效");
        }
        Role effectiveRole = role == null ? Role.ANONYMOUS : role;
        if (!isAllowed(envelope.getCommand(), effectiveRole)) {
            return Decision.denied("forbidden", "当前账号无权执行该操作");
        }
        String structuralError = validateTree(envelope.getPayload(), 0);
        if (structuralError != null) return Decision.denied("invalid_payload", structuralError);
        String fieldError = validateRequiredFields(envelope.getCommand(), envelope.getPayload());
        if (fieldError != null) return Decision.denied("invalid_payload", fieldError);
        return Decision.allowed(envelope);
    }

    public boolean isAllowed(Command command, Role role) {
        if (command == null) return false;
        if (PUBLIC_COMMANDS.contains(command)) return true;
        if (role == Role.CITIZEN) return CITIZEN_COMMANDS.contains(command);
        if (role == Role.STAFF) return STAFF_COMMANDS.contains(command);
        if (role == Role.ADMIN) return ADMIN_COMMANDS.contains(command);
        return false;
    }

    public static boolean isSafeResourceId(String value) {
        return value != null && RESOURCE_ID.matcher(value).matches();
    }

    private static String validateTree(JsonElement value, int depth) {
        if (depth > MAX_DEPTH) return "命令嵌套层级过深";
        if (value == null || value.isJsonNull()) return null;
        if (value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()) {
            return value.getAsString().length() > MAX_STRING_LENGTH ? "字段内容过长" : null;
        }
        if (value.isJsonArray()) {
            JsonArray array = value.getAsJsonArray();
            if (array.size() > 200) return "数组元素过多";
            for (JsonElement item : array) {
                String error = validateTree(item, depth + 1);
                if (error != null) return error;
            }
        } else if (value.isJsonObject()) {
            JsonObject object = value.getAsJsonObject();
            if (object.size() > 100) return "对象字段过多";
            for (String key : object.keySet()) {
                if (FORBIDDEN_KEYS.contains(key.toLowerCase(java.util.Locale.ROOT))) {
                    return "命令不得指定 URL、HTTP 方法或原生方法";
                }
                String error = validateTree(object.get(key), depth + 1);
                if (error != null) return error;
            }
        }
        return null;
    }

    private static String validateRequiredFields(Command command, JsonObject payload) {
        switch (command) {
            case AUTH_LOGIN:
                return requireNonBlank(payload, "username", "password");
            case AUTH_REGISTER:
                return requireNonBlank(payload, "username", "password", "applicant_type", "verification_code");
            case AUTH_SEND_CODE:
                return requireNonBlank(payload, "destination");
            case CHAT_STREAM:
                String messageError = requireNonBlank(payload, "message");
                if (messageError != null) return messageError;
                String message = payload.get("message").getAsString().trim();
                int length = message.codePointCount(0, message.length());
                if (length > 1000) return "message 不能超过 1000 个字符";
                String chatSessionError = optionalSafeId(payload, "session_id");
                if (chatSessionError != null) return chatSessionError;
                String chatServiceError = optionalSafeId(payload, "service_id");
                return chatServiceError == null
                    ? optionalSafeId(payload, "application_id") : chatServiceError;
            case CHAT_SESSION_RESET:
                return payload.size() == 0 ? null : "CHAT_SESSION_RESET 不接受参数";
            case CATALOG_DETAILS:
            case ELIGIBILITY_CHECK:
            case MATERIALS_GET:
            case PROCESS_GET:
            case FORM_SCHEMA_GET:
            case WINDOW_LIST:
            case APPLICATION_CREATE:
                return requireSafeId(payload, "service_id");
            case APPLICATION_DETAILS:
            case APPLICATION_UPDATE_FORM:
            case APPLICATION_SUBMIT:
            case APPLICATION_SUPPLEMENT:
            case APPLICATION_WITHDRAW:
            case APPLICATION_DISCARD:
            case APPLICATION_TIMELINE:
            case DELIVERY_SET:
            case STAFF_SUPPLEMENT:
            case STAFF_APPROVE:
            case STAFF_REJECT:
            case STAFF_COMPLETE:
                return requireSafeId(payload, "application_id");
            case MATERIAL_TEMPLATE_OPTIONS_GET:
                return requireSafeId(payload, "application_id");
            case MATERIAL_TEMPLATE_GENERATE:
                String applicationError = requireSafeId(payload, "application_id");
                if (applicationError != null) return applicationError;
                String requirementError = requireSafeId(payload, "requirement_code");
                if (requirementError != null) return requirementError;
                String templateError = requireSafeId(payload, "template_id");
                if (templateError != null) return templateError;
                JsonElement requestText = payload.get("request_text");
                if (requestText != null && !requestText.isJsonNull()) {
                    if (!requestText.isJsonPrimitive() || !requestText.getAsJsonPrimitive().isString()) {
                        return "request_text 必须是字符串";
                    }
                    String text = requestText.getAsString();
                    if (text.codePointCount(0, text.length()) > 300) {
                        return "request_text 不能超过 300 个字符";
                    }
                }
                return null;
            case MATERIAL_TEMPLATE_STATUS_GET:
                return requireSafeId(payload, "generation_id");
            case CONSULTATION_HISTORY:
                String historyCursorError = optionalSafeId(payload, "cursor");
                return historyCursorError == null
                    ? optionalBoundedInteger(payload, "limit", 1, 100) : historyCursorError;
            case CONSULTATION_MESSAGES:
                String messagesSessionError = requireSafeId(payload, "session_id");
                if (messagesSessionError != null) return messagesSessionError;
                String beforeError = optionalSafeId(payload, "before");
                return beforeError == null
                    ? optionalBoundedInteger(payload, "limit", 1, 50) : beforeError;
            case CONSULTATION_MATERIAL_CONFIRM:
                String consultationSessionError = requireSafeId(payload, "session_id");
                return consultationSessionError == null
                    ? requireSafeId(payload, "intent_id") : consultationSessionError;
            case APPOINTMENT_CANCEL:
                return requireSafeId(payload, "appointment_id");
            case APPOINTMENT_BOOK:
                String serviceError = requireSafeId(payload, "service_id");
                return serviceError == null ? requireSafeId(payload, "window_id") : serviceError;
            case PAYMENT_CONFIRM:
            case PAYMENT_CANCEL:
                return requireSafeId(payload, "payment_id");
            case PAYMENT_CREATE:
            case VERIFICATION_CREATE:
                return requireSafeId(payload, "application_id");
            case VERIFICATION_CONFIRM:
                return requireSafeId(payload, "verification_id");
            case DELIVERY_CANCEL:
                return requireSafeId(payload, "delivery_id");
            case STAFF_CLAIM:
                return requireSafeId(payload, "task_id");
            case HANDOFF_MESSAGES:
            case HANDOFF_MESSAGE_ADD:
            case HANDOFF_CANCEL:
            case STAFF_HANDOFF_REPLY:
            case STAFF_HANDOFF_RESOLVE:
                return requireSafeId(payload, "ticket_id");
            case ADMIN_USER_FREEZE:
                return requireSafeId(payload, "account_id");
            case ADMIN_DEPARTMENT_CREATE:
                return requireNonBlank(payload, "code", "name");
            case ADMIN_WINDOW_CREATE:
                return requireSafeId(payload, "department_id");
            case ADMIN_STAFF_CREATE:
                String departmentError = requireSafeId(payload, "department_id");
                return departmentError == null ? requireNonBlank(payload, "username", "password", "display_name") : departmentError;
            case ADMIN_SERVICE_CREATE:
                String serviceDepartmentError = requireSafeId(payload, "department_id");
                return serviceDepartmentError == null
                    ? requireNonBlank(payload, "code", "title", "summary", "applicant_type") : serviceDepartmentError;
            case ADMIN_SERVICE_VERSION:
            case ADMIN_SERVICE_LIFECYCLE:
                return requireSafeId(payload, "service_id");
            case ADMIN_KNOWLEDGE_RETRY:
            case ADMIN_KNOWLEDGE_ARCHIVE:
                return requireSafeId(payload, "job_id");
            case HANDOFF_CREATE:
                String sessionError = requireSafeId(payload, "session_id");
                return sessionError == null ? requireNonBlank(payload, "subject") : sessionError;
            default:
                return null;
        }
    }

    private static String requireSafeId(JsonObject payload, String key) {
        String missing = requireNonBlank(payload, key);
        if (missing != null) return missing;
        return isSafeResourceId(payload.get(key).getAsString()) ? null : key + " 格式无效";
    }

    private static String optionalSafeId(JsonObject payload, String key) {
        JsonElement value = payload.get(key);
        if (value == null || value.isJsonNull()) return null;
        if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()
            || !isSafeResourceId(value.getAsString())) {
            return key + " 格式无效";
        }
        return null;
    }

    private static String optionalBoundedInteger(
        JsonObject payload, String key, int minimum, int maximum
    ) {
        JsonElement value = payload.get(key);
        if (value == null || value.isJsonNull()) return null;
        if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()) {
            return key + " 必须是整数字符串";
        }
        try {
            int parsed = Integer.parseInt(value.getAsString());
            return parsed >= minimum && parsed <= maximum
                ? null : key + " 超出允许范围";
        } catch (NumberFormatException ignored) {
            return key + " 必须是整数字符串";
        }
    }

    private static String requireNonBlank(JsonObject payload, String... keys) {
        for (String key : keys) {
            JsonElement value = payload.get(key);
            if (value == null || !value.isJsonPrimitive() || !value.getAsJsonPrimitive().isString()
                || value.getAsString().trim().isEmpty()) {
                return "缺少字段 " + key;
            }
        }
        return null;
    }

    public static final class Decision {
        private final CommandEnvelope envelope;
        private final String code;
        private final String message;

        private Decision(CommandEnvelope envelope, String code, String message) {
            this.envelope = envelope;
            this.code = code;
            this.message = message;
        }

        static Decision allowed(CommandEnvelope envelope) {
            return new Decision(envelope, "", "");
        }

        static Decision denied(String code, String message) {
            return new Decision(null, code, message);
        }

        public boolean isAllowed() { return envelope != null; }
        public CommandEnvelope getEnvelope() { return envelope; }
        public String getCode() { return code; }
        public String getMessage() { return message; }
    }
}
