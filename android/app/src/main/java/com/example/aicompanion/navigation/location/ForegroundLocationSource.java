package com.example.aicompanion.navigation.location;

import android.annotation.SuppressLint;
import android.content.Context;
import android.location.Location;
import android.os.Handler;
import android.os.Looper;

import com.example.aicompanion.navigation.model.ServiceNavigationContract.GeoPoint;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.LocationSample;
import com.huawei.hms.location.FusedLocationProviderClient;
import com.huawei.hms.location.LocationCallback;
import com.huawei.hms.location.LocationRequest;
import com.huawei.hms.location.LocationResult;
import com.huawei.hms.location.LocationServices;

/** Location Kit source that is started/stopped strictly with the visible navigation Activity. */
public final class ForegroundLocationSource implements ForegroundLocationControl {
    private static final long MAX_CACHED_LOCATION_AGE_MILLIS = 120_000L;
    private static final long MAX_CACHED_LOCATION_FUTURE_SKEW_MILLIS = 30_000L;
    private static final float MAX_CACHED_LOCATION_ACCURACY_METERS = 10_000f;
    private enum Mode { IDLE, ONE_SHOT, CONTINUOUS }
    private final FusedLocationProviderClient client;
    private final Listener listener;
    private final LocationCallback callback;
    private final ForegroundLocationDeadline deadline;
    private boolean started;
    private Mode mode = Mode.IDLE;

    public ForegroundLocationSource(Context context, Listener listener) {
        this.client = LocationServices.getFusedLocationProviderClient(context);
        this.listener = listener;
        Handler handler = new Handler(Looper.getMainLooper());
        this.deadline = new ForegroundLocationDeadline((task, delayMillis) -> {
            handler.postDelayed(task, delayMillis);
            return () -> handler.removeCallbacks(task);
        });
        this.callback = new LocationCallback() {
            @Override public void onLocationResult(LocationResult result) {
                if (result != null) deliver(result.getLastLocation());
            }
        };
    }

    @Override @SuppressLint("MissingPermission")
    public void startOneShot() { start(Mode.ONE_SHOT); }

    @Override @SuppressLint("MissingPermission")
    public void startContinuous() { start(Mode.CONTINUOUS); }

    @SuppressLint("MissingPermission")
    private void start(Mode requestedMode) {
        stop();
        started = true;
        mode = requestedMode;
        deadline.start(() -> {
            if (!started) return;
            started = false;
            mode = Mode.IDLE;
            client.removeLocationUpdates(callback);
            notifyError("10 秒内未取得前台定位，请稍后重试");
        });
        client.getLastLocation()
            // A cached-location miss is not terminal: the live request below may still produce
            // a valid fix before the shared 10-second deadline.
            .addOnSuccessListener(location -> {
                if (isUsableCachedLocation(location, System.currentTimeMillis())) deliver(location);
            });
        LocationRequest request = LocationRequest.create()
            .setPriority(LocationRequest.PRIORITY_HIGH_ACCURACY)
            .setInterval(2_000L)
            .setFastestInterval(1_000L)
            .setSmallestDisplacement(2f);
        client.requestLocationUpdates(request, callback, Looper.getMainLooper())
            .addOnSuccessListener(ignored -> {
                // getLastLocation can win before registration finishes. In one-shot mode deliver()
                // already moved to IDLE, so remove the just-registered callback again.
                if (!started || mode == Mode.IDLE) client.removeLocationUpdates(callback);
            })
            .addOnFailureListener(error -> {
                if (!started) return;
                started = false;
                mode = Mode.IDLE;
                deadline.stop();
                notifyError("无法启动前台定位");
            });
    }

    @Override public void stop() {
        deadline.stop();
        mode = Mode.IDLE;
        if (!started) return;
        started = false;
        client.removeLocationUpdates(callback);
    }

    private void deliver(Location location) {
        if (!started || location == null) return;
        try {
            LocationSample sample = new LocationSample(
                new GeoPoint(location.getLatitude(), location.getLongitude()),
                location.hasAccuracy() ? location.getAccuracy() : 0f,
                location.hasBearing() ? location.getBearing() : 0f,
                location.hasSpeed() ? location.getSpeed() : 0f,
                location.getTime() > 0 ? location.getTime() : System.currentTimeMillis()
            );
            deadline.firstFixReceived();
            boolean oneShot = mode == Mode.ONE_SHOT;
            if (oneShot) {
                started = false;
                mode = Mode.IDLE;
                client.removeLocationUpdates(callback);
            }
            listener.onLocation(sample);
        } catch (IllegalArgumentException invalid) {
            notifyError("定位坐标无效");
        }
    }

    private void notifyError(String message) {
        if (listener != null) listener.onLocationError(message);
    }

    private static boolean isUsableCachedLocation(Location location, long nowMillis) {
        if (location == null || location.getTime() <= 0L || !location.hasAccuracy()) return false;
        long ageMillis = nowMillis - location.getTime();
        float accuracy = location.getAccuracy();
        return ageMillis >= -MAX_CACHED_LOCATION_FUTURE_SKEW_MILLIS
            && ageMillis <= MAX_CACHED_LOCATION_AGE_MILLIS
            && Float.isFinite(accuracy)
            && accuracy >= 0f
            && accuracy <= MAX_CACHED_LOCATION_ACCURACY_METERS;
    }

    public interface Listener {
        void onLocation(LocationSample sample);
        void onLocationError(String message);
    }
}
