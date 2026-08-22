package com.example.aicompanion.portal.boundary;

import android.annotation.SuppressLint;
import android.os.Build;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;

import androidx.appcompat.app.AppCompatActivity;
import androidx.webkit.WebViewAssetLoader;

import com.example.aicompanion.web.SecureAssetWebViewClient;

/** Centralized hardened WebView configuration for bundled assets only. */
public final class SecureWebViewHost {
    public static final String BRIDGE_NAME = "GovPortalNative";

    private SecureWebViewHost() {}

    @SuppressLint("SetJavaScriptEnabled") // Required for the bundled SPA; navigation and requests remain appassets-only.
    public static void configure(
        AppCompatActivity activity,
        WebView webView,
        PortalJsBoundary bridge,
        Runnable onPageReady
    ) {
        WebView.setWebContentsDebuggingEnabled(false);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setDomStorageEnabled(false);
        settings.setDatabaseEnabled(false);
        settings.setGeolocationEnabled(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setBlockNetworkLoads(true);
        settings.setSaveFormData(false);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) settings.setSafeBrowsingEnabled(true);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(false);
        cookies.setAcceptThirdPartyCookies(webView, false);

        WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
            .setDomain("appassets.androidplatform.net")
            .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(activity))
            .build();
        webView.setWebViewClient(new SecureAssetWebViewClient(loader, onPageReady));
        webView.addJavascriptInterface(bridge, BRIDGE_NAME);
    }

    public static void destroy(WebView webView) {
        if (webView == null) return;
        webView.removeJavascriptInterface(BRIDGE_NAME);
        webView.stopLoading();
        webView.clearHistory();
        webView.destroy();
    }
}
