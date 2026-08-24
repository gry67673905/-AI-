package com.example.aicompanion.metastudio.business;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.NavigationIntent;
import com.example.aicompanion.portal.business.RoleNavigationPolicy;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** Converts backend suggestions into fixed portal navigation and harmless prefill only. */
public final class DigitalHumanActionPolicy {
    private static final Pattern ID = Pattern.compile("[A-Za-z0-9._:-]{1,256}");
    private static final Pattern TYPE = Pattern.compile("[A-Z][A-Z0-9_]{0,63}");
    private static final int MAX_LABEL = 80;
    private static final int MAX_PREFILL_VALUE = 1000;

    private static final Map<String, Set<String>> PREFILL_FIELDS;
    static {
        Map<String, Set<String>> fields = new HashMap<>();
        fields.put("consultation", set("chat_message"));
        fields.put("services", set("service_query", "service_id", "applicant_type"));
        fields.put("login", set("account"));
        fields.put("applications", set(
            "service_id", "application_id", "requirement_id", "application_version",
            "payment_id", "verification_id", "delivery_id", "window_id", "appointment_id"
        ));
        fields.put("staff_tasks", set("task_id", "application_id"));
        fields.put("staff_handoffs", set("ticket_id"));
        fields.put("admin_catalog", set("service_id", "version_id"));
        fields.put("admin_people", set("department_id", "window_id", "user_id"));
        fields.put("admin_knowledge", set("knowledge_job_id"));
        PREFILL_FIELDS = Collections.unmodifiableMap(fields);
    }

    private final RoleNavigationPolicy navigationPolicy = new RoleNavigationPolicy();

    public Decision validate(JsonElement raw, String expectedIntentId, Role role) {
        JsonObject object = unwrap(raw);
        String intentId = string(object, "intent_id");
        String type = string(object, "type").toUpperCase(java.util.Locale.ROOT);
        String label = string(object, "label");
        String section = string(object, "section");
        boolean confirmation = bool(object, "requires_confirmation");

        if (!ID.matcher(intentId).matches() || !intentId.equals(expectedIntentId)) {
            return Decision.denied("intent_mismatch", "数字人操作意图响应不匹配");
        }
        if (!TYPE.matcher(type).matches()) {
            return Decision.denied("invalid_intent_type", "数字人操作类型无效");
        }
        if (label.isEmpty() || label.length() > MAX_LABEL || containsControl(label)) {
            return Decision.denied("invalid_intent_label", "数字人操作说明无效");
        }
        Role effectiveRole = role == null ? Role.ANONYMOUS : role;
        if (!navigationPolicy.canNavigate(effectiveRole, section)) {
            return Decision.denied("forbidden_navigation", "当前账号不能打开数字人建议的工作台");
        }
        if (!confirmation) {
            return Decision.denied("confirmation_required", "数字人操作必须由用户确认");
        }
        // Appointments are rendered inside the existing citizen applications workspace.
        String portalSection = "appointments".equals(section) ? "applications" : section;
        JsonObject prefill = sanitizePrefill(portalSection, object.get("prefill"));
        return Decision.allowed(new NavigationIntent(intentId, type, label, portalSection, prefill, true));
    }

    /** Re-validates the non-exported Activity result in the portal process before DOM dispatch. */
    public Decision validatePortalEvent(JsonElement raw, Role role) {
        if (raw == null || !raw.isJsonObject()) {
            return Decision.denied("invalid_portal_intent", "数字人操作结果无效");
        }
        JsonObject event = raw.getAsJsonObject();
        if (!"digital_human_intent".equals(string(event, "type"))) {
            return Decision.denied("invalid_portal_intent", "数字人操作结果类型无效");
        }
        String intentId = string(event, "intent_id");
        JsonObject normalized = event.deepCopy();
        normalized.addProperty("type", string(event, "intent_type"));
        return validate(normalized, intentId, role);
    }

    private static JsonObject sanitizePrefill(String section, JsonElement raw) {
        JsonObject output = new JsonObject();
        Set<String> allowed = PREFILL_FIELDS.get(section);
        if (allowed == null || raw == null || !raw.isJsonObject()) return output;
        for (Map.Entry<String, JsonElement> entry : raw.getAsJsonObject().entrySet()) {
            if (!allowed.contains(entry.getKey())) continue;
            JsonElement value = entry.getValue();
            if (value == null || !value.isJsonPrimitive()) continue;
            String text = value.getAsString().trim();
            if (text.length() > MAX_PREFILL_VALUE || containsControl(text)) continue;
            output.addProperty(entry.getKey(), text);
        }
        return output;
    }

    private static JsonObject unwrap(JsonElement raw) {
        if (raw == null || !raw.isJsonObject()) return new JsonObject();
        JsonObject root = raw.getAsJsonObject();
        JsonElement data = root.get("data");
        if (data != null && data.isJsonObject()) root = data.getAsJsonObject();
        JsonElement navigation = root.get("navigation");
        return navigation != null && navigation.isJsonObject() ? navigation.getAsJsonObject() : root;
    }

    private static String string(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() ? value.getAsString().trim() : "";
    }

    private static boolean bool(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isBoolean()
            && value.getAsBoolean();
    }

    private static boolean containsControl(String value) {
        for (int i = 0; i < value.length(); i++) if (Character.isISOControl(value.charAt(i))) return true;
        return false;
    }

    private static Set<String> set(String... values) {
        return Collections.unmodifiableSet(new HashSet<>(Arrays.asList(values)));
    }

    public static final class Decision {
        private final NavigationIntent intent;
        private final String code;
        private final String message;

        private Decision(NavigationIntent intent, String code, String message) {
            this.intent = intent;
            this.code = code;
            this.message = message;
        }

        static Decision allowed(NavigationIntent intent) { return new Decision(intent, "", ""); }
        static Decision denied(String code, String message) { return new Decision(null, code, message); }
        public boolean isAllowed() { return intent != null; }
        public NavigationIntent getIntent() { return intent; }
        public String getCode() { return code; }
        public String getMessage() { return message; }
    }
}
