package com.example.aicompanion;

import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.text.TextUtils;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.widget.Toast;

import androidx.appcompat.app.AppCompatActivity;
import androidx.lifecycle.ViewModelProvider;
import androidx.webkit.WebViewAssetLoader;

import com.example.aicompanion.assistant.AssistantViewModel;
import com.example.aicompanion.assistant.ChatContract.ChatError;
import com.example.aicompanion.assistant.ChatContract.ChatResponse;
import com.example.aicompanion.assistant.GovAssistantRepository;
import com.example.aicompanion.core.HmsCoreHelper;
import com.example.aicompanion.web.SecureAssetWebViewClient;
import com.google.gson.Gson;
import com.google.gson.JsonObject;

import java.lang.ref.WeakReference;

public final class MainActivity extends AppCompatActivity {
    private static final String BRIDGE_NAME = "GovAssistantNative";

    private final Gson gson = new Gson();
    private WebView assistantWebView;
    private AssistantViewModel viewModel;
    private boolean pageReady;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        viewModel = new ViewModelProvider(
            this,
            new AssistantViewModel.Factory(new GovAssistantRepository())
        ).get(AssistantViewModel.class);

        assistantWebView = findViewById(R.id.assistantWebView);
        configureSecureWebView(assistantWebView);
        assistantWebView.loadUrl(SecureAssetWebViewClient.START_URL);
    }

    private void configureSecureWebView(WebView webView) {
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
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) settings.setSafeBrowsingEnabled(true);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(false);
        cookies.setAcceptThirdPartyCookies(webView, false);

        WebViewAssetLoader assetLoader = new WebViewAssetLoader.Builder()
            .setDomain("appassets.androidplatform.net")
            .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
            .build();
        webView.setWebViewClient(new SecureAssetWebViewClient(assetLoader, this::onPageReady));
        webView.addJavascriptInterface(new AssistantBridge(this), BRIDGE_NAME);
    }

    private void onPageReady() {
        pageReady = true;
        dispatch("onNativeReady", gson.toJson(HmsCoreHelper.describe(this)));
    }

    private void submitMessage(String message) {
        viewModel.submit(message, new AssistantViewModel.UiCallback() {
            @Override
            public void onSuccess(ChatResponse response) {
                runOnUiThread(() -> dispatch("onNativeResponse", gson.toJson(response)));
            }

            @Override
            public void onError(ChatError error) {
                JsonObject payload = new JsonObject();
                payload.addProperty("status_code", error.getStatusCode());
                payload.addProperty("code", error.getCode());
                payload.addProperty("message", error.getMessage());
                runOnUiThread(() -> dispatch("onNativeError", gson.toJson(payload)));
            }
        });
    }

    private void openMap() {
        if (!HmsCoreHelper.isAvailable(this)) {
            HmsCoreHelper.resolve(this, 1001);
            return;
        }
        if (TextUtils.isEmpty(BuildConfig.HMS_MAP_API_KEY)) {
            Toast.makeText(this, "AG Connect 配置中没有可用的 Map API Key", Toast.LENGTH_SHORT).show();
            return;
        }
        startActivity(new Intent(this, HmsMapActivity.class));
    }

    private void dispatch(String functionName, String jsonArgument) {
        if (!pageReady || assistantWebView == null) return;
        String script = "window.GovAssistant&&window.GovAssistant."
            + functionName
            + "("
            + jsonArgument
            + ");";
        assistantWebView.evaluateJavascript(script, null);
    }

    @Override
    protected void onDestroy() {
        pageReady = false;
        if (assistantWebView != null) {
            assistantWebView.removeJavascriptInterface(BRIDGE_NAME);
            assistantWebView.stopLoading();
            assistantWebView.clearHistory();
            assistantWebView.destroy();
            assistantWebView = null;
        }
        super.onDestroy();
    }

    /** Only two fixed commands are exposed; callers cannot choose a URL or native method. */
    private static final class AssistantBridge {
        private final WeakReference<MainActivity> activityReference;

        private AssistantBridge(MainActivity activity) {
            activityReference = new WeakReference<>(activity);
        }

        @JavascriptInterface
        public void sendMessage(String message) {
            MainActivity activity = activityReference.get();
            if (activity != null) activity.runOnUiThread(() -> activity.submitMessage(message));
        }

        @JavascriptInterface
        public void openMap() {
            MainActivity activity = activityReference.get();
            if (activity != null) activity.runOnUiThread(activity::openMap);
        }
    }
}
