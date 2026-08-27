package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Command;
import com.google.gson.Gson;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.gson.JsonPrimitive;

import java.io.IOException;
import java.util.Collections;
import java.util.UUID;

import okhttp3.Call;
import okhttp3.MediaType;
import okhttp3.Request;
import okhttp3.RequestBody;
import okhttp3.Response;
import okhttp3.ResponseBody;
import okio.BufferedSource;

public final class OkHttpStreamingGateway implements StreamingGateway {
    private static final MediaType JSON = MediaType.get("application/json; charset=utf-8");
    private final NativeApiClient api;
    private final Gson gson = new Gson();

    public OkHttpStreamingGateway(NativeApiClient api) {
        this.api = api;
    }

    @Override
    public void streamChat(JsonObject payload, StreamCallback callback) {
        Request.Builder request = new Request.Builder()
            .url(api.buildUrl(new String[]{"chat", "stream"}, Collections.emptyMap()))
            .header("Accept", "text/event-stream")
            .header("Cache-Control", "no-cache")
            .header("Idempotency-Key", UUID.randomUUID().toString())
            .post(RequestBody.create(gson.toJson(payload), JSON));
        SecureSessionStore.Snapshot session = api.getSessionStore().load();
        if (session.isAuthenticated()) {
            request.header("Authorization", session.getSecrets().getTokenType() + " " + session.getSecrets().getAccessToken());
        }
        api.getHttpClient().newCall(request.build()).enqueue(new okhttp3.Callback() {
            @Override
            public void onFailure(Call call, IOException error) {
                callback.onError(new ApiFailure(0, call.isCanceled() ? "cancelled" : "network_error",
                    call.isCanceled() ? "请求已取消" : "无法连接流式政务服务"));
            }

            @Override
            public void onResponse(Call call, Response response) {
                try (ResponseBody body = response.body()) {
                    if (body == null) {
                        callback.onError(new ApiFailure(502, "empty_stream", "流式服务未返回内容"));
                        return;
                    }
                    if (!response.isSuccessful()) {
                        callback.onError(NativeApiClient.parseFailure(response.code(), body.string()));
                        return;
                    }
                    String contentType = response.header("Content-Type", "");
                    if (!contentType.toLowerCase(java.util.Locale.ROOT).contains("text/event-stream")) {
                        emitJsonFallback(body.string(), callback);
                        return;
                    }
                    if (!parseSse(body.source(), callback)) {
                        callback.onError(new ApiFailure(
                            502, "incomplete_stream", "流式回答在完成前中断"
                        ));
                    }
                } catch (IOException error) {
                    callback.onError(new ApiFailure(0, "stream_read_error", "读取流式回答失败"));
                }
            }
        });
    }

    @Override
    public void executeConsultation(Command command, JsonObject payload, GatewayCallback<JsonElement> callback) {
        switch (command) {
            case CONSULTATION_HISTORY:
                api.execute(NativeApiClient.Action.GET, new String[]{"consultations"},
                    GatewayPayload.query(payload, "cursor", "limit"), null, true, false, callback); return;
            case CONSULTATION_MESSAGES:
                api.execute(NativeApiClient.Action.GET,
                    new String[]{"consultations", GatewayPayload.string(payload, "session_id"), "messages"},
                    GatewayPayload.query(payload, "before", "limit"), null, true, false, callback); return;
            case CONSULTATION_MATERIAL_CONFIRM:
                api.execute(NativeApiClient.Action.POST,
                    new String[]{"consultations", GatewayPayload.string(payload, "session_id"),
                        "material-intents", GatewayPayload.string(payload, "intent_id"), "confirm"},
                    Collections.emptyMap(), null, true, true, callback); return;
            case CONSULTATION_FEEDBACK:
                api.execute(NativeApiClient.Action.POST, new String[]{"consultations", "feedback"},
                    Collections.emptyMap(), payload, true, true, callback); return;
            case HANDOFF_CREATE:
                api.execute(NativeApiClient.Action.POST, new String[]{"consultations", "handoffs"},
                    Collections.emptyMap(), payload, true, true, callback); return;
            case HANDOFF_MESSAGES:
                api.execute(NativeApiClient.Action.GET,
                    new String[]{"consultations", "handoffs", GatewayPayload.string(payload, "ticket_id"), "messages"},
                    GatewayPayload.query(payload, "page"), null, true, false, callback); return;
            case HANDOFF_MESSAGE_ADD:
                api.execute(NativeApiClient.Action.POST,
                    new String[]{"consultations", "handoffs", GatewayPayload.string(payload, "ticket_id"), "messages"},
                    Collections.emptyMap(), payload, true, true, callback); return;
            case HANDOFF_CANCEL:
                api.execute(NativeApiClient.Action.POST,
                    new String[]{"consultations", "handoffs", GatewayPayload.string(payload, "ticket_id"), "cancel"},
                    Collections.emptyMap(), null, true, true, callback); return;
            default:
                callback.onError(new ApiFailure(400, "unsupported_command", "不支持的咨询命令"));
        }
    }

    static boolean parseSse(BufferedSource source, StreamCallback callback) throws IOException {
        String event = "message";
        StringBuilder data = new StringBuilder();
        String line;
        while ((line = source.readUtf8Line()) != null) {
            if (line.isEmpty()) {
                if (emit(event, data.toString(), callback)) return true;
                event = "message";
                data.setLength(0);
                continue;
            }
            if (line.startsWith(":")) continue;
            if (line.startsWith("event:")) {
                event = line.substring(6).trim();
            } else if (line.startsWith("data:")) {
                if (data.length() > 0) data.append('\n');
                data.append(line.substring(5).trim());
            }
        }
        return data.length() > 0 && emit(event, data.toString(), callback);
    }

    private static boolean emit(String event, String rawData, StreamCallback callback) {
        if (rawData == null || rawData.isEmpty()) return false;
        if ("[DONE]".equals(rawData)) {
            callback.onEvent("done", new JsonObject());
            return true;
        }
        JsonElement data;
        try { data = JsonParser.parseString(rawData); }
        catch (RuntimeException ignored) { data = new JsonPrimitive(rawData); }
        String safeEvent = event == null || event.isEmpty() ? "message" : event;
        callback.onEvent(safeEvent, data);
        return "done".equals(safeEvent) || "error".equals(safeEvent);
    }

    private static void emitJsonFallback(String raw, StreamCallback callback) {
        try {
            JsonElement value = JsonParser.parseString(raw);
            callback.onEvent("done", value);
        } catch (RuntimeException invalid) {
            callback.onError(new ApiFailure(502, "invalid_response", "后端返回了无效流式响应"));
        }
    }
}
