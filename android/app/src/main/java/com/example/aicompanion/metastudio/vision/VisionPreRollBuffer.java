package com.example.aicompanion.metastudio.vision;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** A memory-only, approximately one-second JPEG pre-roll used for final-only ASR turns. */
final class VisionPreRollBuffer {
    static final long WINDOW_MS = 1_000L;
    static final int MAX_FRAMES = 2;

    private final ArrayDeque<Frame> frames = new ArrayDeque<>(MAX_FRAMES);

    synchronized boolean add(Frame frame) {
        if (frame == null || !frame.isValid()) return false;
        prune(frame.capturedAtMs);
        frames.addLast(frame);
        while (frames.size() > MAX_FRAMES) frames.removeFirst();
        return true;
    }

    synchronized List<Frame> drain(long nowMs) {
        if (nowMs > 0) prune(nowMs);
        List<Frame> result = new ArrayList<>(frames);
        frames.clear();
        return result;
    }

    synchronized void clear() {
        frames.clear();
    }

    synchronized int size() {
        return frames.size();
    }

    private void prune(long newestAtMs) {
        long cutoff = newestAtMs - WINDOW_MS;
        while (!frames.isEmpty() && frames.peekFirst().capturedAtMs < cutoff) {
            frames.removeFirst();
        }
    }

    static final class Frame {
        private final long capturedAtMs;
        private final int width;
        private final int height;
        private final String camera;
        private final byte[] signature;
        private final byte[] jpeg;

        Frame(
            long capturedAtMs,
            int width,
            int height,
            String camera,
            byte[] signature,
            byte[] jpeg
        ) {
            this.capturedAtMs = capturedAtMs;
            this.width = width;
            this.height = height;
            this.camera = camera == null ? "" : camera;
            this.signature = signature == null ? new byte[0] : Arrays.copyOf(
                signature, signature.length
            );
            this.jpeg = jpeg == null ? new byte[0] : Arrays.copyOf(jpeg, jpeg.length);
        }

        private boolean isValid() {
            return capturedAtMs > 0 && width > 0 && height > 0
                && ("front".equals(camera) || "back".equals(camera))
                && signature.length >= 8
                && jpeg.length >= 4
                && jpeg.length <= YuvJpegEncoder.TARGET_JPEG_BYTES
                && (jpeg[0] & 0xff) == 0xff
                && (jpeg[1] & 0xff) == 0xd8
                && (jpeg[jpeg.length - 2] & 0xff) == 0xff
                && (jpeg[jpeg.length - 1] & 0xff) == 0xd9;
        }

        long getCapturedAtMs() { return capturedAtMs; }
        int getWidth() { return width; }
        int getHeight() { return height; }
        String getCamera() { return camera; }
        byte[] getSignature() { return Arrays.copyOf(signature, signature.length); }
        byte[] getJpeg() { return Arrays.copyOf(jpeg, jpeg.length); }
    }
}
