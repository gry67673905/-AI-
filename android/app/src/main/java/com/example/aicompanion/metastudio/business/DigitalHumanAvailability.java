package com.example.aicompanion.metastudio.business;

import android.content.Context;
import android.os.Build;

import com.example.aicompanion.BuildConfig;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/** Runtime hard gate. A wrapper without the verified proprietary SDK is never treated as enabled. */
public final class DigitalHumanAvailability {
    private static final String SDK_ROOT = "metastudio/sdk/";

    public Decision check(Context context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return Decision.unavailable("unsupported_android", "智能交互数字人需要 Android 10 或更高版本");
        }
        if (!BuildConfig.METASTUDIO_SDK_READY) {
            return Decision.unavailable("sdk_not_bundled", "MetaStudio Web SDK 5.0.6 尚未通过完整性校验并随应用打包");
        }
        try {
            if (!nonEmpty(context, SDK_ROOT + "HwICSUiSdk.js")
                || !nonEmpty(context, SDK_ROOT + "HwICSUiSdk.css")) {
                return Decision.unavailable("sdk_incomplete", "MetaStudio Web SDK 文件不完整");
            }
            try (InputStream input = context.getAssets().open(SDK_ROOT + "sdk-integrity.json");
                 InputStreamReader reader = new InputStreamReader(input, StandardCharsets.UTF_8)) {
                JsonElement parsed = JsonParser.parseReader(reader);
                if (!parsed.isJsonObject()) throw new IllegalStateException("invalid marker");
                JsonObject marker = parsed.getAsJsonObject();
                boolean verified = marker.has("cms_verified")
                    && marker.get("cms_verified").isJsonPrimitive()
                    && marker.get("cms_verified").getAsBoolean();
                String version = marker.has("version") ? marker.get("version").getAsString() : "";
                String archiveHash = marker.has("archive_sha256")
                    ? marker.get("archive_sha256").getAsString() : "";
                if (!verified || !BuildConfig.METASTUDIO_SDK_VERSION.equals(version)
                    || !BuildConfig.METASTUDIO_SDK_ARCHIVE_SHA256.equals(archiveHash)) {
                    return Decision.unavailable("sdk_unverified", "MetaStudio Web SDK 完整性标记无效");
                }
            }
        } catch (Exception invalidAssets) {
            return Decision.unavailable("sdk_unreadable", "无法读取已校验的 MetaStudio Web SDK");
        }
        return Decision.available();
    }

    private static boolean nonEmpty(Context context, String path) throws Exception {
        try (InputStream input = context.getAssets().open(path)) {
            return input.read() != -1;
        }
    }

    public static final class Decision {
        private final boolean available;
        private final String code;
        private final String message;

        private Decision(boolean available, String code, String message) {
            this.available = available;
            this.code = code;
            this.message = message;
        }

        static Decision available() { return new Decision(true, "", ""); }
        static Decision unavailable(String code, String message) { return new Decision(false, code, message); }
        public boolean isAvailable() { return available; }
        public String getCode() { return code; }
        public String getMessage() { return message; }
    }
}
