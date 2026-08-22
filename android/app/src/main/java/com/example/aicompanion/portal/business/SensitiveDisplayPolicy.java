package com.example.aicompanion.portal.business;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonPrimitive;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

/** Last native-to-WebView guard: removes secrets and masks common synthetic identifiers. */
public final class SensitiveDisplayPolicy {
    private static final Set<String> SECRET_KEYS = new HashSet<>(Arrays.asList(
        "access_token", "refresh_token", "authorization", "password", "verification_code",
        "api_key", "secret", "token", "credential"
    ));
    private static final Pattern ID_CARD = Pattern.compile("(?<!\\d)(\\d{6})\\d{8}(\\d{3}[0-9Xx])(?!\\d)");
    private static final Pattern PHONE = Pattern.compile("(?<!\\d)(1\\d{2})\\d{4}(\\d{4})(?!\\d)");
    private static final Pattern BEARER = Pattern.compile("(?i)(bearer\\s+)[^\\s,;\\\"}]+");
    private static final Pattern NAMED_SECRET = Pattern.compile(
        "(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\\s*[:=]\\s*[\\\"']?)[^\\s,;\\\"'}]+"
    );
    private static final Pattern PROVIDER_KEY = Pattern.compile("(?i)sk-[a-z0-9_-]{8,}");

    public JsonElement sanitize(JsonElement input) {
        return sanitizeNode(input, 0);
    }

    private JsonElement sanitizeNode(JsonElement input, int depth) {
        if (input == null || input.isJsonNull() || depth > 20) return JsonNull.INSTANCE;
        if (input.isJsonArray()) {
            JsonArray output = new JsonArray();
            for (JsonElement item : input.getAsJsonArray()) output.add(sanitizeNode(item, depth + 1));
            return output;
        }
        if (input.isJsonObject()) {
            JsonObject output = new JsonObject();
            for (String key : input.getAsJsonObject().keySet()) {
                if (isSecretKey(key)) continue;
                output.add(key, sanitizeNode(input.getAsJsonObject().get(key), depth + 1));
            }
            return output;
        }
        if (input.isJsonPrimitive() && input.getAsJsonPrimitive().isString()) {
            String value = input.getAsString();
            value = BEARER.matcher(value).replaceAll("$1[REDACTED]");
            value = NAMED_SECRET.matcher(value).replaceAll("$1[REDACTED]");
            value = PROVIDER_KEY.matcher(value).replaceAll("[REDACTED]");
            value = ID_CARD.matcher(value).replaceAll("$1********$2");
            value = PHONE.matcher(value).replaceAll("$1****$2");
            return new JsonPrimitive(value);
        }
        return input.deepCopy();
    }

    private static boolean isSecretKey(String key) {
        String normalized = key == null ? "" : key.toLowerCase(Locale.ROOT);
        if (SECRET_KEYS.contains(normalized)) return true;
        return normalized.endsWith("_token") || normalized.endsWith("_password") || normalized.endsWith("_secret");
    }
}
