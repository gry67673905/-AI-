package com.example.aicompanion.metastudio.vision;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import org.junit.Test;

import java.nio.ByteBuffer;

public final class LumaSignatureSamplerTest {
    @Test
    public void samplesPaddedLumaPlaneWithoutChangingInputPosition() {
        int width = 64;
        int height = 48;
        int rowStride = 68;
        ByteBuffer source = ByteBuffer.allocate(rowStride * height + 3);
        source.position(3);
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                source.put(3 + y * rowStride + x, (byte) ((x + y) & 0xff));
            }
        }
        int originalPosition = source.position();

        byte[] signature = LumaSignatureSampler.sample(source, width, height, rowStride, 1);

        assertEquals(32 * 24, signature.length);
        assertEquals(originalPosition, source.position());
        assertTrue((signature[0] & 0xff) > 0);
        assertTrue((signature[signature.length - 1] & 0xff) > (signature[0] & 0xff));
    }

    @Test
    public void rejectsTruncatedPlane() {
        try {
            LumaSignatureSampler.sample(ByteBuffer.allocate(10), 64, 48, 64, 1);
            fail("Expected truncated plane");
        } catch (IllegalArgumentException expected) {
            assertEquals("Truncated luma plane", expected.getMessage());
        }
    }
}
