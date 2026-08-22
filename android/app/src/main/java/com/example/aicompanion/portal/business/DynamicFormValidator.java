package com.example.aicompanion.portal.business;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/** Small client-side JSON Schema subset; the backend remains authoritative. */
public final class DynamicFormValidator {
    public ValidationResult validate(JsonObject schema, JsonObject values) {
        List<String> errors = new ArrayList<>();
        if (schema == null || values == null) {
            errors.add("表单定义或数据为空");
            return new ValidationResult(errors);
        }
        JsonArray required = schema.has("required") && schema.get("required").isJsonArray()
            ? schema.getAsJsonArray("required") : new JsonArray();
        for (JsonElement item : required) {
            if (!item.isJsonPrimitive() || !item.getAsJsonPrimitive().isString()) continue;
            String key = item.getAsString();
            JsonElement value = values.get(key);
            if (value == null || value.isJsonNull() || (value.isJsonPrimitive()
                && value.getAsJsonPrimitive().isString() && value.getAsString().trim().isEmpty())) {
                errors.add(key + " 为必填项");
            }
        }
        JsonObject properties = schema.has("properties") && schema.get("properties").isJsonObject()
            ? schema.getAsJsonObject("properties") : new JsonObject();
        for (Map.Entry<String, JsonElement> entry : properties.entrySet()) {
            JsonElement value = values.get(entry.getKey());
            if (value == null || value.isJsonNull() || !entry.getValue().isJsonObject()) continue;
            JsonObject field = entry.getValue().getAsJsonObject();
            String type = string(field, "type");
            if (!matchesType(type, value)) {
                errors.add(entry.getKey() + " 类型不正确");
                continue;
            }
            if (value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()) {
                int length = value.getAsString().codePointCount(0, value.getAsString().length());
                if (field.has("minLength") && length < field.get("minLength").getAsInt()) {
                    errors.add(entry.getKey() + " 长度不足");
                }
                if (field.has("maxLength") && length > field.get("maxLength").getAsInt()) {
                    errors.add(entry.getKey() + " 长度超限");
                }
            }
        }
        return new ValidationResult(errors);
    }

    private static boolean matchesType(String type, JsonElement value) {
        if (type.isEmpty()) return true;
        switch (type) {
            case "string": return value.isJsonPrimitive() && value.getAsJsonPrimitive().isString();
            case "number": return value.isJsonPrimitive() && value.getAsJsonPrimitive().isNumber();
            case "integer":
                if (!value.isJsonPrimitive() || !value.getAsJsonPrimitive().isNumber()) return false;
                try { return value.getAsBigDecimal().stripTrailingZeros().scale() <= 0; }
                catch (NumberFormatException error) { return false; }
            case "boolean": return value.isJsonPrimitive() && value.getAsJsonPrimitive().isBoolean();
            case "array": return value.isJsonArray();
            case "object": return value.isJsonObject();
            default: return false;
        }
    }

    private static String string(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()
            ? value.getAsString() : "";
    }

    public static final class ValidationResult {
        private final List<String> errors;

        ValidationResult(List<String> errors) {
            this.errors = Collections.unmodifiableList(new ArrayList<>(errors));
        }

        public boolean isValid() { return errors.isEmpty(); }
        public List<String> getErrors() { return errors; }
    }
}
