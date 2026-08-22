package com.example.aicompanion;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;

import com.huawei.hms.location.FusedLocationProviderClient;
import com.huawei.hms.location.LocationServices;
import com.huawei.hms.maps.CameraUpdateFactory;
import com.huawei.hms.maps.HuaweiMap;
import com.huawei.hms.maps.MapView;
import com.huawei.hms.maps.MapsInitializer;
import com.huawei.hms.maps.model.BitmapDescriptorFactory;
import com.huawei.hms.maps.model.LatLng;
import com.huawei.hms.maps.model.MarkerOptions;

public class HmsMapActivity extends AppCompatActivity {
    public static final String EXTRA_WINDOW_ID = "gov_window_id";
    public static final String EXTRA_WINDOW_NAME = "gov_window_name";
    public static final String EXTRA_WINDOW_ADDRESS = "gov_window_address";
    public static final String EXTRA_WINDOW_LATITUDE = "gov_window_latitude";
    public static final String EXTRA_WINDOW_LONGITUDE = "gov_window_longitude";
    private static final int LOCATION_PERMISSION_REQUEST = 2001;
    private static final LatLng DEFAULT_CENTER = new LatLng(35.8617, 104.1954);

    private MapView mapView;
    private HuaweiMap map;
    private TextView mapStatus;
    private FusedLocationProviderClient locationClient;
    private LatLng selectedWindow;
    private String selectedWindowName;
    private String selectedWindowAddress;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        MapsInitializer.setApiKey(BuildConfig.HMS_MAP_API_KEY);
        setContentView(R.layout.activity_hms_map);

        mapStatus = findViewById(R.id.mapStatus);
        mapView = findViewById(R.id.mapView);
        mapView.onCreate(savedInstanceState);
        locationClient = LocationServices.getFusedLocationProviderClient(this);
        readValidatedWindow();

        mapView.getMapAsync(huaweiMap -> {
            map = huaweiMap;
            map.getUiSettings().setZoomControlsEnabled(true);
            LatLng center = selectedWindow == null ? DEFAULT_CENTER : selectedWindow;
            map.moveCamera(CameraUpdateFactory.newLatLngZoom(center, selectedWindow == null ? 4.2f : 15f));
            map.addMarker(new MarkerOptions()
                .position(center)
                .title(selectedWindow == null ? "中国地图" : selectedWindowName)
                .snippet(selectedWindow == null ? "" : selectedWindowAddress)
                .icon(BitmapDescriptorFactory.defaultMarker(BitmapDescriptorFactory.HUE_AZURE)));
            if (selectedWindow != null) {
                mapStatus.setText(selectedWindowName + (selectedWindowAddress.isEmpty() ? "" : " · " + selectedWindowAddress));
            }
            enableLocation();
        });
    }

    private void readValidatedWindow() {
        double latitude = getIntent().getDoubleExtra(EXTRA_WINDOW_LATITUDE, Double.NaN);
        double longitude = getIntent().getDoubleExtra(EXTRA_WINDOW_LONGITUDE, Double.NaN);
        if (!Double.isFinite(latitude) || !Double.isFinite(longitude)
            || latitude < -90 || latitude > 90 || longitude < -180 || longitude > 180) {
            selectedWindow = null;
            selectedWindowName = "";
            selectedWindowAddress = "";
            return;
        }
        selectedWindow = new LatLng(latitude, longitude);
        selectedWindowName = safeExtra(EXTRA_WINDOW_NAME, "办事窗口");
        selectedWindowAddress = safeExtra(EXTRA_WINDOW_ADDRESS, "");
    }

    private String safeExtra(String key, String fallback) {
        String value = getIntent().getStringExtra(key);
        if (value == null) return fallback;
        value = value.replaceAll("[\\r\\n\\t]", " ").trim();
        return value.length() > 160 ? value.substring(0, 160) : value;
    }

    private void enableLocation() {
        boolean fine = ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED;
        boolean coarse = ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION)
            == PackageManager.PERMISSION_GRANTED;
        if (!fine && !coarse) {
            ActivityCompat.requestPermissions(
                this,
                new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION},
                LOCATION_PERMISSION_REQUEST
            );
            return;
        }

        if (map != null) map.setMyLocationEnabled(true);
        locationClient.getLastLocation()
            .addOnSuccessListener(location -> {
                if (location == null || map == null) {
                    if (selectedWindow == null) mapStatus.setText("Huawei Map Kit · 等待实时定位");
                    return;
                }
                LatLng current = new LatLng(location.getLatitude(), location.getLongitude());
                map.addMarker(new MarkerOptions().position(current).title("当前位置"));
                if (selectedWindow == null) {
                    map.animateCamera(CameraUpdateFactory.newLatLngZoom(current, 13f));
                    mapStatus.setText("Huawei Map Kit · Location Kit 已定位");
                }
            })
            .addOnFailureListener(error -> mapStatus.setText("定位失败：" + error.getMessage()));
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == LOCATION_PERMISSION_REQUEST) {
            boolean granted = false;
            for (int result : grantResults) granted |= result == PackageManager.PERMISSION_GRANTED;
            if (granted) enableLocation();
            else if (selectedWindow == null) mapStatus.setText("未授予定位权限，可继续查看服务窗口");
        }
    }

    @Override protected void onStart() { super.onStart(); mapView.onStart(); }
    @Override protected void onResume() { super.onResume(); mapView.onResume(); }
    @Override protected void onPause() { mapView.onPause(); super.onPause(); }
    @Override protected void onStop() { mapView.onStop(); super.onStop(); }
    @Override protected void onDestroy() { mapView.onDestroy(); super.onDestroy(); }
    @Override public void onLowMemory() { super.onLowMemory(); mapView.onLowMemory(); }
}
