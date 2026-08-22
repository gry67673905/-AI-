package com.example.aicompanion.portal.boundary;

import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.webkit.MimeTypeMap;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;

import com.example.aicompanion.portal.business.PortalCommandPolicy;
import com.example.aicompanion.portal.model.PortalContract.SelectedDocument;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** Android Storage Access Framework boundary. Selected content never becomes a WebView URI. */
public final class DocumentPickerBoundary {
    private static final long MAX_SIZE = 10L * 1024L * 1024L;
    private static final Set<String> MATERIAL_TYPES = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
        "application/pdf", "image/jpeg", "image/png"
    )));
    private static final Set<String> KNOWLEDGE_TYPES = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/x-markdown"
    )));

    public interface Listener {
        void onSelected(SelectedDocument document);
        void onCancelled();
        void onError(String code, String message);
    }

    private final AppCompatActivity activity;
    private final Listener listener;
    private final ActivityResultLauncher<String[]> launcher;
    private PendingRequest pending;

    public DocumentPickerBoundary(AppCompatActivity activity, Listener listener) {
        this.activity = activity;
        this.listener = listener;
        launcher = activity.registerForActivityResult(new ActivityResultContracts.OpenDocument(), this::handleResult);
    }

    public void choose(String rawRequest, Role role) {
        try {
            JsonElement parsed = JsonParser.parseString(rawRequest == null ? "" : rawRequest);
            if (!parsed.isJsonObject()) throw new IllegalArgumentException("文件请求必须是 JSON 对象");
            JsonObject object = parsed.getAsJsonObject();
            String purpose = string(object, "purpose").toLowerCase(Locale.ROOT);
            if ("material".equals(purpose)) {
                if (role != Role.CITIZEN) throw new IllegalArgumentException("只有群众账号可以上传办件材料");
                String applicationId = string(object, "application_id");
                String requirementId = string(object, "requirement_id");
                if (!PortalCommandPolicy.isSafeResourceId(applicationId)
                    || !PortalCommandPolicy.isSafeResourceId(requirementId)) {
                    throw new IllegalArgumentException("办件或材料要求编号无效");
                }
                pending = new PendingRequest(purpose, applicationId, requirementId, MATERIAL_TYPES);
            } else if ("knowledge".equals(purpose)) {
                if (role != Role.ADMIN) throw new IllegalArgumentException("只有管理员可以上传知识资料");
                pending = new PendingRequest(purpose, "", "", KNOWLEDGE_TYPES);
            } else {
                throw new IllegalArgumentException("不支持的文件用途");
            }
            launcher.launch(pending.mimeTypes.toArray(new String[0]));
        } catch (RuntimeException error) {
            pending = null;
            listener.onError("invalid_document_request", error.getMessage());
        }
    }

    private void handleResult(Uri uri) {
        PendingRequest request = pending;
        pending = null;
        if (uri == null || request == null) {
            listener.onCancelled();
            return;
        }
        if (!"content".equalsIgnoreCase(uri.getScheme())) {
            listener.onError("invalid_document_uri", "文件必须来自 Android 安全文档提供方");
            return;
        }
        String mimeType = normalizedMime(uri);
        if (!request.mimeTypes.contains(mimeType)) {
            listener.onError("unsupported_file_type", "仅支持当前业务规定的演示材料格式");
            return;
        }
        Metadata metadata = metadata(uri);
        if (metadata.size < 0) {
            listener.onError("unknown_file_size", "无法确认文件大小，请重新选择");
            return;
        }
        if (metadata.size == 0) {
            listener.onError("empty_file", "不能上传空文件");
            return;
        }
        if (metadata.size > MAX_SIZE) {
            listener.onError("file_too_large", "单个文件不能超过 10MB");
            return;
        }
        listener.onSelected(new SelectedDocument(
            request.purpose,
            uri.toString(),
            metadata.name,
            mimeType,
            metadata.size,
            request.applicationId,
            request.requirementId
        ));
    }

    private String normalizedMime(Uri uri) {
        String mime = activity.getContentResolver().getType(uri);
        if (mime != null) return mime.toLowerCase(Locale.ROOT);
        String extension = MimeTypeMap.getFileExtensionFromUrl(uri.toString());
        String inferred = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension);
        return inferred == null ? "" : inferred.toLowerCase(Locale.ROOT);
    }

    private Metadata metadata(Uri uri) {
        String name = "document";
        long size = -1;
        try (Cursor cursor = activity.getContentResolver().query(
            uri,
            new String[]{OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE},
            null,
            null,
            null
        )) {
            if (cursor != null && cursor.moveToFirst()) {
                int nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                int sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE);
                if (nameIndex >= 0 && !cursor.isNull(nameIndex)) name = cursor.getString(nameIndex);
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) size = cursor.getLong(sizeIndex);
            }
        } catch (RuntimeException ignored) {}
        name = name.replaceAll("[\\r\\n\\t]", "_");
        if (name.length() > 160) name = name.substring(name.length() - 160);
        return new Metadata(name, size);
    }

    private static String string(JsonObject object, String key) {
        JsonElement value = object.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()
            ? value.getAsString().trim() : "";
    }

    private static final class PendingRequest {
        private final String purpose;
        private final String applicationId;
        private final String requirementId;
        private final Set<String> mimeTypes;

        private PendingRequest(String purpose, String applicationId, String requirementId, Set<String> mimeTypes) {
            this.purpose = purpose;
            this.applicationId = applicationId;
            this.requirementId = requirementId;
            this.mimeTypes = mimeTypes;
        }
    }

    private static final class Metadata {
        private final String name;
        private final long size;
        private Metadata(String name, long size) { this.name = name; this.size = size; }
    }
}
