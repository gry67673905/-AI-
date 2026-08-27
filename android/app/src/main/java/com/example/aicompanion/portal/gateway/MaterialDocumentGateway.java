package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.business.PortalCommandPolicy;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.Role;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URLDecoder;
import java.util.Collections;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import okhttp3.Call;
import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.ResponseBody;

/** Authenticated fixed-path binary transport for generated Word documents. */
public final class MaterialDocumentGateway {
    public static final String DOCX_MIME =
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
    private static final Pattern SHA256 = Pattern.compile("[0-9a-fA-F]{64}");
    private static final Pattern FILENAME_STAR = Pattern.compile(
        "(?i)(?:^|;)\\s*filename\\*\\s*=\\s*UTF-8''([^;]+)"
    );
    private static final Pattern FILENAME = Pattern.compile(
        "(?i)(?:^|;)\\s*filename\\s*=\\s*(?:\"([^\"]*)\"|([^;]*))"
    );

    private final NativeApiClient api;
    private final File cacheRoot;
    private final OkHttpClient binaryClient;

    public MaterialDocumentGateway(NativeApiClient api, File cacheRoot) {
        this.api = api;
        this.cacheRoot = cacheRoot;
        this.binaryClient = api.getHttpClient().newBuilder()
            .followRedirects(false)
            .followSslRedirects(false)
            .readTimeout(60, TimeUnit.SECONDS)
            .callTimeout(75, TimeUnit.SECONDS)
            .retryOnConnectionFailure(false)
            .build();
    }

    public void download(String generationId, GatewayCallback<CachedDocument> callback) {
        if (!PortalCommandPolicy.isSafeResourceId(generationId)) {
            callback.onError(new ApiFailure(400, "invalid_generation_id", "生成任务编号无效"));
            return;
        }
        SecureSessionStore.Snapshot snapshot = api.getSessionStore().load();
        if (!snapshot.isAuthenticated() || snapshot.getProfile().getRole() != Role.CITIZEN
            || snapshot.getProfile().getId().isEmpty()) {
            callback.onError(new ApiFailure(401, "authentication_required", "请先登录"));
            return;
        }
        String ownerId = snapshot.getProfile().getId();
        Request request = new Request.Builder()
            .url(api.buildUrl(
                new String[]{"material-documents", generationId, "download"},
                Collections.emptyMap()
            ))
            .header("Accept", DOCX_MIME)
            .header("Authorization", snapshot.getSecrets().getTokenType() + " "
                + snapshot.getSecrets().getAccessToken())
            .get()
            .build();
        binaryClient.newCall(request).enqueue(new okhttp3.Callback() {
            @Override public void onFailure(Call call, IOException error) {
                callback.onError(new ApiFailure(0, call.isCanceled() ? "cancelled" : "network_error",
                    call.isCanceled() ? "下载已取消" : "无法下载生成的 Word 文件"));
            }

            @Override public void onResponse(Call call, Response response) {
                File target = null;
                try (ResponseBody body = response.body()) {
                    if (!response.isSuccessful()) {
                        String raw = body == null ? "" : body.string();
                        callback.onError(NativeApiClient.parseFailure(response.code(), raw));
                        return;
                    }
                    String mime = normalizedMime(response.header("Content-Type", ""));
                    if (!DOCX_MIME.equals(mime)) {
                        callback.onError(new ApiFailure(502, "invalid_document_mime",
                            "服务端返回的文件类型不是 DOCX"));
                        return;
                    }
                    String expectedSha = response.header("X-Content-SHA256", "").trim();
                    if (!SHA256.matcher(expectedSha).matches()) {
                        callback.onError(new ApiFailure(502, "missing_document_hash",
                            "服务端未提供有效的文件校验值"));
                        return;
                    }
                    long declared = body == null ? 0 : body.contentLength();
                    if (declared == 0 || declared > MaterialDocumentValidator.MAX_FILE_BYTES) {
                        callback.onError(new ApiFailure(502,
                            declared > MaterialDocumentValidator.MAX_FILE_BYTES
                                ? "document_too_large" : "empty_document",
                            declared > MaterialDocumentValidator.MAX_FILE_BYTES
                                ? "生成的 Word 文件超过 10MB" : "生成的 Word 文件为空"));
                        return;
                    }
                    File directory = new File(cacheRoot, "generated-material-documents");
                    if ((!directory.isDirectory() && !directory.mkdirs()) || !directory.isDirectory()) {
                        callback.onError(new ApiFailure(0, "cache_unavailable", "无法创建安全下载缓存"));
                        return;
                    }
                    target = new File(directory, generationId + "-" + UUID.randomUUID() + ".docx");
                    if (!isChild(directory, target)) {
                        callback.onError(new ApiFailure(0, "cache_unavailable", "安全下载路径无效"));
                        return;
                    }
                    try (InputStream input = body.byteStream(); FileOutputStream output = new FileOutputStream(target)) {
                        byte[] buffer = new byte[8192];
                        long total = 0;
                        int count;
                        while ((count = input.read(buffer)) != -1) {
                            total += count;
                            if (total > MaterialDocumentValidator.MAX_FILE_BYTES) {
                                throw new SizeLimitException();
                            }
                            output.write(buffer, 0, count);
                        }
                        output.flush();
                        output.getFD().sync();
                    }
                    MaterialDocumentValidator.Result validation =
                        MaterialDocumentValidator.validate(target, expectedSha);
                    if (!validation.isValid()) {
                        deleteQuietly(target);
                        callback.onError(new ApiFailure(502, validation.getCode(), validation.getMessage()));
                        return;
                    }
                    SecureSessionStore.Snapshot current = api.getSessionStore().load();
                    if (!current.isAuthenticated() || current.getProfile().getRole() != Role.CITIZEN
                        || !ownerId.equals(current.getProfile().getId())) {
                        deleteQuietly(target);
                        callback.onError(new ApiFailure(401, "session_changed",
                            "登录身份已变化，请重新下载"));
                        return;
                    }
                    String displayName = safeFilename(
                        response.header("Content-Disposition", ""), generationId
                    );
                    callback.onSuccess(new CachedDocument(
                        target, displayName, validation.getSha256(), validation.getSize()
                    ));
                } catch (SizeLimitException tooLarge) {
                    deleteQuietly(target);
                    callback.onError(new ApiFailure(502, "document_too_large", "生成的 Word 文件超过 10MB"));
                } catch (IOException error) {
                    deleteQuietly(target);
                    callback.onError(new ApiFailure(0, "document_download_failed", "保存下载缓存失败"));
                }
            }
        });
    }

    public static String safeFilename(String contentDisposition, String generationId) {
        String raw = "";
        Matcher encoded = FILENAME_STAR.matcher(contentDisposition == null ? "" : contentDisposition);
        if (encoded.find()) {
            try {
                raw = URLDecoder.decode(encoded.group(1).trim(), "UTF-8");
            } catch (Exception ignored) {}
        }
        if (raw.isEmpty()) {
            Matcher plain = FILENAME.matcher(contentDisposition == null ? "" : contentDisposition);
            if (plain.find()) raw = plain.group(1) != null ? plain.group(1) : plain.group(2);
        }
        raw = raw == null ? "" : raw.trim();
        raw = raw.replace('\\', '/');
        int slash = raw.lastIndexOf('/');
        if (slash >= 0) raw = raw.substring(slash + 1);
        raw = raw.replaceAll("[\\x00-\\x1f\\x7f:*?\"<>|]", "_").trim();
        if (raw.isEmpty()) raw = "material-" + generationId + ".docx";
        if (!raw.toLowerCase(Locale.ROOT).endsWith(".docx")) raw += ".docx";
        if (raw.length() > 120) raw = raw.substring(0, 115) + ".docx";
        return raw;
    }

    private static String normalizedMime(String raw) {
        String value = raw == null ? "" : raw.trim().toLowerCase(Locale.ROOT);
        int separator = value.indexOf(';');
        return separator >= 0 ? value.substring(0, separator).trim() : value;
    }

    private static boolean isChild(File parent, File child) throws IOException {
        String root = parent.getCanonicalPath() + File.separator;
        return child.getCanonicalPath().startsWith(root);
    }

    public static void deleteQuietly(File file) {
        if (file != null && file.exists()) {
            // Best effort only: files live in app-private cache and are cleaned again on the next launch.
            file.delete();
        }
    }

    public static final class CachedDocument {
        private final File file;
        private final String displayName;
        private final String sha256;
        private final long size;

        CachedDocument(File file, String displayName, String sha256, long size) {
            this.file = file;
            this.displayName = displayName;
            this.sha256 = sha256;
            this.size = size;
        }

        public File getFile() { return file; }
        public String getDisplayName() { return displayName; }
        public String getSha256() { return sha256; }
        public long getSize() { return size; }
    }

    private static final class SizeLimitException extends IOException {}
}
