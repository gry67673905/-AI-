package com.example.aicompanion.portal.business;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Explains missing required/conditional materials without replacing server validation. */
public final class MaterialCompletionPolicy {
    public Result evaluate(JsonArray requirements, JsonArray uploaded, JsonObject formValues) {
        Set<String> uploadedIds = new HashSet<>();
        if (uploaded != null) {
            for (JsonElement item : uploaded) {
                if (item.isJsonObject()) {
                    String id = string(item.getAsJsonObject(), "requirement_id");
                    if (!id.isEmpty()) uploadedIds.add(id);
                }
            }
        }
        List<MissingMaterial> missing = new ArrayList<>();
        if (requirements != null) {
            for (JsonElement item : requirements) {
                if (!item.isJsonObject()) continue;
                JsonObject requirement = item.getAsJsonObject();
                String id = string(requirement, "id");
                if (id.isEmpty() || uploadedIds.contains(id)) continue;
                String kind = string(requirement, "kind").toUpperCase(java.util.Locale.ROOT);
                boolean needed = "REQUIRED".equals(kind);
                String reason = "事项要求必须上传";
                if ("CONDITIONAL".equals(kind)) {
                    needed = conditionMatches(requirement.get("condition"), formValues);
                    reason = string(requirement, "trigger_reason");
                    if (reason.isEmpty()) reason = "当前填写条件触发此材料";
                }
                if (needed) missing.add(new MissingMaterial(id, string(requirement, "name"), reason));
            }
        }
        return new Result(missing);
    }

    private static boolean conditionMatches(JsonElement condition, JsonObject values) {
        if (condition == null || !condition.isJsonObject() || values == null) return false;
        JsonObject object = condition.getAsJsonObject();
        String field = string(object, "field");
        JsonElement expected = object.get("eq");
        JsonElement actual = values.get(field);
        return !field.isEmpty() && expected != null && actual != null && expected.equals(actual);
    }

    private static String string(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()
            ? value.getAsString() : "";
    }

    public static final class MissingMaterial {
        private final String requirementId;
        private final String name;
        private final String reason;

        MissingMaterial(String requirementId, String name, String reason) {
            this.requirementId = requirementId;
            this.name = name;
            this.reason = reason;
        }

        public String getRequirementId() { return requirementId; }
        public String getName() { return name; }
        public String getReason() { return reason; }
    }

    public static final class Result {
        private final List<MissingMaterial> missing;

        Result(List<MissingMaterial> missing) {
            this.missing = Collections.unmodifiableList(new ArrayList<>(missing));
        }

        public boolean isComplete() { return missing.isEmpty(); }
        public List<MissingMaterial> getMissing() { return missing; }
    }
}
