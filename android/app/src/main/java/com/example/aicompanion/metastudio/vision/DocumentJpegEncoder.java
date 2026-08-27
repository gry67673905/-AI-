package com.example.aicompanion.metastudio.vision;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.ImageFormat;
import android.graphics.Matrix;

import androidx.camera.core.ImageProxy;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;

/** Re-encodes an in-memory CameraX JPEG so EXIF and other source metadata are removed. */
public final class DocumentJpegEncoder {
    static final int MAX_DECODE_DIMENSION = 2560;
    static final int MIN_RESIZED_LONG_EDGE = 640;
    static final float RESIZE_FACTOR = 0.85f;
    private static final int MAX_SOURCE_JPEG_BYTES = 16 * 1024 * 1024;
    // Text survives a modest reduction in pixels much better than severe JPEG block artifacts.
    // Never trade document legibility for quality levels below 70 just to meet the wire limit.
    private static final int[] QUALITY_STEPS = {85, 80, 75, 70};

    private DocumentJpegEncoder() {}

    public static EncodedDocument encode(ImageProxy image) {
        if (image == null || image.getFormat() != ImageFormat.JPEG
            || image.getWidth() < 2 || image.getHeight() < 2
            || image.getPlanes() == null || image.getPlanes().length != 1) {
            return null;
        }
        ByteBuffer buffer = image.getPlanes()[0].getBuffer().duplicate();
        if (!buffer.hasRemaining() || buffer.remaining() > MAX_SOURCE_JPEG_BYTES) return null;
        byte[] source = new byte[buffer.remaining()];
        buffer.get(source);
        int rotation = image.getImageInfo().getRotationDegrees();
        if (!(rotation == 0 || rotation == 90 || rotation == 180 || rotation == 270)) {
            return null;
        }

        BitmapFactory.Options bounds = new BitmapFactory.Options();
        bounds.inJustDecodeBounds = true;
        BitmapFactory.decodeByteArray(source, 0, source.length, bounds);
        int sampleSize = calculateInSampleSize(bounds.outWidth, bounds.outHeight);
        if (sampleSize < 1) return null;

        BitmapFactory.Options decode = new BitmapFactory.Options();
        decode.inSampleSize = sampleSize;
        decode.inPreferredConfig = Bitmap.Config.ARGB_8888;
        Bitmap working = BitmapFactory.decodeByteArray(source, 0, source.length, decode);
        if (working == null) return null;
        try {
            float scale = Math.min(
                1f,
                (float) DocumentFrameEnvelope.MAX_DIMENSION
                    / Math.max(working.getWidth(), working.getHeight())
            );
            int width = Math.max(1, Math.round(working.getWidth() * scale));
            int height = Math.max(1, Math.round(working.getHeight() * scale));
            if (width != working.getWidth() || height != working.getHeight()) {
                Bitmap scaled = Bitmap.createScaledBitmap(working, width, height, true);
                if (scaled != working) {
                    working.recycle();
                    working = scaled;
                }
            }
            if (rotation != 0) {
                Matrix matrix = new Matrix();
                matrix.postRotate(rotation);
                Bitmap oriented = Bitmap.createBitmap(
                    working, 0, 0, working.getWidth(), working.getHeight(), matrix, true
                );
                if (oriented != working) {
                    working.recycle();
                    working = oriented;
                }
            }

            return compressPreservingText(working);
        } catch (RuntimeException invalidBitmap) {
            return null;
        } finally {
            working.recycle();
        }
    }

    static int calculateInSampleSize(int width, int height) {
        if (width < 1 || height < 1) return 0;
        long longest = Math.max((long) width, (long) height);
        int sampleSize = 1;
        while ((longest + sampleSize - 1L) / sampleSize > MAX_DECODE_DIMENSION) {
            if (sampleSize > Integer.MAX_VALUE / 2) return 0;
            sampleSize *= 2;
        }
        return sampleSize;
    }

    /** Pure sizing policy kept package-visible so the no-low-quality contract is JVM-testable. */
    static int[] nextDimensions(int width, int height) {
        if (width < 1 || height < 1) return new int[] {0, 0};
        int longest = Math.max(width, height);
        if (longest <= MIN_RESIZED_LONG_EDGE) return new int[] {0, 0};
        float scale = Math.max(
            RESIZE_FACTOR,
            (float) MIN_RESIZED_LONG_EDGE / (float) longest
        );
        int nextWidth = Math.max(1, Math.round(width * scale));
        int nextHeight = Math.max(1, Math.round(height * scale));
        if (nextWidth == width && nextHeight == height) return new int[] {0, 0};
        return new int[] {nextWidth, nextHeight};
    }

    static int minimumOutputQuality() {
        return QUALITY_STEPS[QUALITY_STEPS.length - 1];
    }

    private static EncodedDocument compressPreservingText(Bitmap source) {
        Bitmap candidate = source;
        boolean ownsCandidate = false;
        try {
            while (true) {
                EncodedDocument encoded = compressWithinLimit(candidate);
                if (encoded != null) return encoded;

                int[] next = nextDimensions(candidate.getWidth(), candidate.getHeight());
                if (next[0] < 1 || next[1] < 1) return null;
                Bitmap smaller = Bitmap.createScaledBitmap(candidate, next[0], next[1], true);
                if (smaller == candidate) return null;
                if (ownsCandidate) candidate.recycle();
                candidate = smaller;
                ownsCandidate = true;
            }
        } finally {
            if (ownsCandidate) candidate.recycle();
        }
    }

    private static EncodedDocument compressWithinLimit(Bitmap bitmap) {
        ByteArrayOutputStream output = new ByteArrayOutputStream(
            Math.min(DocumentFrameEnvelope.MAX_JPEG_BYTES, bitmap.getWidth() * bitmap.getHeight() / 3)
        );
        for (int quality : QUALITY_STEPS) {
            output.reset();
            if (bitmap.compress(Bitmap.CompressFormat.JPEG, quality, output)
                && output.size() <= DocumentFrameEnvelope.MAX_JPEG_BYTES) {
                byte[] jpeg = output.toByteArray();
                if (jpeg.length >= 4
                    && (jpeg[0] & 0xff) == 0xff && (jpeg[1] & 0xff) == 0xd8
                    && (jpeg[jpeg.length - 2] & 0xff) == 0xff
                    && (jpeg[jpeg.length - 1] & 0xff) == 0xd9) {
                    return new EncodedDocument(
                        jpeg,
                        bitmap.getWidth(),
                        bitmap.getHeight(),
                        quality
                    );
                }
            }
        }
        return null;
    }

    public static final class EncodedDocument {
        private final byte[] bytes;
        private final int width;
        private final int height;
        private final int jpegQuality;

        private EncodedDocument(byte[] bytes, int width, int height, int jpegQuality) {
            this.bytes = bytes;
            this.width = width;
            this.height = height;
            this.jpegQuality = jpegQuality;
        }

        public byte[] getBytes() { return bytes; }
        public int getWidth() { return width; }
        public int getHeight() { return height; }
        /** Safe diagnostic metadata only; the image itself is never logged or persisted. */
        public int getJpegQuality() { return jpegQuality; }
    }
}
