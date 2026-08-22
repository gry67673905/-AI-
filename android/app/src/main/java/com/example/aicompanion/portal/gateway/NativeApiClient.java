package com.example.aicompanion.portal.gateway;

import android.content.ContentResolver;
import android.net.Uri;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.SelectedDocument;
import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonNull;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.JsonPrimitive;

import java.io.IOException;
import java.io.InputStream;
import java.util.Collections;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import okhttp3.Call;
import okhttp3.HttpUrl;
import okhttp3.MediaType;
import okhttp3.MultipartBody;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;
import okio.BufferedSink;

/** Fixed-origin native HTTP transport. No URL or HTTP method crosses the JS bridge. */
public final class NativeApiClient {
    public enum Action { GET, POST, PATCH, DELETE }

    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private static final Pattern SECRET = Pattern.compile(
        "(?i)(bearer\\s+|(?:access[_-]?token|refresh[_-]?token|api[_-]?key|password)\\s*[:=]\\s*[\\\"']?)[^\\s,;\\\"'}]+"
    );
    private static final int MAX_ERROR_LENGTH = 512;

    private final OkHttpClient client;
    private final HttpUrl apiRoot;
    private final SecureSessionStore sessionStore;
    private final Gson gson;

    public NativeApiClient(OkHttpClient client, String baseUrl, SecureSessionStore sessionStore) {
        this(client, baseUrl, sessionStore, new Gson());
    }

    NativeApiClient(OkHttpClient client, String baseUrl, SecureSessionStore sessionStore, Gson gson) {
        this.client = client;
        this.sessionStore = sessionStore;
        this.gson = gson;
        HttpUrl parsed = HttpUrl.parse(trimSlash(baseUrl) + "/api/v1/");
        if (parsed == null || !("http".equals(parsed.scheme()) || "https".equals(parsed.scheme()))) {
            throw new IllegalArgumentException("Invalid government API base URL");
        }
        this.apiRoot = parsed;
    }

    public static OkHttpClient defaultClient() {
        return new OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(45, TimeUnit.SECONDS)
            .writeTimeout(20, TimeUnit.SECONDS)
            .callTimeout(55, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build();
    }

    public void execute(
        Action action,
        String[] pathSegments,
        Map<String, String> query,
        JsonObject body,
        boolean authenticated,
        boolean idempotentWrite,
        GatewayCallback<JsonElement> callback
    ) {
        HttpUrl url = buildUrl(pathSegments, query);
        Request.Builder request = new Request.Builder().url(url).header("Accept", "application/json");
        if (!authorize(request, authenticated, callback)) return;
        if (idempotentWrite) request.header("Idempotency-Key", UUID.randomUUID().toString());
        // A zero-length body without a JSON content type accurately represents OpenAPI POST operations
        // that declare no requestBody (for example cancel/retry/archive).
        RequestBody requestBody = body == null
            ? RequestBody.create(new byte[0], (MediaType) null)
            : RequestBody.create(gson.toJson(body), JSON);
        switch (action) {
            case GET: request.get(); break;
            case POST: request.post(requestBody); break;
            case PATCH: request.patch(requestBody); break;
            case DELETE:
                if (body == null || body.size() == 0) request.delete(); else request.delete(requestBody);
                break;
            default: throw new IllegalStateException("Unsupported action");
        }
        enqueue(request.build(), callback);
    }

    public void upload(
        String[] pathSegments,
        SelectedDocument document,
        ContentResolver resolver,
        Map<String, String> formFields,
        GatewayCallback<JsonElement> callback
    ) {
        SecureSessionStore.Snapshot snapshot = sessionStore.load();
        if (!snapshot.isAuthenticated()) {
            callback.onError(new ApiFailure(401, "authentication_required", "请先登录"));
            return;
        }
        Uri uri = Uri.parse(document.getUri());
        MediaType mediaType = MediaType.parse(document.getMimeType());
        if (mediaType == null) mediaType = MediaType.get("application/octet-stream");
        RequestBody streamBody = new ContentResolverRequestBody(resolver, uri, mediaType, document.getSize());
        MultipartBody.Builder multipart = new MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", document.getDisplayName(), streamBody);
        if (formFields != null) {
            for (Map.Entry<String, String> field : formFields.entrySet()) {
                if (field.getKey() != null && field.getValue() != null) {
                    multipart.addFormDataPart(field.getKey(), field.getValue());
                }
            }
        }
        MultipartBody body = multipart.build();
        Request request = new Request.Builder()
            .url(buildUrl(pathSegments, Collections.emptyMap()))
            .header("Accept", "application/json")
            .header("Authorization", snapshot.getSecrets().getTokenType() + " " + snapshot.getSecrets().getAccessToken())
            .header("Idempotency-Key", UUID.randomUUID().toString())
            .post(body)
            .build();
        enqueue(request, callback);
    }

    public HttpUrl buildUrl(String[] pathSegments, Map<String, String> query) {
        HttpUrl.Builder builder = apiRoot.newBuilder();
        if (pathSegments != null) {
            for (String segment : pathSegments) {
                if (segment == null || segment.isEmpty() || segment.contains("/") || segment.contains("\\")) {
                    throw new IllegalArgumentException("Invalid API path segment");
                }
                builder.addPathSegment(segment);
            }
        }
        if (query != null) {
            for (Map.Entry<String, String> entry : query.entrySet()) {
                if (entry.getKey() != null && entry.getValue() != null) {
                    builder.addQueryParameter(entry.getKey(), entry.getValue());
                }
            }
        }
        return builder.build();
    }

    public SecureSessionStore getSessionStore() { return sessionStore; }
    public OkHttpClient getHttpClient() { return client; }
    public void cancelAll() { client.dispatcher().cancelAll(); }

    private boolean authorize(Request.Builder request, boolean authenticated, GatewayCallback<?> callback) {
        if (!authenticated) return true;
        SecureSessionStore.Snapshot snapshot = sessionStore.load();
        if (!snapshot.isAuthenticated()) {
            callback.onError(new ApiFailure(401, "authentication_required", "请先登录"));
            return false;
        }
        request.header("Authorization", snapshot.getSecrets().getTokenType() + " " + snapshot.getSecrets().getAccessToken());
        return true;
    }

    private void enqueue(Request request, GatewayCallback<JsonElement> callback) {
        client.newCall(request).enqueue(new okhttp3.Callback() {
            @Override
            public void onFailure(Call call, IOException error) {
                callback.onError(new ApiFailure(0, call.isCanceled() ? "cancelled" : "network_error",
                    call.isCanceled() ? "请求已取消" : "无法连接本地政务服务"));
            }

            @Override
            public void onResponse(Call call, Response response) {
                try (ResponseBody body = response.body()) {
                    String raw = body == null ? "" : body.string();
                    if (!response.isSuccessful()) {
                        if (response.code() == 401) sessionStore.clear();
                        callback.onError(parseFailure(response.code(), raw));
                        return;
                    }
                    if (raw.trim().isEmpty()) {
                        callback.onSuccess(new JsonObject());
                        return;
                    }
                    try {
                        callback.onSuccess(JsonParser.parseString(raw));
                    } catch (RuntimeException invalid) {
                        callback.onError(new ApiFailure(502, "invalid_response", "后端返回了无效 JSON"));
                    }
                } catch (IOException error) {
                    callback.onError(new ApiFailure(0, "network_error", "读取政务服务响应失败"));
                }
            }
        });
    }

    static ApiFailure parseFailure(int statusCode, String raw) {
        String code = "http_error";
        String message = "政务服务暂时不可用";
        JsonElement details = JsonNull.INSTANCE;
        try {
            JsonElement root = JsonParser.parseString(raw);
            if (root.isJsonObject()) {
                JsonObject object = root.getAsJsonObject();
                JsonElement detail = object.get("detail");
                if (detail == null || detail.isJsonNull()) detail = object.get("details");
                if (detail != null && !detail.isJsonNull()) {
                    if (statusCode == 422) {
                        code = "validation_error";
                        message = validationMessage(detail);
                    } else if (detail.isJsonPrimitive()) {
                        message = detail.getAsString();
                    } else {
                        details = sanitizeErrorDetails(detail, 0);
                    }
                }
                JsonElement error = object.get("error");
                if (error != null && error.isJsonObject()) {
                    JsonObject nested = error.getAsJsonObject();
                    if (nested.has("code") && nested.get("code").isJsonPrimitive()) code = nested.get("code").getAsString();
                    if (nested.has("message") && nested.get("message").isJsonPrimitive()) message = nested.get("message").getAsString();
                    JsonElement nestedDetails = nested.get("detail");
                    if (nestedDetails == null || nestedDetails.isJsonNull()) nestedDetails = nested.get("details");
                    if (nestedDetails != null && !nestedDetails.isJsonNull()) {
                        details = sanitizeErrorDetails(nestedDetails, 0);
                    }
                } else {
                    if (object.has("code") && object.get("code").isJsonPrimitive()) code = object.get("code").getAsString();
                    if (object.has("message") && object.get("message").isJsonPrimitive()) message = object.get("message").getAsString();
                }
            }
        } catch (RuntimeException ignored) {}
        return new ApiFailure(statusCode, sanitizeText(code), sanitizeText(message), details);
    }

    private static JsonElement sanitizeErrorDetails(JsonElement value, int depth) {
        if (value == null || value.isJsonNull() || depth > 5) return JsonNull.INSTANCE;
        if (value.isJsonObject()) {
            JsonObject output = new JsonObject();
            for (Map.Entry<String, JsonElement> entry : value.getAsJsonObject().entrySet()) {
                if (isSensitiveKey(entry.getKey())) continue;
                output.add(entry.getKey(), sanitizeErrorDetails(entry.getValue(), depth + 1));
            }
            return output;
        }
        if (value.isJsonArray()) {
            JsonArray output = new JsonArray();
            int count = 0;
            for (JsonElement item : value.getAsJsonArray()) {
                if (count++ >= 32) break;
                output.add(sanitizeErrorDetails(item, depth + 1));
            }
            return output;
        }
        JsonPrimitive primitive = value.getAsJsonPrimitive();
        if (primitive.isString()) return new JsonPrimitive(sanitizeText(primitive.getAsString()));
        if (primitive.isBoolean()) return new JsonPrimitive(primitive.getAsBoolean());
        if (primitive.isNumber()) return new JsonPrimitive(primitive.getAsNumber());
        return JsonNull.INSTANCE;
    }

    private static boolean isSensitiveKey(String key) {
        if (key == null) return false;
        String normalized = key.trim().toLowerCase(java.util.Locale.ROOT).replace('-', '_');
        return normalized.equals("authorization")
            || normalized.equals("password")
            || normalized.equals("verification_code")
            || normalized.equals("api_key")
            || normalized.equals("secret")
            || normalized.equals("token")
            || normalized.equals("credential")
            || normalized.endsWith("_token")
            || normalized.endsWith("_password")
            || normalized.endsWith("_secret")
            || normalized.endsWith("_credential");
    }

    private static String sanitizeText(String value) {
        String source = value == null ? "" : value;
        String sanitized = SECRET.matcher(source.replaceAll("[\\r\\n\\t]+", " ")).replaceAll("[REDACTED]").trim();
        return sanitized.length() <= MAX_ERROR_LENGTH
            ? sanitized
            : sanitized.substring(0, MAX_ERROR_LENGTH) + "…";
    }

    private static String validationMessage(JsonElement detail) {
        if (!detail.isJsonArray()) return "请求字段校验失败";
        StringBuilder output = new StringBuilder();
        for (JsonElement item : detail.getAsJsonArray()) {
            if (!item.isJsonObject()) continue;
            JsonObject object = item.getAsJsonObject();
            String field = "字段";
            JsonElement location = object.get("loc");
            if (location != null && location.isJsonArray() && location.getAsJsonArray().size() > 0) {
                JsonElement last = location.getAsJsonArray().get(location.getAsJsonArray().size() - 1);
                if (last.isJsonPrimitive()) field = last.getAsString();
            }
            String text = object.has("msg") && object.get("msg").isJsonPrimitive()
                ? object.get("msg").getAsString() : "校验失败";
            if (output.length() > 0) output.append("；");
            output.append(field).append("：").append(text);
            if (output.length() > 420) break;
        }
        return output.length() == 0 ? "请求字段校验失败" : output.toString();
    }

    private static String trimSlash(String value) {
        String result = value == null ? "" : value.trim();
        while (result.endsWith("/")) result = result.substring(0, result.length() - 1);
        return result;
    }

    private static final class ContentResolverRequestBody extends RequestBody {
        private final ContentResolver resolver;
        private final Uri uri;
        private final MediaType mediaType;
        private final long size;

        ContentResolverRequestBody(ContentResolver resolver, Uri uri, MediaType mediaType, long size) {
            this.resolver = resolver;
            this.uri = uri;
            this.mediaType = mediaType;
            this.size = size;
        }

        @Override public MediaType contentType() { return mediaType; }
        @Override public long contentLength() { return size >= 0 ? size : -1; }

        @Override
        public void writeTo(BufferedSink sink) throws IOException {
            try (InputStream input = resolver.openInputStream(uri)) {
                if (input == null) throw new IOException("Cannot open selected document");
                byte[] buffer = new byte[8192];
                int count;
                long total = 0;
                while ((count = input.read(buffer)) != -1) {
                    total += count;
                    if (total > 10L * 1024L * 1024L) throw new IOException("Selected document exceeds 10MB");
                    sink.write(buffer, 0, count);
                }
            }
        }
    }
}
