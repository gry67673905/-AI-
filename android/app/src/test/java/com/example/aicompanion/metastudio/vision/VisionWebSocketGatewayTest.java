package com.example.aicompanion.metastudio.vision;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.metastudio.model.DigitalHumanContract.VisionSession;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import okhttp3.OkHttpClient;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import okhttp3.mockwebserver.MockResponse;
import okhttp3.mockwebserver.MockWebServer;
import okhttp3.mockwebserver.RecordedRequest;
import okio.ByteString;

public final class VisionWebSocketGatewayTest {
    private MockWebServer server;
    private OkHttpClient client;
    private VisionWebSocketGateway gateway;
    private final AtomicReference<WebSocket> serverSocket = new AtomicReference<>();
    private final BlockingQueue<String> textMessages = new LinkedBlockingQueue<>();
    private final BlockingQueue<ByteString> binaryMessages = new LinkedBlockingQueue<>();
    private final CountDownLatch serverOpen = new CountDownLatch(1);
    private final CountDownLatch clientOpen = new CountDownLatch(1);
    private final CountDownLatch clientError = new CountDownLatch(1);
    private final CountDownLatch documentStarted = new CountDownLatch(1);
    private final BlockingQueue<Long> documentStartEvents = new LinkedBlockingQueue<>();
    private final CountDownLatch documentAcknowledged = new CountDownLatch(1);
    private final CountDownLatch documentReady = new CountDownLatch(1);
    private final BlockingQueue<String> documentFailures = new LinkedBlockingQueue<>();
    private final AtomicReference<String> clientErrorMessage = new AtomicReference<>();
    private String wsUrl;

    @Before
    public void setUp() throws Exception {
        server = new MockWebServer();
        server.enqueue(new MockResponse().withWebSocketUpgrade(new WebSocketListener() {
            @Override public void onOpen(WebSocket webSocket, Response response) {
                serverSocket.set(webSocket);
                serverOpen.countDown();
            }

            @Override public void onMessage(WebSocket webSocket, String text) {
                textMessages.add(text);
            }

            @Override public void onMessage(WebSocket webSocket, ByteString bytes) {
                binaryMessages.add(bytes);
            }

            @Override public void onClosing(WebSocket webSocket, int code, String reason) {
                webSocket.close(code, null);
            }
        }));
        server.start();
        client = new OkHttpClient();
        wsUrl = server.url(VisionWebSocketGateway.VISION_PATH).toString()
            .replaceFirst("^http", "ws");
        gateway = new VisionWebSocketGateway(
            client,
            wsUrl,
            false,
            true,
            new VisionWebSocketGateway.Listener() {
                @Override public void onConnected() { clientOpen.countDown(); }
                @Override public void onDisconnected() {}
                @Override public void onError(String message) {
                    clientErrorMessage.set(message);
                    clientError.countDown();
                }
                @Override public void onDocumentStarted(long documentSeq) {
                    documentStartEvents.add(documentSeq);
                    if (documentSeq == 11) documentStarted.countDown();
                }
                @Override public void onDocumentAcknowledged(long documentSeq, String status) {
                    if (documentSeq == 11) documentAcknowledged.countDown();
                }
                @Override public void onDocumentReady(long documentSeq) {
                    if (documentSeq == 11) documentReady.countDown();
                }
                @Override public void onDocumentFailed(long documentSeq, String message) {
                    documentFailures.add(documentSeq + ":" + message);
                }
            }
        );
        gateway.configure(
            new VisionSession(
                "vision-1", wsUrl, "vision-token-1234567890", "2099-01-01T00:00:00Z"
            ),
            "client-1"
        );
    }

    @After
    public void tearDown() throws Exception {
        if (gateway != null) gateway.destroy();
        if (client != null) {
            client.dispatcher().cancelAll();
            client.connectionPool().evictAll();
            client.dispatcher().executorService().shutdownNow();
        }
        if (server != null) server.shutdown();
    }

    @Test
    public void authenticatesStartsSessionAndHoldsEndUntilFinalFrameAck() throws Exception {
        assertTrue(gateway.connect());
        assertTrue(serverOpen.await(3, TimeUnit.SECONDS));
        RecordedRequest request = server.takeRequest(1, TimeUnit.SECONDS);
        assertNotNull(request);
        assertEquals(VisionWebSocketGateway.VISION_PATH, request.getPath());
        assertEquals("Bearer vision-token-1234567890", request.getHeader("Authorization"));

        JsonObject sessionStart = nextText();
        assertEquals("vision.start", sessionStart.get("type").getAsString());
        assertEquals("vision-1", sessionStart.get("vision_session_id").getAsString());
        assertEquals("client-1", sessionStart.get("client_session_id").getAsString());
        serverSocket.get().send("{\"v\":1,\"type\":\"vision.started\"}");
        assertTrue(clientOpen.await(3, TimeUnit.SECONDS));

        gateway.startTurn(3);
        JsonObject turnStart = nextText();
        assertEquals(3, turnStart.size());
        assertEquals("turn.start", turnStart.get("type").getAsString());
        assertEquals(3, turnStart.get("turn_seq").getAsLong());

        assertEquals(-1, gateway.offerFrame(
            3, 900, 480, 640, "front", jpeg(YuvJpegEncoder.TARGET_JPEG_BYTES + 1)
        ));
        long first = gateway.offerFrame(3, 1000, 480, 640, "front", jpeg(20));
        long latestNonFinal = first;
        for (int index = 1; index < VisionFrameSelector.MAX_NON_FINAL_FRAMES_PER_TURN; index++) {
            latestNonFinal = gateway.offerFrame(
                3, 1000 + index * 500L, 480, 640, "front", jpeg(20 + index)
            );
            assertTrue(latestNonFinal > first);
        }
        assertEquals(
            "The transport reserves the eighth slot even if a camera selector regresses",
            -1,
            gateway.offerFrame(3, 4_600, 480, 640, "front", jpeg(32))
        );
        long finalFrame = gateway.offerFinalFrame(
            3, 4_700, 480, 640, "front", jpeg(36)
        );
        assertTrue(finalFrame > latestNonFinal);
        assertEquals(-1, gateway.offerFinalFrame(
            3, 4_800, 480, 640, "front", jpeg(36)
        ));
        gateway.endTurn(3);
        gateway.endTurn(3);

        JsonObject firstHeader = nextFrameHeader();
        assertEquals(first, firstHeader.get("frame_seq").getAsLong());
        assertNull(binaryMessages.poll(200, TimeUnit.MILLISECONDS));
        assertNull(textMessages.poll(200, TimeUnit.MILLISECONDS));

        serverSocket.get().send(ack(3, first));
        JsonObject finalHeader = nextFrameHeader();
        // The explicit final frame replaces older unsent candidates while one frame awaits ACK.
        assertEquals(finalFrame, finalHeader.get("frame_seq").getAsLong());
        assertNull(textMessages.poll(200, TimeUnit.MILLISECONDS));

        // A rate-limited frame is still acknowledged and must release backpressure so turn.end
        // cannot deadlock behind a frame the server intentionally dropped.
        serverSocket.get().send(ack(3, finalFrame, "dropped"));
        JsonObject turnEnd = nextText();
        assertEquals(3, turnEnd.size());
        assertEquals("turn.end", turnEnd.get("type").getAsString());
        assertEquals(3, turnEnd.get("turn_seq").getAsLong());
        assertNull("Duplicate endTurn must not create a second model turn", textMessages.poll(
            200, TimeUnit.MILLISECONDS
        ));

        gateway.disconnect();
        assertFalse("Consumed ticket must not reconnect", gateway.connect());
        server.enqueue(new MockResponse().withWebSocketUpgrade(new WebSocketListener() {
            @Override public void onClosing(WebSocket webSocket, int code, String reason) {
                webSocket.close(code, null);
            }
        }));
        gateway.configure(
            new VisionSession(
                "vision-2", wsUrl, "second-token-123456789", "2099-01-01T00:00:00Z"
            ),
            "client-1"
        );
        assertTrue("A newly issued ticket can reconnect", gateway.connect());
    }

    @Test
    public void frameAckTimeoutFailsClosedInsteadOfBlockingTurnForever() throws Exception {
        gateway.destroy();
        gateway = new VisionWebSocketGateway(
            client,
            wsUrl,
            false,
            true,
            new VisionWebSocketGateway.Listener() {
                @Override public void onConnected() { clientOpen.countDown(); }
                @Override public void onDisconnected() {}
                @Override public void onError(String message) {
                    clientErrorMessage.set(message);
                    clientError.countDown();
                }
            },
            150
        );
        gateway.configure(
            new VisionSession(
                "vision-timeout", wsUrl, "vision-token-1234567890", "2099-01-01T00:00:00Z"
            ),
            "client-timeout"
        );

        assertTrue(gateway.connect());
        assertTrue(serverOpen.await(3, TimeUnit.SECONDS));
        assertNotNull(server.takeRequest(1, TimeUnit.SECONDS));
        assertEquals("vision.start", nextText().get("type").getAsString());
        serverSocket.get().send("{\"v\":1,\"type\":\"vision.started\"}");
        assertTrue(clientOpen.await(3, TimeUnit.SECONDS));
        gateway.startTurn(7);
        assertEquals("turn.start", nextText().get("type").getAsString());
        assertTrue(gateway.offerFrame(7, 1000, 480, 640, "back", jpeg(24)) > 0);
        assertNotNull(binaryMessages.poll(3, TimeUnit.SECONDS));

        assertTrue(clientError.await(3, TimeUnit.SECONDS));
        assertTrue(clientErrorMessage.get().contains("确认超时"));
        gateway.endTurn(7);
        assertNull(textMessages.poll(250, TimeUnit.MILLISECONDS));
    }

    @Test
    public void documentPhotoWaitsForStartedAckAndReadyWithoutLeakingOcrText() throws Exception {
        assertTrue(gateway.connect());
        assertTrue(serverOpen.await(3, TimeUnit.SECONDS));
        assertNotNull(server.takeRequest(1, TimeUnit.SECONDS));
        assertEquals("vision.start", nextText().get("type").getAsString());
        serverSocket.get().send("{\"v\":1,\"type\":\"vision.started\"}");
        assertTrue(clientOpen.await(3, TimeUnit.SECONDS));

        assertEquals(11, gateway.startDocument(11));
        assertEquals(-1, gateway.startTurn(12));
        JsonObject start = nextText();
        assertEquals(3, start.size());
        assertEquals("document.start", start.get("type").getAsString());
        assertEquals(11, start.get("document_seq").getAsLong());
        assertEquals(-1, gateway.offerDocumentFrame(
            11, 1000, 1536, 2048, "back", jpeg(1024)
        ));

        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.started\",\"document_seq\":11}"
        );
        assertTrue(documentStarted.await(3, TimeUnit.SECONDS));
        assertEquals(11, gateway.offerDocumentFrame(
            11, 1000, 1536, 2048, "back", jpeg(1024)
        ));
        JsonObject header = nextFrameHeader();
        assertEquals("document.frame", header.get("type").getAsString());
        assertEquals(11, header.get("document_seq").getAsLong());
        assertFalse(header.has("text"));
        assertFalse(header.has("ocr"));

        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.ack\",\"document_seq\":11,"
                + "\"status\":\"accepted\"}"
        );
        assertTrue(documentAcknowledged.await(3, TimeUnit.SECONDS));
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.ready\",\"document_seq\":10}"
        );
        assertFalse("Stale ready must be ignored", documentReady.await(150, TimeUnit.MILLISECONDS));
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.ready\",\"document_seq\":11}"
        );
        assertTrue(documentReady.await(3, TimeUnit.SECONDS));
        assertEquals(12, gateway.startTurn(12));
        assertEquals("turn.start", nextText().get("type").getAsString());
    }

    @Test
    public void fullOrdinaryQueueNeverEvictsControlsOrDocumentStart() throws Exception {
        // Sixteen protected turn controls fill the ordinary queue before the socket starts.
        for (long turn = 1; turn <= 8; turn++) {
            assertEquals(turn, gateway.startTurn(turn));
            gateway.endTurn(turn);
        }
        assertEquals(99, gateway.startDocument(99));

        assertTrue(gateway.connect());
        assertTrue(serverOpen.await(3, TimeUnit.SECONDS));
        assertNotNull(server.takeRequest(1, TimeUnit.SECONDS));
        assertEquals("vision.start", nextText().get("type").getAsString());
        serverSocket.get().send("{\"v\":1,\"type\":\"vision.started\"}");
        assertTrue(clientOpen.await(3, TimeUnit.SECONDS));

        for (long turn = 1; turn <= 8; turn++) {
            JsonObject start = nextText();
            JsonObject end = nextText();
            assertEquals("turn.start", start.get("type").getAsString());
            assertEquals(turn, start.get("turn_seq").getAsLong());
            assertEquals("turn.end", end.get("type").getAsString());
            assertEquals(turn, end.get("turn_seq").getAsLong());
        }
        JsonObject documentStart = nextText();
        assertEquals("document.start", documentStart.get("type").getAsString());
        assertEquals(99, documentStart.get("document_seq").getAsLong());
    }

    @Test
    public void documentStartTimeoutInvalidatesSocketAndSingleUseCredential() throws Exception {
        TimeoutSignals signals = replaceGatewayForDocumentTimeouts(120, 500);
        openReplacementGateway(signals);
        assertEquals(21, gateway.startDocument(21));
        assertEquals("document.start", nextText().get("type").getAsString());

        assertTrue(signals.error.await(3, TimeUnit.SECONDS));
        assertTrue(signals.message.get().contains("重新开启视觉"));
        assertDocumentCredentialInvalidated();
    }

    @Test
    public void documentReceiptTimeoutInvalidatesSocketAndSingleUseCredential() throws Exception {
        TimeoutSignals signals = replaceGatewayForDocumentTimeouts(120, 500);
        openReplacementGateway(signals);
        assertEquals(22, gateway.startDocument(22));
        assertEquals("document.start", nextText().get("type").getAsString());
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.started\",\"document_seq\":22}"
        );
        assertTrue(signals.started.await(3, TimeUnit.SECONDS));
        assertEquals(22, gateway.offerDocumentFrame(
            22, 1000, 1536, 2048, "back", jpeg(1024)
        ));
        assertNotNull(binaryMessages.poll(3, TimeUnit.SECONDS));

        assertTrue(signals.error.await(3, TimeUnit.SECONDS));
        assertTrue(signals.message.get().contains("重新开启视觉"));
        assertDocumentCredentialInvalidated();
    }

    @Test
    public void documentReadyTimeoutInvalidatesSocketAndSingleUseCredential() throws Exception {
        TimeoutSignals signals = replaceGatewayForDocumentTimeouts(500, 120);
        openReplacementGateway(signals);
        assertEquals(23, gateway.startDocument(23));
        assertEquals("document.start", nextText().get("type").getAsString());
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.started\",\"document_seq\":23}"
        );
        assertTrue(signals.started.await(3, TimeUnit.SECONDS));
        assertEquals(23, gateway.offerDocumentFrame(
            23, 1000, 1536, 2048, "back", jpeg(1024)
        ));
        assertNotNull(binaryMessages.poll(3, TimeUnit.SECONDS));
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.ack\",\"document_seq\":23,"
                + "\"status\":\"accepted\"}"
        );
        assertTrue(signals.acknowledged.await(3, TimeUnit.SECONDS));

        assertTrue(signals.error.await(3, TimeUnit.SECONDS));
        assertTrue(signals.message.get().contains("重新开启视觉"));
        assertDocumentCredentialInvalidated();
    }

    @Test
    public void serverDocumentErrorKeepsSocketAndTicketForOrdinaryAndNewDocumentUse()
        throws Exception {
        assertTrue(gateway.connect());
        assertTrue(serverOpen.await(3, TimeUnit.SECONDS));
        assertNotNull(server.takeRequest(1, TimeUnit.SECONDS));
        assertEquals("vision.start", nextText().get("type").getAsString());
        serverSocket.get().send("{\"v\":1,\"type\":\"vision.started\"}");
        assertTrue(clientOpen.await(3, TimeUnit.SECONDS));

        assertEquals(24, gateway.startDocument(24));
        assertEquals("document.start", nextText().get("type").getAsString());
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.error\",\"document_seq\":24,"
                + "\"code\":\"document_unreadable\"}"
        );
        assertEquals(
            "24:没有看清文件内容，请将文件放平、居中并避免反光后重新拍摄",
            documentFailures.poll(3, TimeUnit.SECONDS)
        );
        assertFalse("Recoverable document results must not close visual WSS",
            clientError.await(200, TimeUnit.MILLISECONDS));

        assertEquals(25, gateway.startTurn(25));
        assertEquals("turn.start", nextText().get("type").getAsString());
        gateway.endTurn(25);
        assertEquals("turn.end", nextText().get("type").getAsString());

        assertEquals(26, gateway.startDocument(26));
        assertEquals("document.start", nextText().get("type").getAsString());
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.error\",\"document_seq\":26,"
                + "\"code\":\"analysis_unavailable\"}"
        );
        assertEquals(
            "26:本次文件内容暂时无法识别，请稍后重新拍摄",
            documentFailures.poll(3, TimeUnit.SECONDS)
        );
        assertFalse("A second recoverable result must also keep WSS open",
            clientError.await(200, TimeUnit.MILLISECONDS));

        assertEquals(27, gateway.startTurn(27));
        assertEquals("turn.start", nextText().get("type").getAsString());
    }

    @Test
    public void invalidDocumentStateVisionErrorKeepsSocketForTurnAndNewDocument()
        throws Exception {
        assertTrue(gateway.connect());
        assertTrue(serverOpen.await(3, TimeUnit.SECONDS));
        assertNotNull(server.takeRequest(1, TimeUnit.SECONDS));
        assertEquals("vision.start", nextText().get("type").getAsString());
        serverSocket.get().send("{\"v\":1,\"type\":\"vision.started\"}");
        assertTrue(clientOpen.await(3, TimeUnit.SECONDS));

        assertEquals(31, gateway.startDocument(31));
        assertEquals("document.start", nextText().get("type").getAsString());
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"vision.error\","
                + "\"code\":\"invalid_document_state\"}"
        );
        assertEquals(
            "31:当前语音或回答尚未结束，请等待结束后重新拍摄",
            documentFailures.poll(3, TimeUnit.SECONDS)
        );
        assertFalse("A busy document state must not close visual WSS",
            clientError.await(200, TimeUnit.MILLISECONDS));

        assertEquals(32, gateway.startTurn(32));
        assertEquals("turn.start", nextText().get("type").getAsString());
        gateway.endTurn(32);
        assertEquals("turn.end", nextText().get("type").getAsString());

        assertEquals(33, gateway.startDocument(33));
        JsonObject nextDocument = nextText();
        assertEquals("document.start", nextDocument.get("type").getAsString());
        assertEquals(33, nextDocument.get("document_seq").getAsLong());
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"document.started\",\"document_seq\":33}"
        );
        assertEquals(Long.valueOf(33), documentStartEvents.poll(3, TimeUnit.SECONDS));
        assertEquals(33, gateway.offerDocumentFrame(
            33, 2_000, 1536, 2048, "back", jpeg(1024)
        ));
        assertNotNull(binaryMessages.poll(3, TimeUnit.SECONDS));
    }

    @Test
    public void unrelatedVisionErrorRemainsFatalDuringDocumentStart() throws Exception {
        assertTrue(gateway.connect());
        assertTrue(serverOpen.await(3, TimeUnit.SECONDS));
        assertNotNull(server.takeRequest(1, TimeUnit.SECONDS));
        assertEquals("vision.start", nextText().get("type").getAsString());
        serverSocket.get().send("{\"v\":1,\"type\":\"vision.started\"}");
        assertTrue(clientOpen.await(3, TimeUnit.SECONDS));

        assertEquals(34, gateway.startDocument(34));
        assertEquals("document.start", nextText().get("type").getAsString());
        serverSocket.get().send(
            "{\"v\":1,\"type\":\"vision.error\",\"code\":\"protocol_error\"}"
        );

        assertTrue(clientError.await(3, TimeUnit.SECONDS));
        assertTrue(clientErrorMessage.get().contains("协议异常"));
        assertNull(documentFailures.poll(200, TimeUnit.MILLISECONDS));
        assertEquals(-1, gateway.startTurn(35));
        assertEquals(-1, gateway.startDocument(35));
    }

    @Test
    public void derivesOnlyFixedSecureEndpoint() {
        assertEquals(
            "wss://123.249.68.176" + VisionWebSocketGateway.VISION_PATH,
            VisionWebSocketGateway.deriveWebSocketUrl("https://123.249.68.176")
        );
        try {
            VisionWebSocketGateway.deriveWebSocketUrl("http://123.249.68.176");
        } catch (IllegalArgumentException expected) {
            assertFalse(expected.getMessage().isEmpty());
            return;
        }
        throw new AssertionError("Cleartext API base must be rejected");
    }

    private JsonObject nextText() throws Exception {
        String text = textMessages.poll(3, TimeUnit.SECONDS);
        assertNotNull(text);
        return JsonParser.parseString(text).getAsJsonObject();
    }

    private TimeoutSignals replaceGatewayForDocumentTimeouts(
        long ackTimeoutMs, long readyTimeoutMs
    ) {
        gateway.destroy();
        TimeoutSignals signals = new TimeoutSignals();
        gateway = new VisionWebSocketGateway(
            client,
            wsUrl,
            false,
            true,
            new VisionWebSocketGateway.Listener() {
                @Override public void onConnected() { signals.connected.countDown(); }
                @Override public void onDisconnected() {}
                @Override public void onError(String message) {
                    signals.message.set(message);
                    signals.error.countDown();
                }
                @Override public void onDocumentStarted(long documentSeq) {
                    signals.started.countDown();
                }
                @Override public void onDocumentAcknowledged(long documentSeq, String status) {
                    signals.acknowledged.countDown();
                }
            },
            ackTimeoutMs,
            readyTimeoutMs
        );
        gateway.configure(
            new VisionSession(
                "vision-timeout", wsUrl, "vision-token-1234567890", "2099-01-01T00:00:00Z"
            ),
            "client-timeout"
        );
        return signals;
    }

    private void openReplacementGateway(TimeoutSignals signals) throws Exception {
        assertTrue(gateway.connect());
        assertTrue(serverOpen.await(3, TimeUnit.SECONDS));
        assertNotNull(server.takeRequest(1, TimeUnit.SECONDS));
        assertEquals("vision.start", nextText().get("type").getAsString());
        serverSocket.get().send("{\"v\":1,\"type\":\"vision.started\"}");
        assertTrue(signals.connected.await(3, TimeUnit.SECONDS));
    }

    private void assertDocumentCredentialInvalidated() {
        assertEquals(-1, gateway.startTurn(88));
        assertEquals(-1, gateway.startDocument(88));
        assertFalse(gateway.connect());
    }

    private JsonObject nextFrameHeader() throws Exception {
        ByteString bytes = binaryMessages.poll(3, TimeUnit.SECONDS);
        assertNotNull(bytes);
        ByteBuffer packet = bytes.asByteBuffer().order(ByteOrder.BIG_ENDIAN);
        long headerLength = Integer.toUnsignedLong(packet.getInt());
        assertTrue(headerLength > 0 && headerLength <= VisionFrameEnvelope.MAX_HEADER_BYTES);
        byte[] json = new byte[(int) headerLength];
        packet.get(json);
        return JsonParser.parseString(new String(json, StandardCharsets.UTF_8)).getAsJsonObject();
    }

    private static String ack(long turnSeq, long frameSeq) {
        return "{\"type\":\"vision.ack\",\"turn_seq\":" + turnSeq
            + ",\"frame_seq\":" + frameSeq + "}";
    }

    private static String ack(long turnSeq, long frameSeq, String status) {
        return "{\"v\":1,\"type\":\"vision.ack\",\"turn_seq\":" + turnSeq
            + ",\"frame_seq\":" + frameSeq + ",\"status\":\"" + status + "\"}";
    }

    private static byte[] jpeg(int size) {
        byte[] value = new byte[size];
        value[0] = (byte) 0xff;
        value[1] = (byte) 0xd8;
        value[size - 2] = (byte) 0xff;
        value[size - 1] = (byte) 0xd9;
        return value;
    }

    private static final class TimeoutSignals {
        private final CountDownLatch connected = new CountDownLatch(1);
        private final CountDownLatch started = new CountDownLatch(1);
        private final CountDownLatch acknowledged = new CountDownLatch(1);
        private final CountDownLatch error = new CountDownLatch(1);
        private final AtomicReference<String> message = new AtomicReference<>();
    }
}
