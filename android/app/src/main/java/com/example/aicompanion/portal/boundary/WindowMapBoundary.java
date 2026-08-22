package com.example.aicompanion.portal.boundary;

import android.content.Intent;
import android.text.TextUtils;

import androidx.appcompat.app.AppCompatActivity;

import com.example.aicompanion.BuildConfig;
import com.example.aicompanion.HmsMapActivity;
import com.example.aicompanion.core.HmsCoreHelper;
import com.example.aicompanion.portal.business.PortalCommandPolicy;
import com.example.aicompanion.portal.gateway.CatalogGateway;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.example.aicompanion.portal.model.PortalContract.WindowLocation;

import java.lang.ref.WeakReference;

/** Resolves a validated backend window id; coordinates never cross the JS bridge. */
public final class WindowMapBoundary {
    public interface Listener { void onError(String code, String message); }

    private final WeakReference<AppCompatActivity> activity;
    private final CatalogGateway catalog;
    private final Listener listener;

    public WindowMapBoundary(AppCompatActivity activity, CatalogGateway catalog, Listener listener) {
        this.activity = new WeakReference<>(activity);
        this.catalog = catalog;
        this.listener = listener;
    }

    public void open(String windowId) {
        if (!PortalCommandPolicy.isSafeResourceId(windowId)) {
            listener.onError("invalid_window_id", "窗口编号格式无效");
            return;
        }
        catalog.resolveWindow(windowId, new GatewayCallback<WindowLocation>() {
            @Override public void onSuccess(WindowLocation window) {
                AppCompatActivity host = activity.get();
                if (host == null || host.isFinishing() || host.isDestroyed()) return;
                host.runOnUiThread(() -> launch(host, window));
            }
            @Override public void onError(ApiFailure error) { listener.onError(error.getCode(), error.getMessage()); }
        });
    }

    private void launch(AppCompatActivity host, WindowLocation window) {
        if (!HmsCoreHelper.isAvailable(host)) {
            HmsCoreHelper.resolve(host, 1001);
            return;
        }
        if (TextUtils.isEmpty(BuildConfig.HMS_MAP_API_KEY)) {
            listener.onError("map_not_configured", "AG Connect 配置中没有可用的 Map API Key");
            return;
        }
        Intent intent = new Intent(host, HmsMapActivity.class)
            .putExtra(HmsMapActivity.EXTRA_WINDOW_ID, window.getId())
            .putExtra(HmsMapActivity.EXTRA_WINDOW_NAME, window.getName())
            .putExtra(HmsMapActivity.EXTRA_WINDOW_ADDRESS, window.getAddress())
            .putExtra(HmsMapActivity.EXTRA_WINDOW_LATITUDE, window.getLatitude())
            .putExtra(HmsMapActivity.EXTRA_WINDOW_LONGITUDE, window.getLongitude());
        host.startActivity(intent);
    }
}
