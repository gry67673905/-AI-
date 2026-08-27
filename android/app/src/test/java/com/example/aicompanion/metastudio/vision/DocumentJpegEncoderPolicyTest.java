package com.example.aicompanion.metastudio.vision;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

public final class DocumentJpegEncoderPolicyTest {
    @Test
    public void boundsDecodeBeforeAllocatingFullCameraBitmap() {
        assertEquals(1, DocumentJpegEncoder.calculateInSampleSize(2048, 1536));
        assertEquals(2, DocumentJpegEncoder.calculateInSampleSize(4032, 3024));
        assertEquals(4, DocumentJpegEncoder.calculateInSampleSize(8000, 6000));
        assertEquals(0, DocumentJpegEncoder.calculateInSampleSize(0, 2048));
    }

    @Test
    public void preservesJpegQualityAndShrinksPixelsGradually() {
        assertEquals(70, DocumentJpegEncoder.minimumOutputQuality());

        int[] first = DocumentJpegEncoder.nextDimensions(2048, 1536);
        assertEquals(1741, first[0]);
        assertEquals(1306, first[1]);
        assertTrue(first[0] < 2048);
        assertTrue(first[1] < 1536);

        int[] floor = DocumentJpegEncoder.nextDimensions(700, 525);
        assertEquals(640, floor[0]);
        assertEquals(480, floor[1]);
        assertEquals(0, DocumentJpegEncoder.nextDimensions(640, 480)[0]);
    }
}
