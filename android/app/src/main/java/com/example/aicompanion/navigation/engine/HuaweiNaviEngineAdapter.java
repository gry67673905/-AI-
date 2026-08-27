package com.example.aicompanion.navigation.engine;

import android.app.Activity;
import android.content.Context;
import android.location.Location;
import android.os.Handler;
import android.os.Looper;

import com.example.aicompanion.BuildConfig;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.GeoPoint;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.LocationSample;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.RoutePreview;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.RouteRequest;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.TravelMode;
import com.huawei.hms.navi.navibase.MapNavi;
import com.huawei.hms.navi.navibase.MapNaviListener;
import com.huawei.hms.navi.navibase.enums.NaviMode;
import com.huawei.hms.navi.navibase.enums.VehicleType;
import com.huawei.hms.navi.navibase.model.DevServerSiteConstant;
import com.huawei.hms.navi.navibase.model.MapNaviPath;
import com.huawei.hms.navi.navibase.model.NaviBroadInfo;
import com.huawei.hms.navi.navibase.model.NaviRequestPoint;
import com.huawei.hms.navi.navibase.model.NaviStrategy;
import com.huawei.hms.navi.navibase.model.RoutingRequestParam;
import com.huawei.hms.navi.navibase.model.locationstruct.NaviLatLng;

import java.lang.reflect.Proxy;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Lazy Huawei Navi Kit adapter. No SDK object is created until the user requests a route. */
public final class HuaweiNaviEngineAdapter implements NavigationEngine {
    private final Context applicationContext;
    private final Activity locationContext;
    private final Handler main = new Handler(Looper.getMainLooper());
    private MapNavi mapNavi;
    private MapNaviListener mapListener;
    private Listener listener;
    private boolean destroyed;

    public HuaweiNaviEngineAdapter(Activity activity) {
        if (activity == null) throw new IllegalArgumentException("Navigation Activity is required");
        locationContext = activity;
        applicationContext = activity.getApplicationContext();
    }

    @Override public void setListener(Listener listener) { this.listener = listener; }

    @Override public void planRoute(RouteRequest request) {
        if (destroyed) return;
        if (BuildConfig.HMS_MAP_API_KEY == null || BuildConfig.HMS_MAP_API_KEY.trim().isEmpty()) {
            failure("huawei_navi_key_missing", "本地构建未配置华为地图与导航 API Key");
            return;
        }
        try {
            MapNavi navi = ensureInitialized();
            navi.setCoordinateSystem(request.getDestination().getCoordinateType());
            navi.setVehicleType(request.getMode() == TravelMode.WALKING
                ? VehicleType.WALKING : VehicleType.DRIVING);

            RoutingRequestParam parameters = new RoutingRequestParam();
            parameters.setFromPoints(Collections.singletonList(point(request.getOrigin().getPoint())));
            parameters.setToPoints(Collections.singletonList(point(request.getDestination().getPoint())));
            NaviStrategy strategy = new NaviStrategy();
            strategy.setSmartRecommend(true);
            parameters.setStrategy(strategy);
            parameters.setAlternatives(false);

            boolean accepted = request.getMode() == TravelMode.WALKING
                ? navi.calculateWalkRoute(parameters)
                : navi.calculateDriveRoute(parameters);
            if (!accepted) failure("route_request_rejected", "华为导航未接受路线规划请求");
        } catch (RuntimeException error) {
            failure("route_sdk_error", "华为导航路线规划初始化失败");
        }
    }

    @Override public boolean startNavigation() {
        if (destroyed || mapNavi == null) return false;
        try {
            return mapNavi.startNavi(NaviMode.GPS);
        } catch (RuntimeException ignored) {
            return false;
        }
    }

    @Override public void updateLocation(LocationSample sample) {
        if (destroyed || mapNavi == null || sample == null) return;
        Location location = new Location("hms-location-foreground");
        location.setLatitude(sample.getPoint().getLatitude());
        location.setLongitude(sample.getPoint().getLongitude());
        location.setAccuracy(sample.getAccuracyMeters());
        location.setBearing(sample.getBearingDegrees());
        location.setSpeed(sample.getSpeedMetersPerSecond());
        location.setTime(sample.getCapturedAtMillis());
        try {
            // The second parameter is reserved by Navi Kit; external-location mode keeps SDK
            // location collection disabled while still allowing foreground turn guidance.
            mapNavi.updateExtraLocationData(location, -1d);
        } catch (RuntimeException ignored) {}
    }

    @Override public void stopNavigation() {
        if (mapNavi == null) return;
        try { mapNavi.stopLocation(); } catch (RuntimeException ignored) {}
        try { mapNavi.stopNavi(); } catch (RuntimeException ignored) {}
    }

    @Override public void destroy() {
        if (destroyed) return;
        destroyed = true;
        MapNavi current = mapNavi;
        mapNavi = null;
        if (current == null) return;
        try { current.stopLocation(); } catch (RuntimeException ignored) {}
        try { current.stopNavi(); } catch (RuntimeException ignored) {}
        if (mapListener != null) {
            try { current.removeMapNaviListener(mapListener); } catch (RuntimeException ignored) {}
        }
        mapListener = null;
        try { current.destroy(); } catch (RuntimeException ignored) {}
    }

    private MapNavi ensureInitialized() {
        if (mapNavi != null) return mapNavi;
        if (Looper.myLooper() != Looper.getMainLooper()) {
            throw new IllegalStateException("Navi Kit must initialize on the main thread");
        }
        MapNavi initialized = MapNavi.getInstance(applicationContext);
        initialized.setLocationContext(locationContext);
        initialized.setApiKey(BuildConfig.HMS_MAP_API_KEY);
        initialized.setDevServerSite(DevServerSiteConstant.DR1);
        initialized.setSendLocationListSwitch(false);
        initialized.setReportOMPSwitch(false);
        initialized.setTrajShareSwitch(false);
        initialized.setUseExtraLocationData(true);
        initialized.setUseExtraTTS(true);
        mapListener = createListener();
        if (!initialized.addMapNaviListener(mapListener)) {
            mapListener = null;
            throw new IllegalStateException("Could not register Navi listener");
        }
        mapNavi = initialized;
        return initialized;
    }

    private MapNaviListener createListener() {
        return (MapNaviListener) Proxy.newProxyInstance(
            MapNaviListener.class.getClassLoader(),
            new Class<?>[]{MapNaviListener.class},
            (proxy, method, args) -> {
                String name = method.getName();
                if ("equals".equals(name)) return proxy == (args == null ? null : args[0]);
                if ("hashCode".equals(name)) return System.identityHashCode(proxy);
                if ("toString".equals(name)) return "GovMapNaviListener";
                switch (name) {
                    case "onCalculateRouteSuccess":
                    case "onCalculateWalkRouteSuccess":
                        deliverRoute(args != null && args.length > 0 && args[0] instanceof int[]
                            ? (int[]) args[0] : new int[0]);
                        break;
                    case "onCalculateRouteFailure":
                    case "onCalculateWalkRouteFailure":
                        int error = args != null && args.length > 0 && args[0] instanceof Integer
                            ? (Integer) args[0] : -1;
                        failure("route_calculation_failed_" + error, "未能规划所选路线");
                        break;
                    case "onGetNavigationText":
                        if (args != null && args.length > 0 && args[0] instanceof NaviBroadInfo) {
                            instruction(((NaviBroadInfo) args[0]).getBroadString());
                        }
                        break;
                    case "onReCalculateRouteForYaw":
                        instruction("已偏离路线，正在重新规划");
                        break;
                    case "onDriveRoutesChanged":
                        deliverRoute(new int[0]);
                        break;
                    case "onStartNavi":
                        int startCode = args != null && args.length > 0 && args[0] instanceof Integer
                            ? (Integer) args[0] : -1;
                        if (startCode != 0) {
                            failure(
                                "navigation_start_failed_" + startCode,
                                "华为导航启动失败，请返回路线预览重试"
                            );
                        }
                        break;
                    case "onStartNaviSuccess":
                        dispatch(target -> target.onNavigationStarted());
                        break;
                    case "onArriveDestination":
                        dispatch(target -> target.onDestinationArrived());
                        break;
                    case "onAuthenticationFail":
                        failure("huawei_navi_authentication_failed", "华为导航鉴权失败");
                        break;
                    default:
                        break;
                }
                return defaultValue(method.getReturnType());
            }
        );
    }

    private void deliverRoute(int[] routeIds) {
        MapNavi current = mapNavi;
        if (current == null || destroyed) return;
        try {
            if (routeIds.length > 0) current.selectRouteId(routeIds[0]);
            MapNaviPath path = current.getNaviPath();
            if (path == null || path.getCoordList() == null || path.getCoordList().size() < 2) {
                failure("route_geometry_missing", "路线缺少可预览的轨迹");
                return;
            }
            List<GeoPoint> points = new ArrayList<>();
            for (NaviLatLng coordinate : path.getCoordList()) {
                if (coordinate != null && coordinate.isValid()) {
                    points.add(new GeoPoint(coordinate.getLatitude(), coordinate.getLongitude()));
                }
            }
            if (points.size() < 2) {
                failure("route_geometry_missing", "路线缺少可预览的轨迹");
                return;
            }
            RoutePreview preview = new RoutePreview(path.getAllLength(), path.getAllTime(), points);
            dispatch(target -> target.onRouteReady(preview));
        } catch (RuntimeException invalid) {
            failure("route_geometry_invalid", "无法读取华为导航路线");
        }
    }

    private static NaviRequestPoint point(GeoPoint coordinate) {
        NaviRequestPoint point = new NaviRequestPoint();
        point.setPoint(new NaviLatLng(coordinate.getLatitude(), coordinate.getLongitude()));
        return point;
    }

    private void instruction(String raw) {
        if (raw == null) return;
        String text = raw.replaceAll("[\\r\\n\\t]", " ").trim();
        if (text.isEmpty()) return;
        if (text.length() > 300) text = text.substring(0, 300);
        final String safe = text;
        dispatch(target -> target.onNavigationInstruction(safe));
    }

    private void failure(String code, String message) {
        dispatch(target -> target.onRouteFailure(code, message));
    }

    private void dispatch(java.util.function.Consumer<Listener> action) {
        main.post(() -> {
            Listener current = listener;
            if (!destroyed && current != null) action.accept(current);
        });
    }

    private static Object defaultValue(Class<?> type) {
        if (!type.isPrimitive() || type == Void.TYPE) return null;
        if (type == Boolean.TYPE) return false;
        if (type == Character.TYPE) return '\0';
        if (type == Byte.TYPE) return (byte) 0;
        if (type == Short.TYPE) return (short) 0;
        if (type == Integer.TYPE) return 0;
        if (type == Long.TYPE) return 0L;
        if (type == Float.TYPE) return 0f;
        if (type == Double.TYPE) return 0d;
        return null;
    }
}
