package com.example.aicompanion.portal.gateway;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;

import java.util.LinkedHashMap;
import java.util.Map;

final class GatewayPayload {
    private GatewayPayload() {}

    static String string(JsonObject payload, String key) {
        if (payload == null) return "";
        JsonElement value = payload.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()
            ? value.getAsString() : "";
    }

    static boolean bool(JsonObject payload, String key, boolean fallback) {
        if (payload == null) return fallback;
        JsonElement value = payload.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isBoolean()
            ? value.getAsBoolean() : fallback;
    }

    static Map<String, String> query(JsonObject payload, String... keys) {
        Map<String, String> result = new LinkedHashMap<>();
        for (String key : keys) {
            String value = string(payload, key);
            if (!value.isEmpty()) result.put(key, value);
        }
        return result;
    }

    static JsonObject object(JsonElement element) {
        return element != null && element.isJsonObject() ? element.getAsJsonObject() : new JsonObject();
    }

    static JsonObject unwrapObject(JsonElement element) {
        JsonObject root = object(element);
        JsonElement data = root.get("data");
        return data != null && data.isJsonObject() ? data.getAsJsonObject() : root;
    }
}
