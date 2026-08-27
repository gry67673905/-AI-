package com.example.aicompanion.metastudio.vision;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.fail;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import org.junit.Test;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

public final class VisionFrameEnvelopeTest {
    @Test
    public void goldenPacketUsesFourByteHeaderLengthExactEightFieldsThenJpeg() {
        byte[] jpeg = jpeg(32);
        byte[] packet = VisionFrameEnvelope.encode(new VisionFrameEnvelope.Frame(
            7, 11, 1_724_000_000_123L, 480, 640, "front", jpeg
        ));

        ByteBuffer input = ByteBuffer.wrap(packet).order(ByteOrder.BIG_ENDIAN);
        long unsignedLength = Integer.toUnsignedLong(input.getInt());
        assertTrue(unsignedLength > 0 && unsignedLength <= VisionFrameEnvelope.MAX_HEADER_BYTES);
        byte[] headerBytes = new byte[(int) unsignedLength];
        input.get(headerBytes);
        JsonObject header = JsonParser.parseString(
            new String(headerBytes, StandardCharsets.UTF_8)
        ).getAsJsonObject();

        assertEquals(8, header.size());
        assertEquals(1, header.get("v").getAsInt());
        assertEquals("vision.frame", header.get("type").getAsString());
        assertEquals(7, header.get("turn_seq").getAsLong());
        assertEquals(11, header.get("frame_seq").getAsLong());
        assertEquals(1_724_000_000_123L, header.get("captured_at_ms").getAsLong());
        assertEquals(480, header.get("width").getAsInt());
        assertEquals(640, header.get("height").getAsInt());
        assertEquals("front", header.get("camera").getAsString());
        assertFalse(header.has("rotation_degrees"));

        byte[] actualJpeg = new byte[input.remaining()];
        input.get(actualJpeg);
        assertArrayEquals(jpeg, actualJpeg);
    }

    @Test
    public void rejectsOversizedJpegAndDimensions() {
        expectInvalid(new VisionFrameEnvelope.Frame(
            1, 1, 1, 1281, 480, "back", jpeg(16)
        ));
        expectInvalid(new VisionFrameEnvelope.Frame(
            1, 1, 1, 640, 480, "back", jpeg(VisionFrameEnvelope.MAX_JPEG_BYTES + 1)
        ));
    }

    private static void expectInvalid(VisionFrameEnvelope.Frame frame) {
        try {
            VisionFrameEnvelope.encode(frame);
            fail("Expected invalid frame");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().startsWith("Invalid"));
        }
    }

    static byte[] jpeg(int size) {
        byte[] value = new byte[Math.max(4, size)];
        value[0] = (byte) 0xff;
        value[1] = (byte) 0xd8;
        value[value.length - 2] = (byte) 0xff;
        value[value.length - 1] = (byte) 0xd9;
        return value;
    }
}
