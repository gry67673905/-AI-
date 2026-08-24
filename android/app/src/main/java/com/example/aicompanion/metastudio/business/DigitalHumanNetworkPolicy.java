package com.example.aicompanion.metastudio.business;

import java.net.URI;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** Exact MetaStudio endpoint plus the SparkRTC suffixes published by Huawei. */
public final class DigitalHumanNetworkPolicy {
    public static final String CHAT_CONTROL_HOST =
        "metastudio-control.cn-southwest-2.myhuaweicloud.com";
    public static final String APP_HOST = "digitalhuman.appassets.androidplatform.net";
    public static final String APP_ORIGIN = "https://" + APP_HOST;
    public static final String START_PATH = "/assets/metastudio/index.html";
    public static final String START_URL = APP_ORIGIN + START_PATH;

    private static final Set<String> EXACT_HOSTS = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
        DigitalHumanSessionPolicy.BEIJING_FOUR_SERVER,
        CHAT_CONTROL_HOST
    )));
    private static final Set<String> EXACT_443_ONLY_HOSTS = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
        CHAT_CONTROL_HOST
    )));
    private static final Set<String> RTC_SUFFIXES = Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
        ".dbankcdn.com",
        ".dbankcdn.cn",
        ".dbankcloud.ru",
        ".dbankcloud.cn",
        ".dbankcloud.com",
        ".hicloud.cn",
        ".hicloud.com",
        ".dbankedge.cn"
    )));

    public boolean isTrustedMainFrame(String rawUrl) {
        URI uri = parse(rawUrl);
        return uri != null
            && "https".equalsIgnoreCase(uri.getScheme())
            && APP_HOST.equalsIgnoreCase(uri.getHost())
            && normalizedPort(uri) == 443
            && uri.getRawQuery() == null
            && uri.getRawFragment() == null
            && START_PATH.equals(uri.getPath());
    }

    public boolean isTrustedAsset(String rawUrl) {
        URI uri = parse(rawUrl);
        return uri != null
            && "https".equalsIgnoreCase(uri.getScheme())
            && APP_HOST.equalsIgnoreCase(uri.getHost())
            && normalizedPort(uri) == 443
            && uri.getUserInfo() == null
            && uri.getRawQuery() == null
            && uri.getPath() != null
            && uri.getPath().startsWith("/assets/metastudio/")
            && !uri.getPath().contains("..")
            && !uri.getPath().contains("\\");
    }

    public boolean isAllowedRemoteResource(String rawUrl) {
        URI uri = parse(rawUrl);
        if (uri == null || uri.getUserInfo() != null || uri.getHost() == null) return false;
        String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
        if (!("https".equals(scheme) || "wss".equals(scheme))) return false;
        int port = normalizedPort(uri);
        if (port != 443 && port != 6447) return false;
        String host = uri.getHost().toLowerCase(Locale.ROOT);
        if (EXACT_443_ONLY_HOSTS.contains(host)) return port == 443;
        if (EXACT_HOSTS.contains(host)) return true;
        for (String suffix : RTC_SUFFIXES) {
            if (host.endsWith(suffix) && host.length() > suffix.length()) return true;
        }
        return false;
    }

    public boolean isAllowedOrigin(String rawOrigin) {
        URI uri = parse(rawOrigin);
        String path = uri == null ? null : uri.getPath();
        return uri != null
            && "https".equalsIgnoreCase(uri.getScheme())
            && APP_HOST.equalsIgnoreCase(uri.getHost())
            && normalizedPort(uri) == 443
            && uri.getUserInfo() == null
            // Chromium exposes a canonical origin URI with a trailing slash.
            && (path != null && (path.isEmpty() || "/".equals(path)))
            && uri.getRawQuery() == null
            && uri.getRawFragment() == null;
    }

    private static int normalizedPort(URI uri) {
        return uri.getPort() == -1 ? 443 : uri.getPort();
    }

    private static URI parse(String raw) {
        if (raw == null || raw.length() > 4096) return null;
        try {
            return URI.create(raw);
        } catch (RuntimeException ignored) {
            return null;
        }
    }
}
