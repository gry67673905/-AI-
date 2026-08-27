package com.example.aicompanion.metastudio.vision;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import org.junit.Test;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;

public final class DocumentFrameEnvelopeTest {
    @Test
    public void encodesFixedHeaderAndMetadataFreeJpegPayload() {
        byte[] jpeg = jpeg(1024);
        byte[] encoded = DocumentFrameEnvelope.encode(new DocumentFrameEnvelope.Frame(
            9, 123456789L, 1536, 2048, "back", jpeg
        ));
        ByteBuffer packet = ByteBuffer.wrap(encoded).order(ByteOrder.BIG_ENDIAN);
        int headerLength = packet.getInt();
        assertTrue(headerLength > 0 && headerLength <= DocumentFrameEnvelope.MAX_HEADER_BYTES);
        byte[] headerBytes = new byte[headerLength];
        packet.get(headerBytes);
        JsonObject header = JsonParser.parseString(
            new String(headerBytes, StandardCharsets.UTF_8)
        ).getAsJsonObject();
        assertEquals(7, header.size());
        assertEquals("document.frame", header.get("type").getAsString());
        assertEquals(9, header.get("document_seq").getAsLong());
        assertEquals(1536, header.get("width").getAsInt());
        assertEquals(2048, header.get("height").getAsInt());
        assertEquals("back", header.get("camera").getAsString());
        assertEquals(jpeg.length, packet.remaining());
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsOversizedDocumentPhoto() {
        DocumentFrameEnvelope.encode(new DocumentFrameEnvelope.Frame(
            1, 1, 2048, 2048, "back",
            jpeg(DocumentFrameEnvelope.MAX_JPEG_BYTES + 1)
        ));
    }

    @Test(expected = IllegalArgumentException.class)
    public void rejectsDimensionsBeyondDocumentContract() {
        DocumentFrameEnvelope.encode(new DocumentFrameEnvelope.Frame(
            1, 1, 2049, 1000, "back", jpeg(100)
        ));
    }

    private static byte[] jpeg(int size) {
        byte[] value = new byte[size];
        value[0] = (byte) 0xff;
        value[1] = (byte) 0xd8;
        value[size - 2] = (byte) 0xff;
        value[size - 1] = (byte) 0xd9;
        return value;
    }
}
