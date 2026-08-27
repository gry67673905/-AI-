package com.example.aicompanion.metastudio.vision;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.pm.PackageManager;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.util.Size;
import android.view.View;

import androidx.appcompat.app.AppCompatActivity;
import androidx.annotation.NonNull;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageCapture;
import androidx.camera.core.ImageCaptureException;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;

import java.nio.ByteBuffer;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;

/** Foreground-only CameraX preview and bounded temporal-frame analyzer. Never captures audio. */
public final class CameraXVisionController {
    private static final long ANALYSIS_INTERVAL_MS = 500L;
    private static final long FINAL_FRAME_TIMEOUT_MS = 750L;

    private final AppCompatActivity activity;
    private final PreviewView previewView;
    private final VisionWebSocketGateway gateway;
    private final Listener listener;
    private final VisionFrameSelector selector = new VisionFrameSelector();
    private final VisionPreRollBuffer preRoll = new VisionPreRollBuffer();
    private final Object frameStateLock = new Object();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private final ExecutorService analyzerExecutor = Executors.newSingleThreadExecutor(
        new ThreadFactory() {
            @Override public Thread newThread(Runnable task) {
                Thread thread = new Thread(task, "digital-human-vision-analysis");
                thread.setDaemon(true);
                return thread;
            }
        }
    );

    private ListenableFuture<ProcessCameraProvider> providerFuture;
    private ProcessCameraProvider cameraProvider;
    private ImageAnalysis imageAnalysis;
    private ImageCapture imageCapture;
    private int lensFacing = CameraSelector.LENS_FACING_FRONT;
    private boolean hasFrontCamera;
    private boolean hasBackCamera;
    private boolean userEnabled;
    private boolean foreground;
    private boolean destroyed;
    private long lastAnalyzedElapsedMs;
    private long pendingFinalTurnSeq;
    private Runnable finalFrameTimeout;
    private volatile boolean documentMode;
    private volatile boolean documentCaptureBusy;
    private long nextDocumentSeq;
    private long activeDocumentSeq;
    private long pendingDocumentCapturedAtMs;
    private String pendingDocumentCamera = "back";
    private DocumentJpegEncoder.EncodedDocument pendingDocument;

    public CameraXVisionController(
        AppCompatActivity activity,
        PreviewView previewView,
        VisionWebSocketGateway gateway,
        Listener listener
    ) {
        if (activity == null || previewView == null || gateway == null || listener == null) {
            throw new IllegalArgumentException("Camera vision dependencies are required");
        }
        this.activity = activity;
        this.previewView = previewView;
        this.gateway = gateway;
        this.listener = listener;
        previewView.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);
        previewView.setScaleType(PreviewView.ScaleType.FIT_CENTER);
        prepareCameraProvider();
    }

    private void prepareCameraProvider() {
        providerFuture = ProcessCameraProvider.getInstance(activity);
        providerFuture.addListener(() -> {
            if (destroyed) return;
            try {
                cameraProvider = providerFuture.get();
                hasFrontCamera = cameraProvider.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA);
                hasBackCamera = cameraProvider.hasCamera(CameraSelector.DEFAULT_BACK_CAMERA);
                if (!hasFrontCamera && hasBackCamera) lensFacing = CameraSelector.LENS_FACING_BACK;
                listener.onCameraReady(hasFrontCamera || hasBackCamera, hasFrontCamera && hasBackCamera);
                if (userEnabled && foreground) bindUseCases();
            } catch (Exception unavailable) {
                listener.onError("当前设备无法初始化摄像头");
            }
        }, ContextCompat.getMainExecutor(activity));
    }

    public void enable() {
        if (destroyed || userEnabled) return;
        if (!gateway.connect()) {
            listener.onError("视觉会话不可用，请重新开启");
            return;
        }
        userEnabled = true;
        previewView.setVisibility(View.VISIBLE);
        if (foreground) bindUseCases();
        listener.onEnabledChanged(true);
    }

    public void disable() {
        if (!userEnabled && !destroyed) {
            previewView.setVisibility(View.GONE);
            return;
        }
        userEnabled = false;
        resetDocumentLocked(false);
        endActiveTurn();
        unbindUseCases();
        previewView.setVisibility(View.GONE);
        gateway.disconnect();
        listener.onEnabledChanged(false);
    }

    public void switchCamera() {
        if (destroyed || !userEnabled || documentMode || !(hasFrontCamera && hasBackCamera)) return;
        synchronized (frameStateLock) {
            lensFacing = lensFacing == CameraSelector.LENS_FACING_FRONT
                ? CameraSelector.LENS_FACING_BACK : CameraSelector.LENS_FACING_FRONT;
            preRoll.clear();
        }
        bindUseCases();
    }

    public void setForeground(boolean value) {
        if (destroyed) return;
        foreground = value;
        if (!value) {
            synchronized (frameStateLock) {
                preRoll.clear();
            }
            unbindUseCases();
        } else if (userEnabled) {
            bindUseCases();
        }
    }

    public void onSpeechPartial() {
        if (destroyed || !userEnabled || documentMode) return;
        synchronized (frameStateLock) {
            if (selector.getActiveTurnSeq() > 0) return;
            beginTurnLocked();
        }
    }

    public void onSpeechFinal() {
        if (destroyed || !userEnabled || documentMode) return;
        final long turnSeq;
        synchronized (frameStateLock) {
            long active = selector.getActiveTurnSeq();
            if (active < 1) active = beginTurnLocked();
            if (active < 1) return;
            turnSeq = selector.requestFinal();
        }
        pendingFinalTurnSeq = turnSeq;
        if (finalFrameTimeout != null) mainHandler.removeCallbacks(finalFrameTimeout);
        finalFrameTimeout = () -> finishTurn(turnSeq);
        mainHandler.postDelayed(finalFrameTimeout, FINAL_FRAME_TIMEOUT_MS);
    }

    private long beginTurnLocked() {
        long turnSeq = selector.beginTurn();
        if (gateway.startTurn(turnSeq) < 1) {
            selector.reset();
            preRoll.clear();
            return -1;
        }
        List<VisionPreRollBuffer.Frame> buffered = preRoll.drain(System.currentTimeMillis());
        for (VisionPreRollBuffer.Frame frame : buffered) {
            long queued = gateway.offerFrame(
                turnSeq,
                frame.getCapturedAtMs(),
                frame.getWidth(),
                frame.getHeight(),
                frame.getCamera(),
                frame.getJpeg()
            );
            if (queued > 0) {
                selector.recordPreRollFrame(frame.getSignature(), frame.getCapturedAtMs());
            }
        }
        return turnSeq;
    }

    public boolean isEnabled() { return userEnabled; }
    public boolean isFrontCamera() { return lensFacing == CameraSelector.LENS_FACING_FRONT; }
    public boolean isDocumentMode() { return documentMode; }
    public boolean isDocumentCaptureBusy() { return documentCaptureBusy; }

    /** Pauses temporal keyframes and prepares the rear camera without starting OCR traffic. */
    public boolean enterDocumentMode() {
        if (destroyed || !userEnabled || !foreground || documentMode) return false;
        endActiveTurn();
        synchronized (frameStateLock) {
            documentMode = true;
            documentCaptureBusy = false;
            activeDocumentSeq = 0;
            pendingDocument = null;
            if (hasBackCamera) lensFacing = CameraSelector.LENS_FACING_BACK;
            preRoll.clear();
        }
        bindUseCases();
        listener.onDocumentStateChanged(true, false);
        return true;
    }

    /** Captures into memory first; document.start is sent only after a valid JPEG exists. */
    public boolean captureDocument() {
        final ImageCapture capture;
        final String camera;
        synchronized (frameStateLock) {
            if (destroyed || !userEnabled || !foreground || !documentMode
                || documentCaptureBusy || imageCapture == null) return false;
            documentCaptureBusy = true;
            capture = imageCapture;
            camera = lensFacing == CameraSelector.LENS_FACING_FRONT ? "front" : "back";
        }
        listener.onDocumentStateChanged(true, true);
        capture.takePicture(analyzerExecutor, new ImageCapture.OnImageCapturedCallback() {
            @Override public void onCaptureSuccess(@NonNull ImageProxy image) {
                long capturedAtMs = System.currentTimeMillis();
                DocumentJpegEncoder.EncodedDocument encoded;
                try {
                    encoded = DocumentJpegEncoder.encode(image);
                } finally {
                    image.close();
                }
                mainHandler.post(() -> onDocumentEncoded(encoded, capturedAtMs, camera));
            }

            @Override public void onError(@NonNull ImageCaptureException exception) {
                mainHandler.post(() -> failLocalDocumentCapture(
                    "拍照失败，请保持手机稳定后重试"
                ));
            }
        });
        return true;
    }

    private void onDocumentEncoded(
        DocumentJpegEncoder.EncodedDocument encoded,
        long capturedAtMs,
        String camera
    ) {
        if (destroyed || !documentMode || !documentCaptureBusy) return;
        if (encoded == null) {
            failLocalDocumentCapture("文件画面无法读取，请重新拍摄");
            return;
        }
        long documentSeq = nextDocumentSeq == Long.MAX_VALUE ? 1 : nextDocumentSeq + 1;
        if (gateway.startDocument(documentSeq) < 1) {
            failLocalDocumentCapture("文件识别通道正忙，请稍后重试");
            return;
        }
        nextDocumentSeq = documentSeq;
        activeDocumentSeq = documentSeq;
        pendingDocumentCapturedAtMs = capturedAtMs;
        pendingDocumentCamera = camera;
        pendingDocument = encoded;
        listener.onDocumentWaitingForServer(documentSeq);
    }

    /** Called only for a matching, schema-valid document.started control message. */
    public void onDocumentStarted(long documentSeq) {
        if (destroyed || !documentMode || !documentCaptureBusy
            || documentSeq != activeDocumentSeq || pendingDocument == null) return;
        DocumentJpegEncoder.EncodedDocument encoded = pendingDocument;
        pendingDocument = null;
        long offered = gateway.offerDocumentFrame(
            documentSeq,
            pendingDocumentCapturedAtMs,
            encoded.getWidth(),
            encoded.getHeight(),
            pendingDocumentCamera,
            encoded.getBytes()
        );
        if (offered < 1) {
            failLocalDocumentCapture("文件照片上传失败，请重新开启视觉后重试");
        }
    }

    public void onDocumentReady(long documentSeq) {
        if (documentSeq != activeDocumentSeq) return;
        resetDocumentLocked(false);
        bindUseCases();
        listener.onDocumentStateChanged(false, false);
    }

    /** Restores ordinary preview/analysis after one recoverable server-side photo result. */
    public void onDocumentFailed(long documentSeq) {
        if (destroyed || documentSeq != activeDocumentSeq) return;
        resetDocumentLocked(false);
        bindUseCases();
        listener.onDocumentStateChanged(false, false);
    }

    public boolean cancelDocumentMode() {
        if (!documentMode || documentCaptureBusy) return false;
        resetDocumentLocked(false);
        bindUseCases();
        listener.onDocumentStateChanged(false, false);
        return true;
    }

    private void failLocalDocumentCapture(String message) {
        if (destroyed || !documentMode) return;
        synchronized (frameStateLock) {
            documentCaptureBusy = false;
            activeDocumentSeq = 0;
            pendingDocument = null;
        }
        listener.onDocumentStateChanged(true, false);
        listener.onError(message);
    }

    private void resetDocumentLocked(boolean preserveMode) {
        synchronized (frameStateLock) {
            documentMode = preserveMode;
            documentCaptureBusy = false;
            activeDocumentSeq = 0;
            pendingDocument = null;
            pendingDocumentCapturedAtMs = 0;
            pendingDocumentCamera = "back";
        }
    }

    @SuppressLint("MissingPermission") // Activity grants CAMERA before enable().
    private void bindUseCases() {
        if (destroyed || !userEnabled || !foreground || cameraProvider == null
            || ContextCompat.checkSelfPermission(activity, Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            return;
        }
        CameraSelector cameraSelector = new CameraSelector.Builder()
            .requireLensFacing(lensFacing)
            .build();
        if ((lensFacing == CameraSelector.LENS_FACING_FRONT && !hasFrontCamera)
            || (lensFacing == CameraSelector.LENS_FACING_BACK && !hasBackCamera)) {
            listener.onError("所选摄像头不可用");
            return;
        }
        try {
            if (imageAnalysis != null) imageAnalysis.clearAnalyzer();
            imageAnalysis = null;
            imageCapture = null;
            cameraProvider.unbindAll();
            Preview preview = new Preview.Builder().build();
            preview.setSurfaceProvider(previewView.getSurfaceProvider());
            if (documentMode) {
                imageAnalysis = null;
                imageCapture = new ImageCapture.Builder()
                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MAXIMIZE_QUALITY)
                    .setTargetResolution(new Size(2048, 1536))
                    .build();
                cameraProvider.bindToLifecycle(activity, cameraSelector, preview, imageCapture);
            } else {
                imageCapture = null;
                imageAnalysis = new ImageAnalysis.Builder()
                    .setTargetResolution(new Size(640, 480))
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build();
                imageAnalysis.setAnalyzer(analyzerExecutor, this::analyze);
                cameraProvider.bindToLifecycle(activity, cameraSelector, preview, imageAnalysis);
            }
        } catch (RuntimeException unavailable) {
            unbindUseCases();
            listener.onError("无法打开摄像头，语音对话仍可继续");
        }
    }

    private void analyze(ImageProxy image) {
        try {
            if (destroyed || !userEnabled || !foreground || documentMode
                || image.getPlanes().length < 1) return;
            long elapsed = SystemClock.elapsedRealtime();
            final long observedTurnSeq;
            final String camera;
            synchronized (frameStateLock) {
                observedTurnSeq = selector.getActiveTurnSeq();
                camera = lensFacing == CameraSelector.LENS_FACING_FRONT ? "front" : "back";
            }
            if (elapsed - lastAnalyzedElapsedMs < ANALYSIS_INTERVAL_MS) return;
            lastAnalyzedElapsedMs = elapsed;
            ImageProxy.PlaneProxy luma = image.getPlanes()[0];
            ByteBuffer buffer = luma.getBuffer();
            byte[] signature = LumaSignatureSampler.sample(
                buffer,
                image.getWidth(),
                image.getHeight(),
                luma.getRowStride(),
                luma.getPixelStride()
            );
            long capturedAtMs = System.currentTimeMillis();
            YuvJpegEncoder.EncodedJpeg jpeg = YuvJpegEncoder.encode(image);
            if (jpeg == null) return;
            VisionFrameSelector.Selection selection;
            long queuedFrame;
            synchronized (frameStateLock) {
                // Encoding runs off the main thread. Re-check documentMode because the user may
                // have entered explicit document capture while this ordinary frame was encoding.
                if (destroyed || !userEnabled || !foreground || documentMode) return;
                long activeTurnSeq = selector.getActiveTurnSeq();
                String currentCamera = lensFacing == CameraSelector.LENS_FACING_FRONT
                    ? "front" : "back";
                if (!camera.equals(currentCamera)
                    || (observedTurnSeq > 0 && activeTurnSeq != observedTurnSeq)) return;
                if (activeTurnSeq < 1) {
                    preRoll.add(new VisionPreRollBuffer.Frame(
                        capturedAtMs,
                        jpeg.getWidth(),
                        jpeg.getHeight(),
                        camera,
                        signature,
                        jpeg.getBytes()
                    ));
                    return;
                }
                selection = selector.evaluate(signature, capturedAtMs);
                if (!selection.isSelected()) return;
                queuedFrame = selection.isFinal()
                    ? gateway.offerFinalFrame(
                        selection.getTurnSeq(),
                        capturedAtMs,
                        jpeg.getWidth(),
                        jpeg.getHeight(),
                        camera,
                        jpeg.getBytes()
                    )
                    : gateway.offerFrame(
                        selection.getTurnSeq(),
                        capturedAtMs,
                        jpeg.getWidth(),
                        jpeg.getHeight(),
                        camera,
                        jpeg.getBytes()
                    );
            }
            if (selection.isFinal() && queuedFrame > 0) {
                mainHandler.post(() -> finishTurn(selection.getTurnSeq()));
            }
        } catch (RuntimeException invalidFrame) {
            // Malformed vendor camera buffers are dropped without affecting the audio RTC session.
        } finally {
            image.close();
        }
    }

    private void finishTurn(long turnSeq) {
        if (turnSeq < 1 || pendingFinalTurnSeq != turnSeq) return;
        pendingFinalTurnSeq = 0;
        if (finalFrameTimeout != null) {
            mainHandler.removeCallbacks(finalFrameTimeout);
            finalFrameTimeout = null;
        }
        synchronized (frameStateLock) {
            selector.completeWithoutFrame(turnSeq);
            gateway.endTurn(turnSeq);
        }
    }

    private void endActiveTurn() {
        final long active;
        synchronized (frameStateLock) {
            long selected = selector.getActiveTurnSeq();
            // evaluate(final) may already have sealed the selector while the
            // final JPEG is still encoding.  The gateway remains active until
            // finishTurn runs, so document mode must close that pending turn
            // as well instead of leaving document.start permanently busy.
            active = selected > 0 ? selected : pendingFinalTurnSeq;
            selector.reset();
            preRoll.clear();
            if (active > 0) gateway.endTurn(active);
        }
        pendingFinalTurnSeq = 0;
        if (finalFrameTimeout != null) {
            mainHandler.removeCallbacks(finalFrameTimeout);
            finalFrameTimeout = null;
        }
    }

    private void unbindUseCases() {
        synchronized (frameStateLock) {
            preRoll.clear();
        }
        if (imageAnalysis != null) {
            imageAnalysis.clearAnalyzer();
            imageAnalysis = null;
        }
        imageCapture = null;
        if (cameraProvider != null) cameraProvider.unbindAll();
    }

    public void destroy() {
        if (destroyed) return;
        disable();
        destroyed = true;
        foreground = false;
        if (providerFuture != null && !providerFuture.isDone()) providerFuture.cancel(true);
        analyzerExecutor.shutdownNow();
        mainHandler.removeCallbacksAndMessages(null);
        gateway.destroy();
    }

    public interface Listener {
        void onCameraReady(boolean available, boolean canSwitch);
        void onEnabledChanged(boolean enabled);
        void onError(String message);
        default void onDocumentStateChanged(boolean documentMode, boolean busy) {}
        default void onDocumentWaitingForServer(long documentSeq) {}
    }
}
