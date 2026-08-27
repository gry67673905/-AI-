package com.example.aicompanion.metastudio.vision;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Test;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

public final class VisionIntegrationBoundaryTest {
    @Test
    public void ticketIsRequestedOnlyAfterExplicitEnableAndConsumedOnce() throws Exception {
        String activity = read("src", "main", "java", "com", "example", "aicompanion",
            "DigitalHumanActivity.java");
        String requestClient = between(
            activity,
            "private void requestClientSession(",
            "private void exchangeIntent("
        );
        assertTrue(requestClient.contains("visionClientSessionId = value.getSessionId()"));
        assertFalse(requestClient.contains("visionSessionGateway.create"));

        String requestTicket = between(
            activity,
            "private void requestVisionTicketAndEnable()",
            "private void toggleVision()"
        );
        assertTrue(requestTicket.contains("visionSessionGateway.create(clientSessionId"));
        assertTrue(requestTicket.contains("visionController.enable()"));
        String beginEnable = between(
            activity,
            "private void beginVisionEnable()",
            "private void onCameraPermissionResult("
        );
        assertTrue(beginEnable.contains("Manifest.permission.CAMERA"));
        assertTrue(beginEnable.contains("requestVisionTicketAndEnable()"));

        String socket = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "VisionWebSocketGateway.java");
        assertTrue(socket.contains("pendingVisionToken = \"\";"));
        assertTrue(socket.contains("public synchronized void disconnect()"));
        assertTrue(socket.contains("clearCredentialLocked()"));
    }

    @Test
    public void finalFrameIsQueuedBeforeTurnEndAndTimeoutIsFallback() throws Exception {
        String controller = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "CameraXVisionController.java");
        int offerFinal = controller.indexOf("gateway.offerFinalFrame(");
        int finish = controller.indexOf("mainHandler.post(() -> finishTurn", offerFinal);
        assertTrue(offerFinal > 0 && finish > offerFinal);
        assertTrue(controller.contains("mainHandler.postDelayed(finalFrameTimeout, FINAL_FRAME_TIMEOUT_MS)"));
    }

    @Test
    public void temporalSamplingKeepsWireProtocolAndAsrTextOutOfNativeVision() throws Exception {
        String controller = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "CameraXVisionController.java");
        String selector = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "VisionFrameSelector.java");
        String encoder = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "YuvJpegEncoder.java");
        String envelope = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "VisionFrameEnvelope.java");

        assertTrue(controller.contains("private static final long ANALYSIS_INTERVAL_MS = 500L"));
        assertTrue(controller.contains(
            "if (elapsed - lastAnalyzedElapsedMs < ANALYSIS_INTERVAL_MS) return;"
        ));
        assertTrue(controller.contains("VisionPreRollBuffer"));
        assertTrue(selector.contains("MAX_FRAMES_PER_TURN = 8"));
        assertTrue(encoder.contains("TARGET_JPEG_BYTES = 96 * 1024"));
        assertTrue(envelope.contains("VERSION = 1"));
        assertTrue(envelope.contains("\"type\", \"vision.frame\""));
        assertFalse(controller.contains("question.text"));
        assertFalse(controller.contains("speechText"));
    }

    @Test
    public void documentModeUsesExplicitHighResolutionPhotoWithoutRealtimeOcr() throws Exception {
        String controller = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "CameraXVisionController.java");
        String encoder = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "DocumentJpegEncoder.java");
        String envelope = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "DocumentFrameEnvelope.java");
        String socket = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "VisionWebSocketGateway.java");

        assertTrue(controller.contains("ImageCapture.OnImageCapturedCallback"));
        assertTrue(controller.contains("ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY"));
        assertTrue(controller.contains("if (hasBackCamera) lensFacing"));
        assertTrue(controller.contains("|| documentMode"));
        assertTrue(controller.contains(
            "if (destroyed || !userEnabled || !foreground || documentMode) return;"
        ));
        assertTrue(encoder.contains("inJustDecodeBounds = true"));
        assertTrue(encoder.contains("decode.inSampleSize = sampleSize"));
        assertTrue(encoder.contains("Bitmap.CompressFormat.JPEG, quality"));
        assertTrue(encoder.contains("QUALITY_STEPS = {85"));
        assertTrue(encoder.contains("QUALITY_STEPS = {85, 80, 75, 70}"));
        assertFalse(encoder.contains(", 65, 60, 55, 50, 45, 40"));
        assertTrue(envelope.contains("MAX_DIMENSION = 2048"));
        assertTrue(envelope.contains("MAX_JPEG_BYTES = 1024 * 1024"));
        assertTrue(envelope.contains("\"type\", \"document.frame\""));
        assertTrue(socket.contains("control(\"document.start\")"));
        assertTrue(socket.contains("\"document.started\".equals(type)"));
        assertTrue(socket.contains("\"document.ack\".equals(type)"));
        assertTrue(socket.contains("\"document.ready\".equals(type)"));
        assertFalse(controller.contains("MLKit"));
        assertFalse(controller.contains("OpenCV"));
        assertFalse(controller.contains("FileOutput"));
    }

    @Test
    public void recoverableDocumentResultRestoresOrdinaryVisionWithoutClosingTicket()
        throws Exception {
        String activity = read("src", "main", "java", "com", "example", "aicompanion",
            "DigitalHumanActivity.java");
        String controller = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "CameraXVisionController.java");
        String socket = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "VisionWebSocketGateway.java");

        String activityCallback = between(
            activity,
            "@Override public void onDocumentFailed(",
            "@Override public void onDisconnected()"
        );
        assertTrue(activityCallback.contains("visionController.onDocumentFailed(documentSeq)"));
        assertTrue(activityCallback.contains("showStatus("));
        assertFalse(activityCallback.contains("visionController.disable()"));

        String controllerFailure = between(
            controller,
            "public void onDocumentFailed(",
            "public boolean cancelDocumentMode()"
        );
        assertTrue(controllerFailure.contains("resetDocumentLocked(false)"));
        assertTrue(controllerFailure.contains("bindUseCases()"));
        assertTrue(controllerFailure.contains("onDocumentStateChanged(false, false)"));
        assertFalse(controllerFailure.contains("disable()"));

        String socketFailure = between(
            socket,
            "if (\"document.error\".equals(type))",
            "if (awaitingAck == null) return;"
        );
        assertTrue(socketFailure.contains("clearFailedDocumentLocked(documentSeq)"));
        assertTrue(socketFailure.contains("listener.onDocumentFailed(documentSeq, message)"));
        assertFalse(socketFailure.contains("failLocked("));
        assertTrue(socket.contains("if (\"document_unreadable\".equals(code))"));
        assertTrue(socket.contains("if (\"analysis_unavailable\".equals(code))"));
    }

    @Test
    public void documentButtonWaitsForMetaStudioIdleAndBusyRejectionIsRecoverable()
        throws Exception {
        String activity = read("src", "main", "java", "com", "example", "aicompanion",
            "DigitalHumanActivity.java");
        String socket = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "VisionWebSocketGateway.java");

        assertTrue(activity.contains("documentInteractionBusy = true"));
        assertTrue(activity.contains("!documentInteractionBusy"));
        assertTrue(activity.contains("请等待当前语音或回答结束后再识别文件"));
        assertTrue(socket.contains("\"invalid_document_state\".equals(code)"));
        assertTrue(socket.contains("clearFailedDocumentLocked(documentSeq)"));
        assertTrue(socket.contains("当前语音或回答尚未结束，请等待结束后重新拍摄"));

        String controller = read("src", "main", "java", "com", "example", "aicompanion",
            "metastudio", "vision", "CameraXVisionController.java");
        String endActiveTurn = between(
            controller, "private void endActiveTurn()", "private void unbindUseCases()"
        );
        assertTrue(endActiveTurn.contains("selected > 0 ? selected : pendingFinalTurnSeq"));
        assertTrue(endActiveTurn.contains("gateway.endTurn(active)"));
    }

    @Test
    public void compactPhoneUsesSeparateStatusAndEqualWidthActionRow() throws Exception {
        String layout = read("src", "main", "res", "layout", "activity_digital_human.xml");
        int overlay = layout.indexOf("@+id/digitalHumanDocumentOverlay");
        int statusPanel = layout.indexOf("@+id/digitalHumanStatusPanel");
        assertTrue("Status panel must remain above the document overlay", overlay > 0
            && statusPanel > overlay);
        assertTrue(layout.contains("android:id=\"@+id/digitalHumanStatusPanel\""));
        assertTrue(layout.contains("android:orientation=\"vertical\""));
        assertTrue(equalWidthButton(layout, "digitalHumanVisionToggle"));
        assertTrue(equalWidthButton(layout, "digitalHumanCameraSwitch"));
        assertTrue(equalWidthButton(layout, "digitalHumanDocumentRecognize"));
        assertTrue(equalWidthButton(layout, "digitalHumanClose"));
    }

    private static boolean equalWidthButton(String layout, String id) {
        int start = layout.indexOf("@+id/" + id);
        int end = layout.indexOf("/>", start);
        if (start < 0 || end < 0) return false;
        String button = layout.substring(start, end);
        return button.contains("android:layout_width=\"0dp\"")
            && button.contains("android:layout_weight=\"1\"")
            && button.contains("android:maxLines=\"1\"");
    }

    private static String between(String source, String start, String end) {
        int from = source.indexOf(start);
        int to = source.indexOf(end, from + start.length());
        if (from < 0 || to < 0) throw new AssertionError("Expected source boundary");
        return source.substring(from, to);
    }

    private static String read(String first, String... rest) throws Exception {
        Path path = Paths.get(first, rest);
        return new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
    }
}
