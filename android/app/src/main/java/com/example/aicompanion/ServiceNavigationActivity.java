package com.example.aicompanion;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.view.View;
import android.widget.Button;
import android.widget.RadioButton;
import android.widget.RadioGroup;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;

import com.example.aicompanion.navigation.business.NavigationStateMachine;
import com.example.aicompanion.navigation.business.NavigationLocationLifecycle;
import com.example.aicompanion.navigation.business.NearbyWindowSelector;
import com.example.aicompanion.navigation.business.ServiceIdPolicy;
import com.example.aicompanion.navigation.business.ServiceNavigationController;
import com.example.aicompanion.navigation.engine.HuaweiNaviEngineAdapter;
import com.example.aicompanion.navigation.gateway.NavigationOptionsGateway;
import com.example.aicompanion.navigation.gateway.OkHttpNavigationOptionsGateway;
import com.example.aicompanion.navigation.location.ForegroundLocationSource;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.GeoPoint;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.LocationSample;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.NavigationOptions;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.RoutePreview;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.TravelMode;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.WindowOption;
import com.example.aicompanion.navigation.speech.AndroidNavigationSpeechOutput;
import com.example.aicompanion.portal.gateway.BrokeredSecureSessionStore;
import com.example.aicompanion.portal.gateway.GatewayCallback;
import com.example.aicompanion.portal.gateway.NativeApiClient;
import com.example.aicompanion.portal.model.PortalContract.ApiFailure;
import com.huawei.hms.maps.CameraUpdateFactory;
import com.huawei.hms.maps.HuaweiMap;
import com.huawei.hms.maps.MapView;
import com.huawei.hms.maps.MapsInitializer;
import com.huawei.hms.maps.model.BitmapDescriptorFactory;
import com.huawei.hms.maps.model.LatLng;
import com.huawei.hms.maps.model.MarkerOptions;
import com.huawei.hms.maps.model.PolylineOptions;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** Native, non-exported route page. It never exposes location to either WebView. */
public final class ServiceNavigationActivity extends AppCompatActivity
    implements ForegroundLocationSource.Listener, ServiceNavigationController.Listener,
    NavigationLocationLifecycle.Listener {

    public static final String EXTRA_SERVICE_ID = "gov_navigation_service_id";
    private static final int LOCATION_PERMISSION_REQUEST = 2401;
    private static final int MAX_VISIBLE_WINDOWS = 3;

    private final NearbyWindowSelector nearbySelector = new NearbyWindowSelector();
    private MapView mapView;
    private HuaweiMap map;
    private TextView title;
    private TextView status;
    private TextView demoNotice;
    private RadioGroup windowGroup;
    private RadioGroup modeGroup;
    private Button locationButton;
    private Button reloadButton;
    private Button previewButton;
    private Button startButton;
    private Button stopButton;
    private NavigationOptionsGateway optionsGateway;
    private ForegroundLocationSource locationSource;
    private NavigationLocationLifecycle locationLifecycle;
    private ServiceNavigationController controller;
    private NavigationOptions options;
    private LocationSample currentLocation;
    private List<WindowOption> visibleWindows = Collections.emptyList();
    private RoutePreview routePreview;
    private boolean sortedWithLocation;
    private boolean foreground;
    private boolean suppressWindowSelection;
    private String serviceId;

    @Override protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        serviceId = new ServiceIdPolicy().normalize(getIntent().getStringExtra(EXTRA_SERVICE_ID));
        if (serviceId == null) {
            finish();
            return;
        }
        MapsInitializer.setApiKey(BuildConfig.HMS_MAP_API_KEY);
        setContentView(R.layout.activity_service_navigation);
        bindViews();
        mapView.onCreate(savedInstanceState);
        mapView.getMapAsync(this::onMapReady);

        controller = new ServiceNavigationController(
            new HuaweiNaviEngineAdapter(this),
            new AndroidNavigationSpeechOutput(this),
            this
        );
        locationSource = new ForegroundLocationSource(this, this);
        locationLifecycle = new NavigationLocationLifecycle(locationSource, controller, this);
        NativeApiClient api = new NativeApiClient(
            NativeApiClient.defaultClient(),
            BuildConfig.GOV_API_BASE,
            new BrokeredSecureSessionStore(this)
        );
        optionsGateway = new OkHttpNavigationOptionsGateway(api);
        configureActions();
        loadOptions(serviceId);
    }

    private void bindViews() {
        mapView = findViewById(R.id.navigationMapView);
        title = findViewById(R.id.navigationServiceTitle);
        status = findViewById(R.id.navigationStatus);
        demoNotice = findViewById(R.id.navigationDemoNotice);
        windowGroup = findViewById(R.id.navigationWindows);
        modeGroup = findViewById(R.id.navigationTravelMode);
        locationButton = findViewById(R.id.navigationEnableLocation);
        reloadButton = findViewById(R.id.navigationReloadOptions);
        previewButton = findViewById(R.id.navigationPreviewRoute);
        startButton = findViewById(R.id.navigationStart);
        stopButton = findViewById(R.id.navigationStop);
    }

    private void configureActions() {
        locationButton.setOnClickListener(view -> requestOrStartLocation());
        reloadButton.setOnClickListener(view -> loadOptions(serviceId));
        modeGroup.setOnCheckedChangeListener((group, checkedId) -> {
            routePreview = null;
            controller.setTravelMode(
                checkedId == R.id.navigationDriving ? TravelMode.DRIVING : TravelMode.WALKING
            );
            renderBaseMap();
        });
        windowGroup.setOnCheckedChangeListener((group, checkedId) -> {
            if (suppressWindowSelection) return;
            View selected = group.findViewById(checkedId);
            if (selected != null && selected.getTag() instanceof WindowOption) {
                controller.selectWindow((WindowOption) selected.getTag());
                routePreview = null;
                renderBaseMap();
                updateDemoNotice((WindowOption) selected.getTag());
            }
        });
        previewButton.setOnClickListener(view -> {
            status.setText("正在请求华为导航规划演示路线…");
            controller.plan(currentLocation);
        });
        startButton.setOnClickListener(view -> startNavigationWithTracking());
        stopButton.setOnClickListener(view -> stopNavigationWithTracking());
        updateButtons(NavigationStateMachine.Phase.LOADING_OPTIONS);
    }

    private void loadOptions(String serviceId) {
        reloadButton.setEnabled(false);
        status.setText("正在从项目服务端读取服务网点…");
        optionsGateway.load(serviceId, new GatewayCallback<NavigationOptions>() {
            @Override public void onSuccess(NavigationOptions value) {
                runOnUiThread(() -> applyOptions(value));
            }

            @Override public void onError(ApiFailure error) {
                runOnUiThread(() -> {
                    title.setText("事项服务导航");
                    status.setText(error.getMessage());
                    previewButton.setEnabled(false);
                    reloadButton.setEnabled(true);
                    reloadButton.setVisibility(View.VISIBLE);
                });
            }
        });
    }

    private void applyOptions(NavigationOptions value) {
        options = value;
        reloadButton.setVisibility(View.GONE);
        title.setText(value.getService().getName());
        controller.optionsReady();
        if (currentLocation != null) sortedWithLocation = true;
        renderWindows(currentLocation == null ? null : currentLocation.getPoint());
        if (value.getWindows().isEmpty()) {
            status.setText("该事项当前没有可导航的服务网点");
        } else if (currentLocation == null) {
            status.setText("已按目录优先级显示网点；启用前台定位后将在本机重排最近 3 个");
        }
    }

    private void renderWindows(GeoPoint current) {
        if (options == null) return;
        visibleWindows = nearbySelector.select(options.getWindows(), current, MAX_VISIBLE_WINDOWS);
        suppressWindowSelection = true;
        windowGroup.removeAllViews();
        for (WindowOption window : visibleWindows) {
            RadioButton option = new RadioButton(this);
            option.setId(View.generateViewId());
            option.setTag(window);
            String distance = current == null ? ""
                : " · " + formatDistance(nearbySelector.distanceMeters(current, window.getPoint()));
            option.setText(window.getName() + distance + "\n" + window.getAddress());
            option.setPadding(0, 6, 0, 6);
            windowGroup.addView(option);
        }
        suppressWindowSelection = false;
        if (!visibleWindows.isEmpty()) {
            RadioButton first = (RadioButton) windowGroup.getChildAt(0);
            first.setChecked(true);
            controller.selectWindow((WindowOption) first.getTag());
            updateDemoNotice((WindowOption) first.getTag());
        }
        renderBaseMap();
        updateButtons(controller.getPhase());
    }

    private void updateDemoNotice(WindowOption selected) {
        boolean demo = options != null && (options.isDemoOnly() || (selected != null && selected.isDemo()));
        demoNotice.setVisibility(demo ? View.VISIBLE : View.GONE);
        if (demo && options != null && !options.getNotice().isEmpty()) {
            demoNotice.setText("DEMO：演示路线，不用于实际出行。\n" + options.getNotice());
        } else {
            demoNotice.setText("DEMO：演示路线，不用于实际出行。");
        }
    }

    private void requestOrStartLocation() {
        sortedWithLocation = false;
        routePreview = null;
        WindowOption selected = controller.getSelectedWindow();
        if (selected != null) controller.selectWindow(selected);
        if (hasLocationPermission()) {
            if (foreground) locationLifecycle.requestSortFix(true);
            setMapLocationLayer(true);
            status.setText("正在取得 GCJ02 前台定位（10 秒超时）…");
            updateButtons(controller.getPhase());
            return;
        }
        locationLifecycle.requestSortFix(false);
        ActivityCompat.requestPermissions(
            this,
            new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION},
            LOCATION_PERMISSION_REQUEST
        );
    }

    private boolean hasLocationPermission() {
        return ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED
            || ActivityCompat.checkSelfPermission(this, Manifest.permission.ACCESS_COARSE_LOCATION)
            == PackageManager.PERMISSION_GRANTED;
    }

    @Override public void onLocation(LocationSample sample) {
        // This project stores service-window coordinates as GCJ02. Huawei Location/Navi/Map are
        // consumed under that same mainland-China coordinate semantic; no conversion or backend
        // upload occurs in this Activity.
        currentLocation = sample;
        // The first fix performs the one-time nearest-three sort. Later foreground fixes are
        // retained only to feed live turn-by-turn guidance after the user starts navigation.
        controller.updateLocation(sample);
        status.setText("前台定位已就绪；当前位置仅保存在本页内存中");
        locationButton.setText("重新取得并重排网点");
        if (!sortedWithLocation && options != null) {
            sortedWithLocation = true;
            renderWindows(sample.getPoint());
        } else {
            renderBaseMap();
            updateButtons(controller.getPhase());
        }
        if (controller.getPhase() != NavigationStateMachine.Phase.NAVIGATING) {
            setMapLocationLayer(false);
        }
    }

    @Override public void onLocationError(String message) {
        currentLocation = null;
        setMapLocationLayer(false);
        if (controller.getPhase() == NavigationStateMachine.Phase.STARTING_NAVIGATION
            || controller.getPhase() == NavigationStateMachine.Phase.NAVIGATING) {
            locationLifecycle.stopNavigation();
        }
        if (options != null) renderWindows(null);
        status.setText(message + "；仍可查看按优先级排列的网点");
        updateButtons(controller.getPhase());
    }

    private void onMapReady(HuaweiMap value) {
        map = value;
        map.getUiSettings().setZoomControlsEnabled(true);
        renderBaseMap();
    }

    private void renderBaseMap() {
        if (map == null) return;
        map.clear();
        for (WindowOption window : visibleWindows) {
            map.addMarker(new MarkerOptions()
                .position(latLng(window.getPoint()))
                .title(window.getName())
                .snippet(window.getAddress()));
        }
        if (currentLocation != null) {
            map.addMarker(new MarkerOptions()
                .position(latLng(currentLocation.getPoint()))
                .title("当前位置")
                .icon(BitmapDescriptorFactory.defaultMarker(BitmapDescriptorFactory.HUE_AZURE)));
        }
        WindowOption selected = controller == null ? null : controller.getSelectedWindow();
        if (selected != null) {
            map.moveCamera(CameraUpdateFactory.newLatLngZoom(latLng(selected.getPoint()), 13.5f));
        } else if (!visibleWindows.isEmpty()) {
            map.moveCamera(CameraUpdateFactory.newLatLngZoom(latLng(visibleWindows.get(0).getPoint()), 12f));
        }
    }

    private void renderRoute(RoutePreview preview) {
        renderBaseMap();
        if (map == null || preview == null) return;
        List<LatLng> points = new ArrayList<>();
        for (GeoPoint point : preview.getPoints()) points.add(latLng(point));
        map.addPolyline(new PolylineOptions().addAll(points).color(getColor(R.color.brand_blue)).width(12f));
        if (!points.isEmpty()) {
            map.animateCamera(CameraUpdateFactory.newLatLngZoom(points.get(points.size() / 2), 12.5f));
        }
    }

    @Override public void onPhaseChanged(NavigationStateMachine.Phase phase) {
        if (phase == NavigationStateMachine.Phase.STARTING_NAVIGATION) {
            status.setText("正在启动华为逐向导航…");
        } else if (phase == NavigationStateMachine.Phase.NAVIGATING) {
            status.setText("华为逐向导航已启动，等待首条导航提示…");
        }
        updateButtons(phase);
    }

    @Override public void onRoutePreview(RoutePreview preview) {
        routePreview = preview;
        renderRoute(preview);
        String prefix = controller != null
            && controller.getPhase() == NavigationStateMachine.Phase.NAVIGATING
            ? "路线已重新规划：" : "路线预览：";
        status.setText(prefix + formatDistance(preview.getDistanceMeters())
            + " · 约 " + formatDuration(preview.getDurationSeconds()));
    }

    @Override public void onInstruction(String text) {
        status.setText("导航提示：" + text);
    }

    @Override public void onArrived() {
        locationLifecycle.stopTracking();
        setMapLocationLayer(false);
        status.setText("已到达所选服务网点");
    }

    @Override public void onError(String code, String message) {
        if (controller.getPhase() == NavigationStateMachine.Phase.ERROR
            || (code != null && code.startsWith("navigation_start_"))) {
            locationLifecycle.stopTracking();
            setMapLocationLayer(false);
        }
        status.setText(message);
    }

    private void updateButtons(NavigationStateMachine.Phase phase) {
        boolean hasDestination = controller != null && controller.getSelectedWindow() != null;
        boolean canPlan = currentLocation != null && hasDestination
            && (phase == NavigationStateMachine.Phase.READY
                || phase == NavigationStateMachine.Phase.PREVIEW
                || phase == NavigationStateMachine.Phase.ERROR);
        previewButton.setEnabled(canPlan);
        startButton.setEnabled(phase == NavigationStateMachine.Phase.PREVIEW && routePreview != null);
        // Starting is asynchronous. Keep an explicit cancellation path available if the SDK is
        // slow or never reaches onStartNaviSuccess on a particular device/network.
        stopButton.setEnabled(phase == NavigationStateMachine.Phase.STARTING_NAVIGATION
            || phase == NavigationStateMachine.Phase.NAVIGATING);
        boolean selectorsEnabled = phase != NavigationStateMachine.Phase.PLANNING
            && phase != NavigationStateMachine.Phase.STARTING_NAVIGATION
            && phase != NavigationStateMachine.Phase.NAVIGATING;
        setGroupEnabled(windowGroup, selectorsEnabled);
        setGroupEnabled(modeGroup, selectorsEnabled);
        locationButton.setEnabled(selectorsEnabled);
    }

    private void startNavigationWithTracking() {
        if (!hasLocationPermission()) {
            locationLifecycle.permissionDenied();
            return;
        }
        // The one-shot fix may have arrived before Navi Kit's delayed initialization and would
        // then have been intentionally ignored by the adapter. Re-inject the latest in-memory
        // foreground fix immediately before startNavi so external-location mode always has a fix.
        boolean started = locationLifecycle.startNavigation(currentLocation);
        setMapLocationLayer(started);
    }

    private void stopNavigationWithTracking() {
        locationLifecycle.stopNavigation();
        setMapLocationLayer(false);
    }

    @SuppressLint("MissingPermission")
    private void setMapLocationLayer(boolean enabled) {
        if (map == null) return;
        try {
            map.setMyLocationEnabled(enabled && hasLocationPermission());
        } catch (SecurityException ignored) {}
    }

    @Override public void onPermissionRequired() {
        status.setText("需要前台定位权限；拒绝后仍可查看服务网点");
    }

    @Override public void onPermissionDenied() {
        currentLocation = null;
        setMapLocationLayer(false);
        if (options != null) renderWindows(null);
        status.setText("未授予定位权限；仍可查看服务网点，但不能规划路线");
        updateButtons(controller.getPhase());
    }

    private static void setGroupEnabled(RadioGroup group, boolean enabled) {
        group.setEnabled(enabled);
        for (int index = 0; index < group.getChildCount(); index++) {
            group.getChildAt(index).setEnabled(enabled);
        }
    }

    private static LatLng latLng(GeoPoint point) {
        return new LatLng(point.getLatitude(), point.getLongitude());
    }

    private static String formatDistance(double meters) {
        return meters < 1000d
            ? String.format(Locale.CHINA, "%.0f 米", meters)
            : String.format(Locale.CHINA, "%.1f 公里", meters / 1000d);
    }

    private static String formatDuration(int seconds) {
        int minutes = Math.max(1, (int) Math.ceil(seconds / 60d));
        return minutes < 60 ? minutes + " 分钟" : (minutes / 60) + " 小时 " + (minutes % 60) + " 分钟";
    }

    @Override public void onRequestPermissionsResult(
        int requestCode,
        @NonNull String[] permissions,
        @NonNull int[] grantResults
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != LOCATION_PERMISSION_REQUEST) return;
        if (hasLocationPermission()) {
            status.setText("正在取得 GCJ02 前台定位（10 秒超时）…");
            locationLifecycle.requestSortFix(true);
            setMapLocationLayer(true);
        } else {
            locationLifecycle.permissionDenied();
        }
    }

    @Override protected void onStart() {
        super.onStart();
        foreground = true;
        mapView.onStart();
    }

    @Override protected void onResume() { super.onResume(); mapView.onResume(); }
    @Override protected void onPause() { mapView.onPause(); super.onPause(); }

    @Override protected void onStop() {
        foreground = false;
        if (locationLifecycle != null) locationLifecycle.onStop();
        setMapLocationLayer(false);
        mapView.onStop();
        super.onStop();
    }

    @Override protected void onDestroy() {
        if (locationLifecycle != null) locationLifecycle.destroy();
        mapView.onDestroy();
        super.onDestroy();
    }

    @Override protected void onSaveInstanceState(@NonNull Bundle outState) {
        super.onSaveInstanceState(outState);
        mapView.onSaveInstanceState(outState);
    }

    @Override public void onLowMemory() { super.onLowMemory(); mapView.onLowMemory(); }
}
