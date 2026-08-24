package com.example.aicompanion.metastudio.boundary;

import android.annotation.SuppressLint;
import android.net.Uri;
import android.os.Build;
import android.webkit.ConsoleMessage;
import android.webkit.CookieManager;
import android.webkit.GeolocationPermissions;
import android.webkit.JsResult;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;

import androidx.appcompat.app.AppCompatActivity;
import androidx.webkit.WebViewAssetLoader;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;

import com.example.aicompanion.metastudio.business.DigitalHumanNetworkPolicy;

import java.util.Collections;

/** Hardened host for the downloaded MetaStudio SDK. There is deliberately no JavascriptInterface. */
public final class DigitalHumanWebViewHost {
    public static final String MESSAGE_OBJECT = "GovDigitalHumanNative";

    private DigitalHumanWebViewHost() {}

    public static boolean isMessagingSupported() {
        return WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER);
    }

    @SuppressLint({"SetJavaScriptEnabled", "RequiresFeature"}) // Feature gate is enforced immediately above.
    public static void configure(
        AppCompatActivity activity,
        WebView webView,
        MessageListener messageListener,
        AudioPermissionDelegate audioPermission,
        DigitalHumanWebViewClient.Listener pageListener
    ) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            throw new IllegalStateException("MetaStudio requires Android 10 or later");
        }
        if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)) {
            throw new IllegalStateException("This System WebView lacks origin-scoped messaging");
        }

        WebView.setWebContentsDebuggingEnabled(false);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setJavaScriptCanOpenWindowsAutomatically(false);
        settings.setSupportMultipleWindows(false);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setBlockNetworkLoads(false);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(false);
        settings.setGeolocationEnabled(false);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setSaveFormData(false);
        settings.setCacheMode(WebSettings.LOAD_NO_CACHE);
        settings.setSafeBrowsingEnabled(true);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(false);
        cookies.setAcceptThirdPartyCookies(webView, false);

        DigitalHumanNetworkPolicy networkPolicy = new DigitalHumanNetworkPolicy();
        WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
            .setDomain(DigitalHumanNetworkPolicy.APP_HOST)
            .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(activity))
            .build();
        webView.setWebViewClient(new DigitalHumanWebViewClient(loader, networkPolicy, pageListener));
        webView.setWebChromeClient(new RestrictedChromeClient(networkPolicy, audioPermission));
        webView.setDownloadListener((url, userAgent, contentDisposition, mimetype, contentLength) ->
            pageListener.onBlocked("download_blocked", "数字人页面不允许下载文件")
        );

        WebViewCompat.addWebMessageListener(
            webView,
            MESSAGE_OBJECT,
            Collections.singleton(DigitalHumanNetworkPolicy.APP_ORIGIN),
            (view, message, sourceOrigin, isMainFrame, replyProxy) -> {
                if (!isMainFrame || sourceOrigin == null
                    || !networkPolicy.isAllowedOrigin(sourceOrigin.toString())) {
                    pageListener.onBlocked("untrusted_message_origin", "已拒绝非可信数字人页面消息");
                    return;
                }
                messageListener.onMessage(message.getData(), replyProxy::postMessage);
            }
        );
    }

    public static void destroy(WebView webView) {
        if (webView == null) return;
        if (isMessagingSupported()) WebViewCompat.removeWebMessageListener(webView, MESSAGE_OBJECT);
        webView.stopLoading();
        webView.loadUrl("about:blank");
        webView.clearHistory();
        webView.clearCache(true);
        webView.removeAllViews();
        webView.destroy();
    }

    public interface MessageListener { void onMessage(String data, ReplyChannel reply); }

    /** Reply is bound to the already validated main-frame origin-scoped JavaScript object. */
    public interface ReplyChannel { void post(String data); }

    public interface AudioPermissionDelegate {
        void request(PermissionRequest request);
        void cancelled(PermissionRequest request);
    }

    private static final class RestrictedChromeClient extends WebChromeClient {
        private final DigitalHumanNetworkPolicy networkPolicy;
        private final AudioPermissionDelegate permissionDelegate;

        RestrictedChromeClient(
            DigitalHumanNetworkPolicy networkPolicy,
            AudioPermissionDelegate permissionDelegate
        ) {
            this.networkPolicy = networkPolicy;
            this.permissionDelegate = permissionDelegate;
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            if (request == null || request.getOrigin() == null
                || !networkPolicy.isAllowedOrigin(request.getOrigin().toString())) {
                if (request != null) request.deny();
                return;
            }
            String[] resources = request.getResources();
            if (resources == null || resources.length != 1
                || !PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(resources[0])) {
                request.deny();
                return;
            }
            permissionDelegate.request(request);
        }

        @Override public void onPermissionRequestCanceled(PermissionRequest request) {
            permissionDelegate.cancelled(request);
        }

        @Override public boolean onCreateWindow(WebView view, boolean dialog, boolean userGesture, android.os.Message resultMsg) {
            return false;
        }

        @Override public boolean onShowFileChooser(
            WebView webView,
            ValueCallback<Uri[]> filePathCallback,
            FileChooserParams fileChooserParams
        ) {
            if (filePathCallback != null) filePathCallback.onReceiveValue(null);
            return true;
        }

        @Override public void onGeolocationPermissionsShowPrompt(
            String origin,
            GeolocationPermissions.Callback callback
        ) {
            callback.invoke(origin, false, false);
        }

        @Override public boolean onJsAlert(WebView view, String url, String message, JsResult result) {
            result.cancel();
            return true;
        }

        @Override public boolean onConsoleMessage(ConsoleMessage consoleMessage) {
            // SDK logging is configured to none; suppress console forwarding as defense in depth.
            return true;
        }
    }
}
