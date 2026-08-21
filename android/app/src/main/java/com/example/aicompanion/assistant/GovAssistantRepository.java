package com.example.aicompanion.assistant;

import com.example.aicompanion.BuildConfig;
import com.example.aicompanion.assistant.ChatContract.ChatError;
import com.example.aicompanion.assistant.ChatContract.ChatRequest;
import com.example.aicompanion.assistant.ChatContract.ChatResponse;
import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.JsonSyntaxException;

import java.io.IOException;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import okhttp3.Call;
import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;

/** Native-only API client. The WebView never receives the backend base URL. */
public final class GovAssistantRepository implements ChatDataSource {
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final int MAX_ERROR_LENGTH = 512;
    private static final Pattern BEARER_PATTERN = Pattern.compile(
        "(?i)(authorization\\s*[:=]\\s*bearer\\s+)[^\\s,;\\\"}]+"
    );
    private static final Pattern NAMED_SECRET_PATTERN = Pattern.compile(
        "(?i)((?:api[_-]?key|access[_-]?token|token|password)\\s*[:=]\\s*[\\\"']?)[^\\s,;\\\"'}]+"
    );
    private static final Pattern PROVIDER_KEY_PATTERN = Pattern.compile("(?i)sk-[a-z0-9_-]{8,}");

    private final OkHttpClient client;
    private final HttpUrl chatUrl;
    private final Gson gson;

    public GovAssistantRepository() {
        this(
            new OkHttpClient.Builder()
                .connectTimeout(5, TimeUnit.SECONDS)
                .readTimeout(45, TimeUnit.SECONDS)
                .writeTimeout(10, TimeUnit.SECONDS)
                .callTimeout(50, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false)
                .build(),
            BuildConfig.GOV_API_BASE,
            new Gson()
        );
    }

    public GovAssistantRepository(OkHttpClient client, String baseUrl) {
        this(client, baseUrl, new Gson());
    }

    GovAssistantRepository(OkHttpClient client, String baseUrl, Gson gson) {
        this.client = client;
        this.gson = gson;
        HttpUrl parsed = HttpUrl.parse(removeTrailingSlash(baseUrl) + "/api/v1/chat");
        if (parsed == null || !("http".equals(parsed.scheme()) || "https".equals(parsed.scheme()))) {
            throw new IllegalArgumentException("Invalid government API base URL");
        }
        this.chatUrl = parsed;
    }

    @Override
    public void sendChat(String sessionId, String message, ChatDataSource.Callback callback) {
        Request request = new Request.Builder()
            .url(chatUrl)
            .post(RequestBody.create(gson.toJson(new ChatRequest(sessionId, message)), JSON))
            .header("Accept", "application/json")
            .build();

        client.newCall(request).enqueue(new okhttp3.Callback() {
            @Override
            public void onFailure(Call call, IOException error) {
                if (call.isCanceled()) {
                    callback.onError(new ChatError(0, "cancelled", "请求已取消"));
                    return;
                }
                callback.onError(new ChatError(0, "network_error", "无法连接本地政务服务，请检查后端是否已启动"));
            }

            @Override
            public void onResponse(Call call, Response response) {
                try (ResponseBody responseBody = response.body()) {
                    String body;
                    try {
                        body = responseBody == null ? "" : responseBody.string();
                    } catch (IOException readError) {
                        callback.onError(new ChatError(0, "network_error", "读取政务服务响应失败"));
                        return;
                    }
                    if (!response.isSuccessful()) {
                        callback.onError(new ChatError(
                            response.code(),
                            "http_error",
                            sanitize(extractApiMessage(body, "政务服务暂时不可用"))
                        ));
                        return;
                    }

                    try {
                        callback.onSuccess(parseResponse(body));
                    } catch (IllegalArgumentException | JsonSyntaxException invalidResponse) {
                        callback.onError(new ChatError(502, "invalid_response", "后端返回了无效的聊天响应"));
                    }
                }
            }
        });
    }

    @Override
    public void cancelAll() {
        client.dispatcher().cancelAll();
    }

    String buildRequestJson(String sessionId, String message) {
        return gson.toJson(new ChatRequest(sessionId, message));
    }

    ChatResponse parseResponse(String body) {
        ChatResponse parsed = gson.fromJson(body, ChatResponse.class);
        if (parsed == null
            || isBlank(parsed.getRequestId())
            || isBlank(parsed.getSessionId())
            || isBlank(parsed.getAnswer())) {
            throw new IllegalArgumentException("Missing required response fields");
        }
        parsed.normalizeCollections();
        return parsed;
    }

    static String sanitize(String raw) {
        if (raw == null) return "";
        String sanitized = BEARER_PATTERN.matcher(raw).replaceAll("$1[REDACTED]");
        sanitized = NAMED_SECRET_PATTERN.matcher(sanitized).replaceAll("$1[REDACTED]");
        sanitized = PROVIDER_KEY_PATTERN.matcher(sanitized).replaceAll("[REDACTED]");
        sanitized = sanitized.replaceAll("[\\r\\n\\t]+", " ").trim();
        return sanitized.length() <= MAX_ERROR_LENGTH
            ? sanitized
            : sanitized.substring(0, MAX_ERROR_LENGTH) + "…";
    }

    private static String extractApiMessage(String body, String fallback) {
        if (isBlank(body)) return fallback;
        try {
            JsonElement root = JsonParser.parseString(body);
            if (!root.isJsonObject()) return fallback;
            JsonObject object = root.getAsJsonObject();
            String detail = primitiveString(object.get("detail"));
            if (!isBlank(detail)) return detail;
            String message = primitiveString(object.get("message"));
            if (!isBlank(message)) return message;
            JsonElement errorValue = object.get("error");
            String error = primitiveString(errorValue);
            if (!isBlank(error)) return error;
            if (errorValue != null && errorValue.isJsonObject()) {
                String nestedMessage = primitiveString(errorValue.getAsJsonObject().get("message"));
                if (!isBlank(nestedMessage)) return nestedMessage;
            }
            return fallback;
        } catch (RuntimeException ignored) {
            return fallback;
        }
    }

    private static String primitiveString(JsonElement value) {
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()
            ? value.getAsString()
            : "";
    }

    private static boolean isBlank(String value) {
        return value == null || value.trim().isEmpty();
    }

    private static String removeTrailingSlash(String value) {
        if (value == null) return "";
        String trimmed = value.trim();
        while (trimmed.endsWith("/")) trimmed = trimmed.substring(0, trimmed.length() - 1);
        return trimmed;
    }
}
