package com.example.aicompanion.metastudio.vision;

import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;

/** One high-resolution document photo carried by the existing native visual WebSocket. */
public final class DocumentFrameEnvelope {
    public static final int VERSION = 1;
    public static final int MAX_DIMENSION = 2048;
    public static final int MAX_JPEG_BYTES = 1024 * 1024;
    public static final int MAX_HEADER_BYTES = 2048;

    private static final Gson GSON = new Gson();

    private DocumentFrameEnvelope() {}

    public static byte[] encode(Frame frame) {
        validate(frame);
        JsonObject header = new JsonObject();
        header.addProperty("v", VERSION);
        header.addProperty("type", "document.frame");
        header.addProperty("document_seq", frame.documentSeq);
        header.addProperty("captured_at_ms", frame.capturedAtMs);
        header.addProperty("width", frame.width);
        header.addProperty("height", frame.height);
        header.addProperty("camera", frame.camera);
        byte[] json = GSON.toJson(header).getBytes(StandardCharsets.UTF_8);
        if (json.length < 1 || json.length > MAX_HEADER_BYTES) {
            throw new IllegalArgumentException("Invalid document frame header length");
        }
        ByteBuffer output = ByteBuffer.allocate(4 + json.length + frame.jpeg.length)
            .order(ByteOrder.BIG_ENDIAN);
        output.putInt(json.length);
        output.put(json);
        output.put(frame.jpeg);
        return output.array();
    }

    private static void validate(Frame frame) {
        if (frame == null || frame.documentSeq < 1 || frame.capturedAtMs < 1) {
            throw new IllegalArgumentException("Invalid document frame identity");
        }
        if (frame.width < 1 || frame.width > MAX_DIMENSION
            || frame.height < 1 || frame.height > MAX_DIMENSION) {
            throw new IllegalArgumentException("Invalid document frame dimensions");
        }
        if (!("front".equals(frame.camera) || "back".equals(frame.camera))) {
            throw new IllegalArgumentException("Invalid camera facing");
        }
        if (frame.jpeg.length < 4 || frame.jpeg.length > MAX_JPEG_BYTES
            || (frame.jpeg[0] & 0xff) != 0xff || (frame.jpeg[1] & 0xff) != 0xd8
            || (frame.jpeg[frame.jpeg.length - 2] & 0xff) != 0xff
            || (frame.jpeg[frame.jpeg.length - 1] & 0xff) != 0xd9) {
            throw new IllegalArgumentException("Invalid or oversized document JPEG");
        }
    }

    public static final class Frame {
        private final long documentSeq;
        private final long capturedAtMs;
        private final int width;
        private final int height;
        private final String camera;
        private final byte[] jpeg;

        public Frame(
            long documentSeq,
            long capturedAtMs,
            int width,
            int height,
            String camera,
            byte[] jpeg
        ) {
            this.documentSeq = documentSeq;
            this.capturedAtMs = capturedAtMs;
            this.width = width;
            this.height = height;
            this.camera = camera == null ? "" : camera;
            this.jpeg = jpeg == null ? new byte[0] : Arrays.copyOf(jpeg, jpeg.length);
        }
    }
}
