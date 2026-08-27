package com.example.aicompanion.metastudio.vision;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.util.Arrays;
import java.util.List;

public final class VisionPreRollBufferTest {
    @Test
    public void keepsLatestTwoFramesWithinApproximatelyOneSecondThenDrainsOnce() {
        VisionPreRollBuffer buffer = new VisionPreRollBuffer();
        assertTrue(buffer.add(frame(1_000, 10)));
        assertTrue(buffer.add(frame(1_400, 20)));
        assertTrue(buffer.add(frame(1_900, 30)));
        assertEquals(VisionPreRollBuffer.MAX_FRAMES, buffer.size());

        List<VisionPreRollBuffer.Frame> drained = buffer.drain(2_000);

        assertEquals(2, drained.size());
        assertEquals(1_400, drained.get(0).getCapturedAtMs());
        assertEquals(1_900, drained.get(1).getCapturedAtMs());
        assertEquals(0, buffer.size());
        assertTrue(buffer.drain(2_000).isEmpty());
    }

    @Test
    public void expiresOldFramesAndDefensivelyCopiesCameraBytes() {
        VisionPreRollBuffer buffer = new VisionPreRollBuffer();
        byte[] signature = filled(16, 40);
        byte[] jpeg = jpeg(32);
        VisionPreRollBuffer.Frame frame = new VisionPreRollBuffer.Frame(
            1_000, 640, 480, "front", signature, jpeg
        );
        assertTrue(buffer.add(frame));
        signature[0] = 99;
        jpeg[0] = 0;

        List<VisionPreRollBuffer.Frame> retained = buffer.drain(2_000);
        assertEquals(1, retained.size());
        assertArrayEquals(filled(16, 40), retained.get(0).getSignature());
        assertEquals(0xff, retained.get(0).getJpeg()[0] & 0xff);

        assertTrue(buffer.add(frame(3_000, 50)));
        assertTrue(buffer.drain(4_001).isEmpty());
    }

    @Test
    public void rejectsOversizedOrMalformedJpeg() {
        VisionPreRollBuffer buffer = new VisionPreRollBuffer();
        assertFalse(buffer.add(new VisionPreRollBuffer.Frame(
            1_000,
            640,
            480,
            "front",
            filled(16, 10),
            jpeg(YuvJpegEncoder.TARGET_JPEG_BYTES + 1)
        )));
        assertFalse(buffer.add(new VisionPreRollBuffer.Frame(
            1_000, 640, 480, "front", filled(16, 10), new byte[32]
        )));
    }

    private static VisionPreRollBuffer.Frame frame(long capturedAtMs, int value) {
        return new VisionPreRollBuffer.Frame(
            capturedAtMs, 640, 480, "front", filled(16, value), jpeg(32)
        );
    }

    private static byte[] filled(int size, int value) {
        byte[] result = new byte[size];
        Arrays.fill(result, (byte) value);
        return result;
    }

    private static byte[] jpeg(int size) {
        byte[] value = new byte[Math.max(4, size)];
        value[0] = (byte) 0xff;
        value[1] = (byte) 0xd8;
        value[value.length - 2] = (byte) 0xff;
        value[value.length - 1] = (byte) 0xd9;
        return value;
    }
}
