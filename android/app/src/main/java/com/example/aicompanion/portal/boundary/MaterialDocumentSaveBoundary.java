package com.example.aicompanion.portal.boundary;

import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;

import com.example.aicompanion.portal.business.PortalCommandPolicy;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.MaterialDocumentGateway;
import com.example.aicompanion.portal.gateway.MaterialDocumentValidator;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Role;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** Narrow SAF boundary: WebView supplies only an opaque generation id, never a URL or path. */
public final class MaterialDocumentSaveBoundary {
    private static final String STATE_PATH = "material_document.pending_path";
    private static final String STATE_NAME = "material_document.pending_name";
    private static final String STATE_SHA = "material_document.pending_sha";
    private static final long STALE_CACHE_AGE_MS = 24L * 60L * 60L * 1000L;

    public interface Listener {
        void onPreparing();
        void onSaved(String displayName, boolean opened);
        void onCancelled();
        void onAuthenticationRequired(ApiFailure error);
        void onError(String code, String message);
    }

    private final AppCompatActivity activity;
    private final MaterialDocumentGateway gateway;
    private final Listener listener;
    private final ActivityResultLauncher<String> createDocument;
    private PendingDocument pending;
    private boolean downloadInFlight;
    private boolean destroyed;

    public MaterialDocumentSaveBoundary(
        AppCompatActivity activity,
        MaterialDocumentGateway gateway,
        Bundle savedState,
        Listener listener
    ) {
        this.activity = activity;
        this.gateway = gateway;
        this.listener = listener;
        this.createDocument = activity.registerForActivityResult(
            new ActivityResultContracts.CreateDocument(MaterialDocumentGateway.DOCX_MIME),
            this::handleDestination
        );
        restore(savedState);
        cleanStaleCache();
    }

    public void save(String generationId, Role role) {
        if (destroyed) return;
        if (role != Role.CITIZEN) {
            listener.onError("forbidden", "只有办件所属群众账号可以保存生成材料");
            return;
        }
        if (!PortalCommandPolicy.isSafeResourceId(generationId)) {
            listener.onError("invalid_generation_id", "生成任务编号无效");
            return;
        }
        if (downloadInFlight || pending != null) {
            listener.onError("document_save_in_progress", "已有 Word 文件正在下载或等待保存");
            return;
        }
        downloadInFlight = true;
        listener.onPreparing();
        gateway.download(generationId, new GatewayCallback<MaterialDocumentGateway.CachedDocument>() {
            @Override public void onSuccess(MaterialDocumentGateway.CachedDocument document) {
                activity.runOnUiThread(() -> {
                    downloadInFlight = false;
                    if (destroyed) {
                        MaterialDocumentGateway.deleteQuietly(document.getFile());
                        return;
                    }
                    pending = new PendingDocument(
                        document.getFile(), document.getDisplayName(), document.getSha256()
                    );
                    try {
                        createDocument.launch(document.getDisplayName());
                    } catch (RuntimeException error) {
                        clearPending();
                        listener.onError("document_provider_unavailable", "无法打开 Android 文件保存界面");
                    }
                });
            }

            @Override public void onError(ApiFailure error) {
                activity.runOnUiThread(() -> {
                    downloadInFlight = false;
                    if (destroyed) return;
                    if (error.getStatusCode() == 401) listener.onAuthenticationRequired(error);
                    else listener.onError(error.getCode(), error.getMessage());
                });
            }
        });
    }

    public void saveState(Bundle output) {
        if (output == null || pending == null) return;
        output.putString(STATE_PATH, pending.file.getAbsolutePath());
        output.putString(STATE_NAME, pending.displayName);
        output.putString(STATE_SHA, pending.sha256);
    }

    public void destroy(boolean preservePendingForRecreation) {
        destroyed = true;
        if (!preservePendingForRecreation) clearPending();
    }

    private void handleDestination(Uri uri) {
        PendingDocument document = pending;
        if (uri == null || document == null) {
            clearPending();
            listener.onCancelled();
            return;
        }
        if (!"content".equalsIgnoreCase(uri.getScheme())) {
            clearPending();
            listener.onError("invalid_document_destination", "必须使用 Android 安全文档提供方保存文件");
            return;
        }
        try (InputStream input = new FileInputStream(document.file);
             OutputStream output = activity.getContentResolver().openOutputStream(uri, "w")) {
            if (output == null) throw new IOException("Missing destination stream");
            byte[] buffer = new byte[8192];
            long written = 0;
            int count;
            while ((count = input.read(buffer)) != -1) {
                written += count;
                if (written > MaterialDocumentValidator.MAX_FILE_BYTES) {
                    throw new IOException("Document exceeded client limit");
                }
                output.write(buffer, 0, count);
            }
            output.flush();
            if (written != document.file.length()) throw new IOException("Truncated destination");
        } catch (IOException | SecurityException error) {
            clearPending();
            listener.onError("document_save_failed", "无法写入所选保存位置");
            return;
        }
        String displayName = document.displayName;
        clearPending();
        boolean opened = openDocument(uri);
        listener.onSaved(displayName, opened);
    }

    private boolean openDocument(Uri uri) {
        Intent view = new Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, MaterialDocumentGateway.DOCX_MIME)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        view.setClipData(ClipData.newRawUri("generated-material", uri));
        try {
            activity.startActivity(view);
            return true;
        } catch (ActivityNotFoundException | SecurityException unavailable) {
            return false;
        }
    }

    private void restore(Bundle state) {
        if (state == null) return;
        String path = state.getString(STATE_PATH, "");
        String name = state.getString(STATE_NAME, "");
        String sha = state.getString(STATE_SHA, "");
        if (path.isEmpty() || name.isEmpty()) return;
        File candidate = new File(path);
        try {
            File expectedParent = new File(activity.getCacheDir(), "generated-material-documents");
            if (!candidate.getCanonicalPath().startsWith(expectedParent.getCanonicalPath() + File.separator)) return;
        } catch (IOException invalidPath) {
            return;
        }
        MaterialDocumentValidator.Result validation = MaterialDocumentValidator.validate(candidate, sha);
        if (!validation.isValid()) {
            MaterialDocumentGateway.deleteQuietly(candidate);
            return;
        }
        pending = new PendingDocument(candidate, MaterialDocumentGateway.safeFilename(
            "attachment; filename=\"" + name.replace("\"", "") + "\"", "restored"
        ), validation.getSha256());
    }

    private void cleanStaleCache() {
        File directory = new File(activity.getCacheDir(), "generated-material-documents");
        File[] files = directory.listFiles();
        if (files == null) return;
        long cutoff = System.currentTimeMillis() - STALE_CACHE_AGE_MS;
        for (File file : files) {
            if (pending != null && pending.file.equals(file)) continue;
            if (file.isFile() && file.lastModified() < cutoff) MaterialDocumentGateway.deleteQuietly(file);
        }
    }

    private void clearPending() {
        if (pending != null) MaterialDocumentGateway.deleteQuietly(pending.file);
        pending = null;
    }

    private static final class PendingDocument {
        private final File file;
        private final String displayName;
        private final String sha256;

        private PendingDocument(File file, String displayName, String sha256) {
            this.file = file;
            this.displayName = displayName;
            this.sha256 = sha256;
        }
    }
}
