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
    private static final int LOCATION_PERMISSION_REQUEST = 2001;
    private static final LatLng DEFAULT_CENTER = new LatLng(35.8617, 104.1954);

    private MapView mapView;
    private HuaweiMap map;
    private TextView mapStatus;
    private FusedLocationProviderClient locationClient;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        MapsInitializer.setApiKey(BuildConfig.HMS_MAP_API_KEY);
        setContentView(R.layout.activity_hms_map);

        mapStatus = findViewById(R.id.mapStatus);
        mapView = findViewById(R.id.mapView);
        mapView.onCreate(savedInstanceState);
        locationClient = LocationServices.getFusedLocationProviderClient(this);

        mapView.getMapAsync(huaweiMap -> {
            map = huaweiMap;
            map.getUiSettings().setZoomControlsEnabled(true);
            map.moveCamera(CameraUpdateFactory.newLatLngZoom(DEFAULT_CENTER, 4.2f));
            map.addMarker(new MarkerOptions()
                .position(DEFAULT_CENTER)
                .title("中国地图")
                .icon(BitmapDescriptorFactory.defaultMarker(BitmapDescriptorFactory.HUE_AZURE)));
            enableLocation();
        });
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
                    mapStatus.setText("Huawei Map Kit · 等待实时定位");
                    return;
                }
                LatLng current = new LatLng(location.getLatitude(), location.getLongitude());
                map.animateCamera(CameraUpdateFactory.newLatLngZoom(current, 13f));
                map.addMarker(new MarkerOptions().position(current).title("当前位置"));
                mapStatus.setText("Huawei Map Kit · Location Kit 已定位");
            })
            .addOnFailureListener(error -> mapStatus.setText("定位失败：" + error.getMessage()));
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == LOCATION_PERMISSION_REQUEST) enableLocation();
    }

    @Override protected void onStart() { super.onStart(); mapView.onStart(); }
    @Override protected void onResume() { super.onResume(); mapView.onResume(); }
    @Override protected void onPause() { mapView.onPause(); super.onPause(); }
    @Override protected void onStop() { mapView.onStop(); super.onStop(); }
    @Override protected void onDestroy() { mapView.onDestroy(); super.onDestroy(); }
    @Override public void onLowMemory() { super.onLowMemory(); mapView.onLowMemory(); }
}

