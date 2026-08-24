package com.example.aicompanion.metastudio.boundary;

import android.graphics.Bitmap;
import android.net.Uri;
import android.net.http.SslError;
import android.os.Build;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.SafeBrowsingResponse;
import android.webkit.SslErrorHandler;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.annotation.Nullable;
import androidx.annotation.RequiresApi;
import androidx.webkit.WebViewAssetLoader;

import com.example.aicompanion.metastudio.business.DigitalHumanNetworkPolicy;

import java.io.ByteArrayInputStream;

/** Main-frame navigation is local-only; remote access is limited to Huawei MetaStudio/SparkRTC resources. */
public final class DigitalHumanWebViewClient extends WebViewClient {
    private final WebViewAssetLoader assetLoader;
    private final DigitalHumanNetworkPolicy networkPolicy;
    private final Listener listener;

    public DigitalHumanWebViewClient(
        WebViewAssetLoader assetLoader,
        DigitalHumanNetworkPolicy networkPolicy,
        Listener listener
    ) {
        this.assetLoader = assetLoader;
        this.networkPolicy = networkPolicy;
        this.listener = listener;
    }

    @Nullable
    @Override
    public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
        return intercept(request.getUrl().toString());
    }

    @Nullable
    @Override
    @SuppressWarnings("deprecation")
    public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
        return intercept(url);
    }

    @Override
    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
        String url = request.getUrl().toString();
        if (request.isForMainFrame()) return !networkPolicy.isTrustedMainFrame(url);
        return !(networkPolicy.isTrustedAsset(url) || networkPolicy.isAllowedRemoteResource(url));
    }

    @Override
    @SuppressWarnings("deprecation")
    public boolean shouldOverrideUrlLoading(WebView view, String url) {
        return !networkPolicy.isTrustedMainFrame(url);
    }

    @Override
    public void onPageStarted(WebView view, String url, Bitmap favicon) {
        if (!networkPolicy.isTrustedMainFrame(url)) {
            view.stopLoading();
            listener.onBlocked("blocked_navigation", "已阻止数字人页面跳转");
        }
    }

    @Override
    public void onPageFinished(WebView view, String url) {
        if (networkPolicy.isTrustedMainFrame(url)) listener.onPageReady();
    }

    @Override
    public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
        handler.cancel();
        listener.onBlocked("ssl_error", "数字人服务证书校验失败");
    }

    @Override
    @RequiresApi(Build.VERSION_CODES.O_MR1)
    public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
        listener.onRendererGone(view, "数字人渲染进程已终止");
        return true;
    }

    @Override
    @RequiresApi(Build.VERSION_CODES.O_MR1)
    public void onSafeBrowsingHit(
        WebView view,
        WebResourceRequest request,
        int threatType,
        SafeBrowsingResponse callback
    ) {
        callback.backToSafety(true);
        listener.onBlocked("safe_browsing_block", "数字人资源已被安全浏览拦截");
    }

    private WebResourceResponse intercept(String url) {
        if (networkPolicy.isTrustedAsset(url)) {
            WebResourceResponse local = assetLoader.shouldInterceptRequest(Uri.parse(url));
            return local == null ? blockedResponse() : local;
        }
        if (networkPolicy.isAllowedRemoteResource(url)) return null;
        return blockedResponse();
    }

    private static WebResourceResponse blockedResponse() {
        return new WebResourceResponse("text/plain", "UTF-8", new ByteArrayInputStream(new byte[0]));
    }

    public interface Listener {
        void onPageReady();
        void onBlocked(String code, String message);
        void onRendererGone(WebView view, String message);
    }
}
