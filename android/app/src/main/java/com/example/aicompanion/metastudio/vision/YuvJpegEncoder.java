package com.example.aicompanion.metastudio.vision;

import android.graphics.ImageFormat;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Matrix;
import android.graphics.Rect;
import android.graphics.YuvImage;

import androidx.camera.core.ImageProxy;

import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;

/** Encodes only selected CameraX analysis frames; raw camera data is never written to disk. */
public final class YuvJpegEncoder {
    /** Keeps eight temporal samples within the former three-by-256 KiB turn budget. */
    public static final int TARGET_JPEG_BYTES = 96 * 1024;
    private static final int[] QUALITY_STEPS = {65, 55, 45, 35, 25, 20};

    private YuvJpegEncoder() {}

    public static EncodedJpeg encode(ImageProxy image) {
        if (image == null || image.getFormat() != ImageFormat.YUV_420_888
            || image.getWidth() < 2 || image.getHeight() < 2
            || (image.getWidth() & 1) != 0 || (image.getHeight() & 1) != 0) {
            return null;
        }
        ImageProxy.PlaneProxy[] planes = image.getPlanes();
        if (planes == null || planes.length != 3) return null;
        int width = image.getWidth();
        int height = image.getHeight();
        byte[] nv21;
        try {
            nv21 = toNv21(planes, width, height);
        } catch (RuntimeException invalidPlane) {
            return null;
        }
        int rotation = image.getImageInfo().getRotationDegrees();
        if (!(rotation == 0 || rotation == 90 || rotation == 180 || rotation == 270)) return null;
        YuvImage yuv = new YuvImage(nv21, ImageFormat.NV21, width, height, null);
        if (rotation != 0) return rotateAndEncode(yuv, width, height, rotation);
        byte[] jpeg = compress(yuv, width, height);
        return jpeg == null ? null : new EncodedJpeg(jpeg, width, height);
    }

    private static byte[] compress(YuvImage yuv, int width, int height) {
        ByteArrayOutputStream output = new ByteArrayOutputStream(Math.min(
            TARGET_JPEG_BYTES, width * height / 2
        ));
        for (int quality : QUALITY_STEPS) {
            output.reset();
            if (yuv.compressToJpeg(new Rect(0, 0, width, height), quality, output)
                && output.size() <= TARGET_JPEG_BYTES) {
                return output.toByteArray();
            }
        }
        return null;
    }

    private static EncodedJpeg rotateAndEncode(YuvImage yuv, int width, int height, int rotation) {
        ByteArrayOutputStream intermediate = new ByteArrayOutputStream(width * height / 2);
        if (!yuv.compressToJpeg(new Rect(0, 0, width, height), 90, intermediate)) return null;
        byte[] source = intermediate.toByteArray();
        Bitmap bitmap = BitmapFactory.decodeByteArray(source, 0, source.length);
        if (bitmap == null) return null;
        Matrix matrix = new Matrix();
        matrix.postRotate(rotation);
        Bitmap rotated = null;
        try {
            rotated = Bitmap.createBitmap(
                bitmap, 0, 0, bitmap.getWidth(), bitmap.getHeight(), matrix, true
            );
            ByteArrayOutputStream output = new ByteArrayOutputStream(Math.min(
                TARGET_JPEG_BYTES, width * height / 2
            ));
            for (int quality : QUALITY_STEPS) {
                output.reset();
                if (rotated.compress(Bitmap.CompressFormat.JPEG, quality, output)
                    && output.size() <= TARGET_JPEG_BYTES) {
                    return new EncodedJpeg(output.toByteArray(), rotated.getWidth(), rotated.getHeight());
                }
            }
            return null;
        } finally {
            if (rotated != null && rotated != bitmap) rotated.recycle();
            bitmap.recycle();
        }
    }

    private static byte[] toNv21(ImageProxy.PlaneProxy[] planes, int width, int height) {
        int ySize = width * height;
        byte[] output = new byte[ySize + ySize / 2];
        copyPlane(planes[0], width, height, output, 0, 1);
        int chromaWidth = width / 2;
        int chromaHeight = height / 2;
        // NV21 stores interleaved V then U bytes.
        copyPlane(planes[2], chromaWidth, chromaHeight, output, ySize, 2);
        copyPlane(planes[1], chromaWidth, chromaHeight, output, ySize + 1, 2);
        return output;
    }

    private static void copyPlane(
        ImageProxy.PlaneProxy plane,
        int width,
        int height,
        byte[] output,
        int outputOffset,
        int outputPixelStride
    ) {
        ByteBuffer buffer = plane.getBuffer().duplicate();
        int base = buffer.position();
        int limit = buffer.limit();
        int rowStride = plane.getRowStride();
        int pixelStride = plane.getPixelStride();
        for (int row = 0; row < height; row++) {
            for (int column = 0; column < width; column++) {
                long inputIndex = (long) base + (long) row * rowStride + (long) column * pixelStride;
                int targetIndex = outputOffset + (row * width + column) * outputPixelStride;
                if (inputIndex < base || inputIndex >= limit || targetIndex >= output.length) {
                    throw new IllegalArgumentException("Truncated YUV plane");
                }
                output[targetIndex] = buffer.get((int) inputIndex);
            }
        }
    }

    public static final class EncodedJpeg {
        private final byte[] bytes;
        private final int width;
        private final int height;

        private EncodedJpeg(byte[] bytes, int width, int height) {
            this.bytes = bytes;
            this.width = width;
            this.height = height;
        }

        public byte[] getBytes() { return bytes; }
        public int getWidth() { return width; }
        public int getHeight() { return height; }
    }
}
