package com.example.aicompanion.portal.gateway;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipException;
import java.util.zip.ZipFile;

/** Pure validation for a downloaded editable DOCX before it reaches a document provider. */
public final class MaterialDocumentValidator {
    public static final long MAX_FILE_BYTES = 10L * 1024L * 1024L;
    private static final long MAX_EXPANDED_BYTES = 50L * 1024L * 1024L;
    private static final int MAX_ZIP_ENTRIES = 2_000;
    private static final Pattern SHA256 = Pattern.compile("[0-9a-fA-F]{64}");
    private static final Pattern EXTERNAL_RELATIONSHIP = Pattern.compile(
        "targetmode\\s*=\\s*[\"']external[\"']"
    );
    private static final Pattern ALT_CHUNK = Pattern.compile(
        "<(?:[a-z_][a-z0-9_.-]*:)?altchunk\\b"
    );
    private static final int MAX_RELATIONSHIP_XML_BYTES = 1024 * 1024;
    private static final int MAX_DOCUMENT_XML_BYTES = 10 * 1024 * 1024;

    private MaterialDocumentValidator() {}

    public static Result validate(File file, String expectedSha256) {
        if (file == null || !file.isFile()) return Result.invalid("download_missing", "下载文件不存在");
        long fileSize = file.length();
        if (fileSize <= 0) return Result.invalid("empty_document", "生成的 Word 文件为空");
        if (fileSize > MAX_FILE_BYTES) return Result.invalid("document_too_large", "生成的 Word 文件超过 10MB");
        if (expectedSha256 == null || !SHA256.matcher(expectedSha256.trim()).matches()) {
            return Result.invalid("missing_document_hash", "服务端未提供有效的文件校验值");
        }

        final String actualSha;
        try {
            actualSha = sha256(file);
        } catch (IOException error) {
            return Result.invalid("document_read_failed", "无法读取生成的 Word 文件");
        }
        if (!MessageDigest.isEqual(
            actualSha.getBytes(StandardCharsets.US_ASCII),
            expectedSha256.trim().toLowerCase(Locale.ROOT).getBytes(StandardCharsets.US_ASCII)
        )) {
            return Result.invalid("document_hash_mismatch", "生成的 Word 文件校验失败");
        }

        boolean hasContentTypes = false;
        boolean hasDocument = false;
        int entryCount = 0;
        long expandedBytes = 0;
        Set<String> names = new HashSet<>();
        try (ZipFile zip = new ZipFile(file)) {
            Enumeration<? extends ZipEntry> entries = zip.entries();
            while (entries.hasMoreElements()) {
                ZipEntry entry = entries.nextElement();
                if (++entryCount > MAX_ZIP_ENTRIES) {
                    return Result.invalid("invalid_docx_package", "Word 文件包含过多内部条目");
                }
                String name = entry.getName();
                if (!isSafeEntryName(name) || !names.add(name)) {
                    return Result.invalid("invalid_docx_package", "Word 文件内部路径无效");
                }
                String lower = name.toLowerCase(Locale.ROOT);
                if (lower.contains("vbaproject") || lower.startsWith("word/embeddings/")
                    || lower.startsWith("word/altchunk") || lower.endsWith(".bin")) {
                    return Result.invalid("unsafe_docx_content", "Word 文件包含不允许的活动内容");
                }
                if (entry.isDirectory()) continue;
                try (InputStream input = zip.getInputStream(entry)) {
                    byte[] buffer = new byte[8192];
                    int count;
                    boolean relationshipXml = lower.endsWith(".rels");
                    boolean documentXml = "word/document.xml".equals(lower);
                    java.io.ByteArrayOutputStream inspectedXml = relationshipXml || documentXml
                        ? new java.io.ByteArrayOutputStream() : null;
                    int inspectedLimit = relationshipXml
                        ? MAX_RELATIONSHIP_XML_BYTES : MAX_DOCUMENT_XML_BYTES;
                    while ((count = input.read(buffer)) != -1) {
                        expandedBytes += count;
                        if (expandedBytes > MAX_EXPANDED_BYTES) {
                            return Result.invalid("invalid_docx_package", "Word 文件解压后大小异常");
                        }
                        if (inspectedXml != null) {
                            if (inspectedXml.size() + count > inspectedLimit) {
                                return Result.invalid("invalid_docx_package", "Word 文件内部 XML 大小异常");
                            }
                            inspectedXml.write(buffer, 0, count);
                        }
                    }
                    if (inspectedXml != null) {
                        String xml = new String(inspectedXml.toByteArray(), StandardCharsets.UTF_8)
                            .toLowerCase(Locale.ROOT);
                        if (relationshipXml && EXTERNAL_RELATIONSHIP.matcher(xml).find()) {
                            return Result.invalid("unsafe_docx_content", "Word 文件包含外部资源关系");
                        }
                        if (documentXml && ALT_CHUNK.matcher(xml).find()) {
                            return Result.invalid("unsafe_docx_content", "Word 文件包含不允许的外部内容片段");
                        }
                    }
                }
                if ("[Content_Types].xml".equals(name)) hasContentTypes = true;
                if ("word/document.xml".equals(name)) hasDocument = true;
            }
        } catch (ZipException invalidZip) {
            return Result.invalid("invalid_docx_package", "下载内容不是有效的 DOCX 文件");
        } catch (IOException error) {
            return Result.invalid("document_read_failed", "无法验证生成的 Word 文件");
        }
        if (!hasContentTypes || !hasDocument) {
            return Result.invalid("invalid_docx_package", "DOCX 缺少必要的 Word 文档结构");
        }
        return Result.valid(actualSha, fileSize);
    }

    private static boolean isSafeEntryName(String name) {
        if (name == null || name.isEmpty() || name.startsWith("/") || name.startsWith("\\")
            || name.indexOf('\\') >= 0 || name.indexOf('\0') >= 0 || name.indexOf(':') >= 0) return false;
        String[] parts = name.split("/", -1);
        for (String part : parts) {
            if ("..".equals(part) || ".".equals(part)) return false;
        }
        return true;
    }

    static String sha256(File file) throws IOException {
        final MessageDigest digest;
        try {
            digest = MessageDigest.getInstance("SHA-256");
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 unavailable", impossible);
        }
        try (InputStream input = new FileInputStream(file)) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        StringBuilder output = new StringBuilder(64);
        for (byte item : digest.digest()) output.append(String.format(Locale.ROOT, "%02x", item & 0xff));
        return output.toString();
    }

    public static final class Result {
        private final boolean valid;
        private final String code;
        private final String message;
        private final String sha256;
        private final long size;

        private Result(boolean valid, String code, String message, String sha256, long size) {
            this.valid = valid;
            this.code = code;
            this.message = message;
            this.sha256 = sha256;
            this.size = size;
        }

        static Result valid(String sha256, long size) {
            return new Result(true, "", "", sha256, size);
        }

        static Result invalid(String code, String message) {
            return new Result(false, code, message, "", 0);
        }

        public boolean isValid() { return valid; }
        public String getCode() { return code; }
        public String getMessage() { return message; }
        public String getSha256() { return sha256; }
        public long getSize() { return size; }
    }
}
