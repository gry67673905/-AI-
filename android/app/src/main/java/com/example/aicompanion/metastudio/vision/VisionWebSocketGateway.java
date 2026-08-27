package com.example.aicompanion.metastudio.vision;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.VisionSession;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.ArrayDeque;
import java.util.Iterator;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okio.ByteString;

/** Native WSS transport with one-frame ACK backpressure and no WebView-visible credentials. */
public final class VisionWebSocketGateway {
    public static final String VISION_PATH = "/api/v1/integrations/metastudio/vision/ws";
    private static final int NORMAL_CLOSE = 1000;
    private static final int MAX_QUEUED_MESSAGES = 16;
    private static final int MAX_PROTECTED_MESSAGES = 32;
    private static final long DEFAULT_ACK_TIMEOUT_MS = 5_000;
    private static final long DOCUMENT_READY_TIMEOUT_MS = 30_000;
    private static final Pattern OPAQUE_ID = Pattern.compile("[A-Za-z0-9._:-]{1,256}");

    private final OkHttpClient client;
    private final String websocketUrl;
    private final boolean ownsClient;
    private final Listener listener;
    private final long ackTimeoutMs;
    private final long documentReadyTimeoutMs;
    private final ScheduledExecutorService timeoutExecutor;
    private final ArrayDeque<Outbound> queue = new ArrayDeque<>();

    private String visionSessionId = "";
    private String pendingVisionToken = "";
    private String clientSessionId = "";
    private WebSocket webSocket;
    private Ack awaitingAck;
    private ScheduledFuture<?> ackTimeout;
    private ScheduledFuture<?> documentStartTimeout;
    private ScheduledFuture<?> documentReadyTimeout;
    private long nextFrameSeq;
    private long activeTurnSeq;
    private int activeTurnFrameCount;
    private boolean finalFrameOffered;
    private long activeDocumentSeq;
    private boolean documentStarted;
    private boolean documentFrameOffered;
    private boolean documentFrameAcknowledged;
    private boolean open;
    private boolean protocolStarted;
    private boolean destroyed;

    public VisionWebSocketGateway(String apiBase, Listener listener) {
        this(
            new OkHttpClient.Builder()
                .connectTimeout(5, TimeUnit.SECONDS)
                .readTimeout(0, TimeUnit.MILLISECONDS)
                .writeTimeout(10, TimeUnit.SECONDS)
                .pingInterval(20, TimeUnit.SECONDS)
                .retryOnConnectionFailure(false)
                .build(),
            deriveWebSocketUrl(apiBase),
            true,
            false,
            listener,
            DEFAULT_ACK_TIMEOUT_MS
        );
    }

    VisionWebSocketGateway(
        OkHttpClient client,
        String websocketUrl,
        boolean ownsClient,
        boolean allowCleartextForTest,
        Listener listener
    ) {
        this(
            client, websocketUrl, ownsClient, allowCleartextForTest,
            listener, DEFAULT_ACK_TIMEOUT_MS, DOCUMENT_READY_TIMEOUT_MS
        );
    }

    VisionWebSocketGateway(
        OkHttpClient client,
        String websocketUrl,
        boolean ownsClient,
        boolean allowCleartextForTest,
        Listener listener,
        long ackTimeoutMs
    ) {
        this(
            client, websocketUrl, ownsClient, allowCleartextForTest,
            listener, ackTimeoutMs, DOCUMENT_READY_TIMEOUT_MS
        );
    }

    VisionWebSocketGateway(
        OkHttpClient client,
        String websocketUrl,
        boolean ownsClient,
        boolean allowCleartextForTest,
        Listener listener,
        long ackTimeoutMs,
        long documentReadyTimeoutMs
    ) {
        if (client == null || websocketUrl == null || listener == null
            || ackTimeoutMs < 50 || ackTimeoutMs > 30_000
            || documentReadyTimeoutMs < 50 || documentReadyTimeoutMs > 60_000) {
            throw new IllegalArgumentException("Visual WebSocket dependencies are required");
        }
        URI endpoint = parse(websocketUrl);
        String allowedScheme = allowCleartextForTest ? "ws" : "wss";
        if (endpoint == null || !allowedScheme.equalsIgnoreCase(endpoint.getScheme())
            || endpoint.getHost() == null || !VISION_PATH.equals(endpoint.getPath())
            || endpoint.getUserInfo() != null || endpoint.getRawQuery() != null
            || endpoint.getRawFragment() != null) {
            throw new IllegalArgumentException("Visual WebSocket must use the fixed secure path");
        }
        this.client = client;
        this.websocketUrl = websocketUrl;
        this.ownsClient = ownsClient;
        this.listener = listener;
        this.ackTimeoutMs = ackTimeoutMs;
        this.documentReadyTimeoutMs = documentReadyTimeoutMs;
        this.timeoutExecutor = Executors.newSingleThreadScheduledExecutor(task -> {
            Thread thread = new Thread(task, "digital-human-vision-ack-timeout");
            thread.setDaemon(true);
            return thread;
        });
    }

    public synchronized void configure(VisionSession value, String clientSessionId) {
        if (destroyed || value == null || !OPAQUE_ID.matcher(value.getVisionSessionId()).matches()
            || clientSessionId == null || !OPAQUE_ID.matcher(clientSessionId).matches()
            || !websocketUrl.equals(value.getWebsocketUrl())
            || value.getVisionToken().length() < 16 || containsControl(value.getVisionToken())) {
            throw new IllegalArgumentException("Invalid visual session");
        }
        disconnectLocked();
        clearCredentialLocked();
        this.visionSessionId = value.getVisionSessionId();
        this.pendingVisionToken = value.getVisionToken();
        this.clientSessionId = clientSessionId;
        nextFrameSeq = 0;
    }

    public synchronized boolean connect() {
        if (destroyed || pendingVisionToken.isEmpty() || webSocket != null) return false;
        Request request = new Request.Builder()
            .url(websocketUrl)
            .header("Authorization", "Bearer " + pendingVisionToken)
            .build();
        // The ticket is single-consumption. A retry requires a newly issued vision session.
        pendingVisionToken = "";
        webSocket = client.newWebSocket(request, new SocketListener());
        return true;
    }

    public synchronized long startTurn(long turnSeq) {
        if (!validSequence(turnSeq) || destroyed || visionSessionId.isEmpty()) return -1;
        if (activeDocumentSeq > 0) return -1;
        if (activeTurnSeq > 0) return activeTurnSeq == turnSeq ? turnSeq : -1;
        activeTurnSeq = turnSeq;
        activeTurnFrameCount = 0;
        finalFrameOffered = false;
        JsonObject message = control("turn.start");
        message.addProperty("turn_seq", turnSeq);
        enqueueLocked(Outbound.text(message.toString()));
        return turnSeq;
    }

    public synchronized long offerFrame(
        long turnSeq,
        long capturedAtMs,
        int width,
        int height,
        String camera,
        byte[] jpeg
    ) {
        return offerFrameLocked(
            turnSeq, capturedAtMs, width, height, camera, jpeg, false
        );
    }

    /** Offer the one frame allowed to consume the turn's reserved final slot. */
    public synchronized long offerFinalFrame(
        long turnSeq,
        long capturedAtMs,
        int width,
        int height,
        String camera,
        byte[] jpeg
    ) {
        return offerFrameLocked(
            turnSeq, capturedAtMs, width, height, camera, jpeg, true
        );
    }

    private long offerFrameLocked(
        long turnSeq,
        long capturedAtMs,
        int width,
        int height,
        String camera,
        byte[] jpeg,
        boolean finalFrame
    ) {
        if (destroyed || visionSessionId.isEmpty() || !validSequence(turnSeq)
            || activeTurnSeq != turnSeq
            || finalFrameOffered || jpeg == null
            || jpeg.length > YuvJpegEncoder.TARGET_JPEG_BYTES
            || (finalFrame
                ? activeTurnFrameCount >= VisionFrameSelector.MAX_FRAMES_PER_TURN
                : activeTurnFrameCount
                    >= VisionFrameSelector.MAX_NON_FINAL_FRAMES_PER_TURN)) return -1;
        long frameSeq = nextFrameSeq == Long.MAX_VALUE ? 1 : nextFrameSeq + 1;
        byte[] envelope;
        try {
            envelope = VisionFrameEnvelope.encode(new VisionFrameEnvelope.Frame(
                turnSeq, frameSeq, capturedAtMs, width, height, camera, jpeg
            ));
        } catch (IllegalArgumentException invalidFrame) {
            return -1;
        }
        nextFrameSeq = frameSeq;
        activeTurnFrameCount++;
        if (finalFrame) finalFrameOffered = true;
        // Keep at most one not-yet-sent frame. The in-flight frame remains immutable until ACK.
        for (Iterator<Outbound> iterator = queue.iterator(); iterator.hasNext();) {
            Outbound candidate = iterator.next();
            if (candidate.frame != null && !candidate.document) iterator.remove();
        }
        enqueueLocked(Outbound.frame(turnSeq, frameSeq, envelope));
        return frameSeq;
    }

    public synchronized void endTurn(long turnSeq) {
        if (!validSequence(turnSeq) || destroyed || visionSessionId.isEmpty()
            || activeTurnSeq != turnSeq) return;
        JsonObject message = control("turn.end");
        message.addProperty("turn_seq", turnSeq);
        enqueueLocked(Outbound.text(message.toString()));
        activeTurnSeq = 0;
        activeTurnFrameCount = 0;
        finalFrameOffered = false;
    }

    /** Starts one explicit document-photo exchange. Ordinary visual turns remain paused. */
    public synchronized long startDocument(long documentSeq) {
        if (!validSequence(documentSeq) || destroyed || visionSessionId.isEmpty()
            || activeTurnSeq > 0 || activeDocumentSeq > 0) return -1;
        activeDocumentSeq = documentSeq;
        documentStarted = false;
        documentFrameOffered = false;
        documentFrameAcknowledged = false;
        JsonObject message = control("document.start");
        message.addProperty("document_seq", documentSeq);
        enqueueLocked(Outbound.documentStart(documentSeq, message.toString()));
        return documentSeq;
    }

    /** Sends exactly one re-encoded, metadata-free document JPEG after document.started. */
    public synchronized long offerDocumentFrame(
        long documentSeq,
        long capturedAtMs,
        int width,
        int height,
        String camera,
        byte[] jpeg
    ) {
        if (destroyed || visionSessionId.isEmpty() || activeDocumentSeq != documentSeq
            || !documentStarted || documentFrameOffered || jpeg == null
            || jpeg.length > DocumentFrameEnvelope.MAX_JPEG_BYTES) return -1;
        byte[] envelope;
        try {
            envelope = DocumentFrameEnvelope.encode(new DocumentFrameEnvelope.Frame(
                documentSeq, capturedAtMs, width, height, camera, jpeg
            ));
        } catch (IllegalArgumentException invalidFrame) {
            return -1;
        }
        documentFrameOffered = true;
        enqueueLocked(Outbound.documentFrame(documentSeq, envelope));
        return documentSeq;
    }

    public synchronized void disconnect() {
        disconnectLocked();
        clearCredentialLocked();
    }

    public synchronized void destroy() {
        if (destroyed) return;
        disconnectLocked();
        destroyed = true;
        clearCredentialLocked();
        if (ownsClient) {
            client.dispatcher().cancelAll();
            client.connectionPool().evictAll();
            client.dispatcher().executorService().shutdown();
        }
        timeoutExecutor.shutdownNow();
    }

    public static String deriveWebSocketUrl(String apiBase) {
        URI base = parse(apiBase);
        if (base == null || !"https".equalsIgnoreCase(base.getScheme()) || base.getHost() == null
            || base.getUserInfo() != null || base.getRawQuery() != null || base.getRawFragment() != null
            || (base.getPath() != null && !base.getPath().isEmpty() && !"/".equals(base.getPath()))) {
            throw new IllegalArgumentException("Government API base must be a secure origin");
        }
        try {
            return new URI("wss", null, base.getHost(), base.getPort(), VISION_PATH, null, null)
                .toASCIIString();
        } catch (URISyntaxException invalid) {
            throw new IllegalArgumentException("Cannot derive visual WebSocket endpoint", invalid);
        }
    }

    private void enqueueLocked(Outbound outbound) {
        if (queue.size() >= MAX_QUEUED_MESSAGES) {
            // Only replace an ordinary temporal frame. Protocol controls and the explicit
            // document photo are protected; a small bounded control reserve avoids corrupting
            // turn/document state while an earlier frame is waiting for its receipt ACK.
            Outbound removable = null;
            for (Outbound candidate : queue) {
                if (candidate.frame != null && !candidate.document) removable = candidate;
            }
            if (removable != null) {
                queue.remove(removable);
            } else if (outbound.frame != null && !outbound.document) {
                return;
            } else if (queue.size() >= MAX_PROTECTED_MESSAGES) {
                failLocked("视觉通道消息拥塞，请重新开启视觉辅助");
                return;
            }
        }
        queue.addLast(outbound);
        pumpLocked();
    }

    private void pumpLocked() {
        while (open && protocolStarted && webSocket != null
            && awaitingAck == null && !queue.isEmpty()) {
            Outbound outbound = queue.pollFirst();
            boolean accepted;
            if (outbound.text != null) {
                accepted = webSocket.send(outbound.text);
                if (accepted && outbound.document) {
                    scheduleDocumentStartTimeoutLocked(outbound.turnSeq);
                }
            } else {
                accepted = webSocket.send(ByteString.of(outbound.frame));
                if (accepted) {
                    awaitingAck = new Ack(
                        outbound.document, outbound.turnSeq, outbound.frameSeq
                    );
                    scheduleAckTimeoutLocked(awaitingAck);
                }
            }
            if (!accepted) {
                awaitingAck = null;
                failLocked("视觉通道发送失败");
                return;
            }
        }
    }

    private void handleControlLocked(String text) {
        if (text == null || text.length() > 4096) return;
        try {
            JsonElement parsed = JsonParser.parseString(text);
            if (!parsed.isJsonObject()) return;
            JsonObject object = parsed.getAsJsonObject();
            String type = string(object, "type");
            if ("vision.started".equals(type)) {
                if (!protocolStarted) {
                    protocolStarted = true;
                    listener.onConnected();
                    pumpLocked();
                }
                return;
            }
            if ("vision.error".equals(type)) {
                String code = safeDocumentErrorCode(string(object, "code"));
                if ("invalid_document_state".equals(code) && activeDocumentSeq > 0) {
                    long documentSeq = activeDocumentSeq;
                    clearFailedDocumentLocked(documentSeq);
                    listener.onDocumentFailed(
                        documentSeq,
                        "当前语音或回答尚未结束，请等待结束后重新拍摄"
                    );
                    pumpLocked();
                    return;
                }
                failLocked("视觉通道协议异常，语音对话仍可继续");
                return;
            }
            if ("turn.ended".equals(type)) {
                long turnSeq = number(object, "turn_seq");
                if (validSequence(turnSeq)) listener.onTurnEnded(turnSeq);
                return;
            }
            if ("document.started".equals(type)) {
                long documentSeq = number(object, "document_seq");
                if (documentSeq == activeDocumentSeq && !documentStarted) {
                    cancelDocumentStartTimeoutLocked();
                    documentStarted = true;
                    listener.onDocumentStarted(documentSeq);
                }
                return;
            }
            if ("document.ready".equals(type)) {
                long documentSeq = number(object, "document_seq");
                if (documentSeq == activeDocumentSeq && documentFrameOffered
                    && documentFrameAcknowledged) {
                    cancelDocumentReadyTimeoutLocked();
                    clearDocumentStateLocked();
                    listener.onDocumentReady(documentSeq);
                }
                return;
            }
            if ("document.error".equals(type)) {
                long documentSeq = number(object, "document_seq");
                if (documentSeq == activeDocumentSeq) {
                    String message = documentFailureMessage(safeDocumentErrorCode(
                        string(object, "code")
                    ));
                    clearFailedDocumentLocked(documentSeq);
                    listener.onDocumentFailed(documentSeq, message);
                    pumpLocked();
                }
                return;
            }
            if (awaitingAck == null) return;
            if ("document.ack".equals(type)) {
                long documentSeq = number(object, "document_seq");
                if (!awaitingAck.document || documentSeq != awaitingAck.turnSeq) return;
                cancelAckTimeoutLocked();
                awaitingAck = null;
                documentFrameAcknowledged = true;
                listener.onDocumentAcknowledged(documentSeq, string(object, "status"));
                scheduleDocumentReadyTimeoutLocked(documentSeq);
                pumpLocked();
                return;
            }
            if (!"vision.ack".equals(type) || awaitingAck.document) return;
            long turnSeq = number(object, "turn_seq");
            long frameSeq = number(object, "frame_seq");
            if (turnSeq != awaitingAck.turnSeq || frameSeq != awaitingAck.frameSeq) return;
            cancelAckTimeoutLocked();
            awaitingAck = null;
            listener.onFrameAcknowledged(turnSeq, frameSeq, string(object, "status"));
            pumpLocked();
        } catch (RuntimeException ignored) {
            // Provider data never reaches the UI or logs.
        }
    }

    private void disconnectLocked() {
        queue.clear();
        cancelAckTimeoutLocked();
        cancelDocumentStartTimeoutLocked();
        cancelDocumentReadyTimeoutLocked();
        awaitingAck = null;
        open = false;
        protocolStarted = false;
        WebSocket active = webSocket;
        webSocket = null;
        if (active != null) {
            if (!active.close(NORMAL_CLOSE, "vision_closed")) active.cancel();
        }
    }

    private void failLocked(String message) {
        queue.clear();
        cancelAckTimeoutLocked();
        cancelDocumentStartTimeoutLocked();
        cancelDocumentReadyTimeoutLocked();
        awaitingAck = null;
        open = false;
        protocolStarted = false;
        WebSocket active = webSocket;
        webSocket = null;
        if (active != null) active.cancel();
        clearCredentialLocked();
        listener.onError(message);
    }

    private void clearCredentialLocked() {
        visionSessionId = "";
        pendingVisionToken = "";
        clientSessionId = "";
        nextFrameSeq = 0;
        activeTurnSeq = 0;
        activeTurnFrameCount = 0;
        finalFrameOffered = false;
        clearDocumentStateLocked();
    }

    private void clearDocumentStateLocked() {
        cancelDocumentStartTimeoutLocked();
        cancelDocumentReadyTimeoutLocked();
        activeDocumentSeq = 0;
        documentStarted = false;
        documentFrameOffered = false;
        documentFrameAcknowledged = false;
    }

    /**
     * A schema-valid document.error is a recoverable result for one explicit photo. It must
     * not consume the already-established visual ticket or tear down ordinary keyframe turns.
     */
    private void clearFailedDocumentLocked(long documentSeq) {
        if (awaitingAck != null && awaitingAck.document
            && awaitingAck.turnSeq == documentSeq) {
            cancelAckTimeoutLocked();
            awaitingAck = null;
        }
        for (Iterator<Outbound> iterator = queue.iterator(); iterator.hasNext();) {
            Outbound candidate = iterator.next();
            if (candidate.document && candidate.turnSeq == documentSeq) iterator.remove();
        }
        clearDocumentStateLocked();
    }

    private static String safeDocumentErrorCode(String value) {
        if (value == null || value.length() < 1 || value.length() > 64) return "unknown";
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            if (!(character == '_' || character == '-' || Character.isLetterOrDigit(character))) {
                return "unknown";
            }
        }
        return value;
    }

    private void scheduleAckTimeoutLocked(Ack expected) {
        cancelAckTimeoutLocked();
        ackTimeout = timeoutExecutor.schedule(() -> {
            synchronized (VisionWebSocketGateway.this) {
                if (!destroyed && awaitingAck == expected) {
                    if (expected.document) {
                        failLocked("文件照片确认超时，请重新开启视觉辅助");
                    } else {
                        failLocked("视觉帧确认超时，语音对话仍可继续");
                    }
                }
            }
        }, ackTimeoutMs, TimeUnit.MILLISECONDS);
    }

    private void cancelAckTimeoutLocked() {
        ScheduledFuture<?> active = ackTimeout;
        ackTimeout = null;
        if (active != null) active.cancel(false);
    }

    private void scheduleDocumentStartTimeoutLocked(long documentSeq) {
        cancelDocumentStartTimeoutLocked();
        documentStartTimeout = timeoutExecutor.schedule(() -> {
            synchronized (VisionWebSocketGateway.this) {
                if (!destroyed && activeDocumentSeq == documentSeq && !documentStarted) {
                    failLocked("文件识别连接超时，请重新开启视觉辅助");
                }
            }
        }, ackTimeoutMs, TimeUnit.MILLISECONDS);
    }

    private void cancelDocumentStartTimeoutLocked() {
        ScheduledFuture<?> active = documentStartTimeout;
        documentStartTimeout = null;
        if (active != null) active.cancel(false);
    }

    private void scheduleDocumentReadyTimeoutLocked(long documentSeq) {
        cancelDocumentReadyTimeoutLocked();
        documentReadyTimeout = timeoutExecutor.schedule(() -> {
            synchronized (VisionWebSocketGateway.this) {
                if (!destroyed && activeDocumentSeq == documentSeq && documentFrameOffered) {
                    failLocked("文件识别等待超时，请重新开启视觉辅助");
                }
            }
        }, documentReadyTimeoutMs, TimeUnit.MILLISECONDS);
    }

    private void cancelDocumentReadyTimeoutLocked() {
        ScheduledFuture<?> active = documentReadyTimeout;
        documentReadyTimeout = null;
        if (active != null) active.cancel(false);
    }

    private static String documentFailureMessage(String code) {
        if ("document_unreadable".equals(code)) {
            return "没有看清文件内容，请将文件放平、居中并避免反光后重新拍摄";
        }
        if ("analysis_unavailable".equals(code)) {
            return "本次文件内容暂时无法识别，请稍后重新拍摄";
        }
        if ("blurred".equals(code) || "low_quality".equals(code)) {
            return "文件画面较模糊，请保持手机稳定后重新拍摄";
        }
        if ("glare".equals(code)) {
            return "文件反光较明显，请调整角度后重新拍摄";
        }
        if ("document_not_found".equals(code) || "incomplete_document".equals(code)) {
            return "没有看清完整文件，请将文件居中后重新拍摄";
        }
        if ("too_dark".equals(code)) {
            return "文件画面光线不足，请改善光线后重新拍摄";
        }
        if ("quota_exceeded".equals(code)) {
            return "文件识别额度暂时不可用，普通视觉仍可继续";
        }
        return "本次文件识别未完成，普通视觉仍可继续";
    }

    private JsonObject control(String type) {
        JsonObject message = new JsonObject();
        message.addProperty("v", 1);
        message.addProperty("type", type);
        return message;
    }

    private static boolean validSequence(long value) { return value > 0; }

    private static String string(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() ? value.getAsString() : "";
    }

    private static long number(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() ? value.getAsLong() : -1;
    }

    private static boolean containsControl(String value) {
        for (int index = 0; index < value.length(); index++) {
            if (Character.isISOControl(value.charAt(index))) return true;
        }
        return false;
    }

    private static URI parse(String raw) {
        if (raw == null || raw.length() > 4096) return null;
        try { return URI.create(raw); } catch (RuntimeException invalid) { return null; }
    }

    private final class SocketListener extends WebSocketListener {
        @Override public void onOpen(WebSocket socket, Response response) {
            synchronized (VisionWebSocketGateway.this) {
                if (destroyed || socket != webSocket || visionSessionId.isEmpty()) {
                    socket.close(NORMAL_CLOSE, "stale_session");
                    return;
                }
                open = true;
                JsonObject start = control("vision.start");
                start.addProperty("vision_session_id", visionSessionId);
                start.addProperty("client_session_id", clientSessionId);
                if (!socket.send(start.toString())) {
                    failLocked("视觉通道握手失败");
                    return;
                }
            }
        }

        @Override public void onMessage(WebSocket socket, String text) {
            synchronized (VisionWebSocketGateway.this) {
                if (socket == webSocket) handleControlLocked(text);
            }
        }

        @Override public void onClosing(WebSocket socket, int code, String reason) {
            socket.close(code, null);
        }

        @Override public void onClosed(WebSocket socket, int code, String reason) {
            synchronized (VisionWebSocketGateway.this) {
                if (socket != webSocket) return;
                webSocket = null;
                open = false;
                protocolStarted = false;
                cancelAckTimeoutLocked();
                awaitingAck = null;
                queue.clear();
                clearCredentialLocked();
                listener.onDisconnected();
            }
        }

        @Override public void onFailure(WebSocket socket, Throwable error, Response response) {
            synchronized (VisionWebSocketGateway.this) {
                if (socket != webSocket) return;
                failLocked("视觉通道连接失败");
            }
        }
    }

    private static final class Outbound {
        private final String text;
        private final byte[] frame;
        private final long turnSeq;
        private final long frameSeq;
        private final boolean document;

        private Outbound(
            String text, byte[] frame, long turnSeq, long frameSeq, boolean document
        ) {
            this.text = text;
            this.frame = frame;
            this.turnSeq = turnSeq;
            this.frameSeq = frameSeq;
            this.document = document;
        }

        static Outbound text(String value) { return new Outbound(value, null, 0, 0, false); }
        static Outbound documentStart(long documentSeq, String value) {
            return new Outbound(value, null, documentSeq, 0, true);
        }
        static Outbound frame(long turnSeq, long frameSeq, byte[] value) {
            return new Outbound(null, value, turnSeq, frameSeq, false);
        }
        static Outbound documentFrame(long documentSeq, byte[] value) {
            return new Outbound(null, value, documentSeq, 0, true);
        }
    }

    private static final class Ack {
        private final boolean document;
        private final long turnSeq;
        private final long frameSeq;

        private Ack(boolean document, long turnSeq, long frameSeq) {
            this.document = document;
            this.turnSeq = turnSeq;
            this.frameSeq = frameSeq;
        }
    }

    public interface Listener {
        void onConnected();
        void onDisconnected();
        void onError(String message);
        default void onFrameAcknowledged(long turnSeq, long frameSeq, String status) {}
        default void onTurnEnded(long turnSeq) {}
        default void onDocumentStarted(long documentSeq) {}
        default void onDocumentAcknowledged(long documentSeq, String status) {}
        default void onDocumentReady(long documentSeq) {}
        default void onDocumentFailed(long documentSeq, String message) {}
    }
}
