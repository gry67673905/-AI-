package com.example.aicompanion.metastudio;

import static org.junit.Assert.assertTrue;
import static org.junit.Assert.assertFalse;

import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

public final class DigitalHumanManifestTest {
    @Test
    public void declaresBothWebRtcAudioPermissions() throws Exception {
        Path manifest = Paths.get("src", "main", "AndroidManifest.xml");
        String xml = new String(Files.readAllBytes(manifest), StandardCharsets.UTF_8);

        assertTrue(xml.contains("android.permission.RECORD_AUDIO"));
        assertTrue(xml.contains("android.permission.MODIFY_AUDIO_SETTINGS"));
    }

    @Test
    public void declaresTextToSpeechServiceVisibilityForNavigationGuidance() throws Exception {
        String manifest = read("src", "main", "AndroidManifest.xml");

        assertTrue(manifest.contains("android.intent.action.TTS_SERVICE"));
    }

    @Test
    public void declaresOptionalCameraWithoutWideningWebViewCapturePermission() throws Exception {
        String manifest = read("src", "main", "AndroidManifest.xml");
        assertTrue(manifest.contains("android.permission.CAMERA"));
        assertTrue(manifest.contains("android.hardware.camera.any"));
        assertTrue(manifest.contains("android:required=\"false\""));

        String host = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "boundary", "DigitalHumanWebViewHost.java");
        assertTrue(host.contains("PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resources[0])"));
        assertFalse(host.contains("PermissionRequest.RESOURCE_VIDEO_CAPTURE"));

        String controller = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "CameraXVisionController.java");
        assertTrue(controller.contains("new Preview.Builder()"));
        assertTrue(controller.contains("new ImageAnalysis.Builder()"));
        assertTrue(controller.contains("lensFacing = CameraSelector.LENS_FACING_FRONT"));
        assertFalse(controller.contains("VideoCapture"));
        assertFalse(controller.contains("Recorder"));

        String encoder = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "YuvJpegEncoder.java");
        assertTrue(encoder.contains("matrix.postRotate(rotation)"));
        assertTrue(encoder.contains("rotated.getWidth(), rotated.getHeight()"));
    }

    @Test
    public void secureSessionBrokerStaysInMainProcessAndIsNotExported() throws Exception {
        String manifest = read("src", "main", "AndroidManifest.xml");
        assertTrue(manifest.contains(".portal.gateway.SecureSessionBrokerProvider"));
        assertTrue(manifest.contains("${applicationId}.secure-session-broker"));
        assertTrue(manifest.contains("android:exported=\"false\""));
        assertTrue(manifest.contains("android:grantUriPermissions=\"false\""));
        assertFalse(manifest.contains("android:multiprocess=\"true\""));

        String activity = read("src", "main", "java", "com", "example", "aicompanion",
            "DigitalHumanActivity.java");
        assertTrue(activity.contains("new BrokeredSecureSessionStore"));
        assertFalse(activity.contains("new AndroidKeystoreSessionStore"));
        assertTrue(activity.contains("visionController.setForeground(foreground);"));
    }

    private static String read(String first, String... rest) throws Exception {
        Path path = Paths.get(first, rest);
        return new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
    }
}
