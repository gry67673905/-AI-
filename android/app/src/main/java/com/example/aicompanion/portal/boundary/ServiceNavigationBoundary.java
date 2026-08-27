package com.example.aicompanion.portal.boundary;

import android.app.Activity;
import android.content.Intent;

import com.example.aicompanion.ServiceNavigationActivity;
import com.example.aicompanion.navigation.business.ServiceIdPolicy;

/** Narrow portal boundary: only a validated service UUID crosses into the native navigation page. */
public final class ServiceNavigationBoundary {
    private final Activity activity;
    private final ServiceIdPolicy idPolicy = new ServiceIdPolicy();
    private final ErrorListener errors;

    public ServiceNavigationBoundary(Activity activity, ErrorListener errors) {
        this.activity = activity;
        this.errors = errors;
    }

    public void open(String rawServiceId) {
        String serviceId = idPolicy.normalize(rawServiceId);
        if (serviceId == null) {
            errors.onError("invalid_service_id", "事项编号必须是标准 UUID");
            return;
        }
        Intent intent = new Intent(activity, ServiceNavigationActivity.class);
        intent.putExtra(ServiceNavigationActivity.EXTRA_SERVICE_ID, serviceId);
        activity.startActivity(intent);
    }

    public interface ErrorListener { void onError(String code, String message); }
}
