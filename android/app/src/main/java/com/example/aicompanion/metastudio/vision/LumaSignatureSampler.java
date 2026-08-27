package com.example.aicompanion.metastudio.vision;

import java.nio.ByteBuffer;

/** Small grayscale signature used for cheap scene-change detection without OpenCV. */
public final class LumaSignatureSampler {
    public static final int SIGNATURE_WIDTH = 32;
    public static final int SIGNATURE_HEIGHT = 24;

    private LumaSignatureSampler() {}

    public static byte[] sample(
        ByteBuffer source,
        int width,
        int height,
        int rowStride,
        int pixelStride
    ) {
        if (source == null || width < 1 || height < 1 || rowStride < 1 || pixelStride < 1) {
            throw new IllegalArgumentException("Invalid luma plane");
        }
        ByteBuffer data = source.duplicate();
        int base = data.position();
        int limit = data.limit();
        byte[] signature = new byte[SIGNATURE_WIDTH * SIGNATURE_HEIGHT];
        for (int targetY = 0; targetY < SIGNATURE_HEIGHT; targetY++) {
            int sourceY = Math.min(height - 1, ((2 * targetY + 1) * height) / (2 * SIGNATURE_HEIGHT));
            for (int targetX = 0; targetX < SIGNATURE_WIDTH; targetX++) {
                int sourceX = Math.min(width - 1, ((2 * targetX + 1) * width) / (2 * SIGNATURE_WIDTH));
                long offset = (long) base + (long) sourceY * rowStride + (long) sourceX * pixelStride;
                if (offset < base || offset >= limit) throw new IllegalArgumentException("Truncated luma plane");
                signature[targetY * SIGNATURE_WIDTH + targetX] = data.get((int) offset);
            }
        }
        return signature;
    }
}
