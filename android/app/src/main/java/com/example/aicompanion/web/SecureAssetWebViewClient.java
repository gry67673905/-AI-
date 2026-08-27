package com.example.aicompanion.web;

import android.graphics.Bitmap;
import android.net.Uri;
import android.net.http.SslError;
import android.webkit.SslErrorHandler;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.annotation.Nullable;
import androidx.webkit.WebViewAssetLoader;

import java.io.ByteArrayInputStream;

/** Serves bundled files and denies every non-appassets request or navigation. */
public final class SecureAssetWebViewClient extends WebViewClient {
    public static final String APP_ORIGIN = "https://appassets.androidplatform.net";
    public static final String START_URL = APP_ORIGIN
        + "/assets/index.html?v=portal-20260825-1";

    private final WebViewAssetLoader assetLoader;
    private final Runnable onPageReady;

    public SecureAssetWebViewClient(WebViewAssetLoader assetLoader, Runnable onPageReady) {
        this.assetLoader = assetLoader;
        this.onPageReady = onPageReady;
    }

    @Nullable
    @Override
    public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
        return intercept(request.getUrl());
    }

    @Nullable
    @Override
    @SuppressWarnings("deprecation")
    public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
        return intercept(Uri.parse(url));
    }

    @Override
    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
        return !isTrustedAsset(request.getUrl());
    }

    @Override
    @SuppressWarnings("deprecation")
    public boolean shouldOverrideUrlLoading(WebView view, String url) {
        return !isTrustedAsset(Uri.parse(url));
    }

    @Override
    public void onPageStarted(WebView view, String url, Bitmap favicon) {
        if (!isTrustedAsset(Uri.parse(url))) view.stopLoading();
    }

    @Override
    public void onPageFinished(WebView view, String url) {
        if (isTrustedAsset(Uri.parse(url))) onPageReady.run();
    }

    @Override
    public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
        handler.cancel();
    }

    private WebResourceResponse intercept(Uri uri) {
        if (!isTrustedAsset(uri)) return blockedResponse();
        WebResourceResponse response = assetLoader.shouldInterceptRequest(uri);
        return response == null ? blockedResponse() : response;
    }

    public static boolean isTrustedAsset(Uri uri) {
        return uri != null
            && "https".equals(uri.getScheme())
            && "appassets.androidplatform.net".equals(uri.getHost())
            && uri.getPort() == -1
            && uri.getPath() != null
            && uri.getPath().startsWith("/assets/");
    }

    private static WebResourceResponse blockedResponse() {
        return new WebResourceResponse(
            "text/plain",
            "UTF-8",
            new ByteArrayInputStream(new byte[0])
        );
    }
}
