package com.example.aicompanion.navigation.model;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Immutable, Android-free models shared by the gateway, controller and local JVM tests. */
public final class ServiceNavigationContract {
    private ServiceNavigationContract() {}

    public enum TravelMode { DRIVING, WALKING }

    public static final class GeoPoint {
        private final double latitude;
        private final double longitude;

        public GeoPoint(double latitude, double longitude) {
            if (!Double.isFinite(latitude) || !Double.isFinite(longitude)
                || latitude < -90d || latitude > 90d || longitude < -180d || longitude > 180d) {
                throw new IllegalArgumentException("Invalid coordinate");
            }
            this.latitude = latitude;
            this.longitude = longitude;
        }

        public double getLatitude() { return latitude; }
        public double getLongitude() { return longitude; }
    }

    public static final class LocationSample {
        private final GeoPoint point;
        private final float accuracyMeters;
        private final float bearingDegrees;
        private final float speedMetersPerSecond;
        private final long capturedAtMillis;

        public LocationSample(
            GeoPoint point,
            float accuracyMeters,
            float bearingDegrees,
            float speedMetersPerSecond,
            long capturedAtMillis
        ) {
            if (point == null) throw new IllegalArgumentException("Location point is required");
            this.point = point;
            this.accuracyMeters = finiteOrZero(accuracyMeters);
            this.bearingDegrees = finiteOrZero(bearingDegrees);
            this.speedMetersPerSecond = finiteOrZero(speedMetersPerSecond);
            this.capturedAtMillis = Math.max(0L, capturedAtMillis);
        }

        private static float finiteOrZero(float value) { return Float.isFinite(value) ? value : 0f; }
        public GeoPoint getPoint() { return point; }
        public float getAccuracyMeters() { return accuracyMeters; }
        public float getBearingDegrees() { return bearingDegrees; }
        public float getSpeedMetersPerSecond() { return speedMetersPerSecond; }
        public long getCapturedAtMillis() { return capturedAtMillis; }
    }

    public static final class ServiceSummary {
        private final String id;
        private final String code;
        private final String name;
        private final String handlingMode;
        private final String onlineStatus;
        private final String statusReason;
        private final String statusUpdatedAt;

        public ServiceSummary(
            String id,
            String code,
            String name,
            String handlingMode,
            String onlineStatus,
            String statusReason,
            String statusUpdatedAt
        ) {
            this.id = clean(id);
            this.code = clean(code);
            this.name = clean(name);
            this.handlingMode = clean(handlingMode);
            this.onlineStatus = clean(onlineStatus);
            this.statusReason = clean(statusReason);
            this.statusUpdatedAt = clean(statusUpdatedAt);
        }

        public String getId() { return id; }
        public String getCode() { return code; }
        public String getName() { return name; }
        public String getHandlingMode() { return handlingMode; }
        public String getOnlineStatus() { return onlineStatus; }
        public String getStatusReason() { return statusReason; }
        public String getStatusUpdatedAt() { return statusUpdatedAt; }
    }

    public static final class WindowOption {
        private final String id;
        private final String code;
        private final String name;
        private final String address;
        private final String openingHours;
        private final GeoPoint point;
        private final String coordinateType;
        private final int priority;
        private final String dataMode;
        private final String cityCode;
        private final String sourceReference;
        private final String verifiedAt;

        public WindowOption(
            String id,
            String code,
            String name,
            String address,
            String openingHours,
            GeoPoint point,
            String coordinateType,
            int priority,
            String dataMode,
            String cityCode,
            String sourceReference,
            String verifiedAt
        ) {
            if (point == null) throw new IllegalArgumentException("Window coordinate is required");
            this.id = clean(id);
            this.code = clean(code);
            this.name = clean(name);
            this.address = clean(address);
            this.openingHours = clean(openingHours);
            this.point = point;
            this.coordinateType = clean(coordinateType).toUpperCase(java.util.Locale.ROOT);
            this.priority = priority;
            this.dataMode = clean(dataMode).toUpperCase(java.util.Locale.ROOT);
            this.cityCode = clean(cityCode);
            this.sourceReference = clean(sourceReference);
            this.verifiedAt = clean(verifiedAt);
        }

        public String getId() { return id; }
        public String getCode() { return code; }
        public String getName() { return name; }
        public String getAddress() { return address; }
        public String getOpeningHours() { return openingHours; }
        public GeoPoint getPoint() { return point; }
        public String getCoordinateType() { return coordinateType; }
        public int getPriority() { return priority; }
        public String getDataMode() { return dataMode; }
        public String getCityCode() { return cityCode; }
        public String getSourceReference() { return sourceReference; }
        public String getVerifiedAt() { return verifiedAt; }
        public boolean isDemo() { return "DEMO".equals(dataMode); }
    }

    public static final class NavigationOptions {
        private final ServiceSummary service;
        private final List<WindowOption> windows;
        private final boolean demoOnly;
        private final String notice;

        public NavigationOptions(
            ServiceSummary service,
            List<WindowOption> windows,
            boolean demoOnly,
            String notice
        ) {
            if (service == null) throw new IllegalArgumentException("Service is required");
            this.service = service;
            this.windows = Collections.unmodifiableList(new ArrayList<>(
                windows == null ? Collections.emptyList() : windows
            ));
            this.demoOnly = demoOnly;
            this.notice = clean(notice);
        }

        public ServiceSummary getService() { return service; }
        public List<WindowOption> getWindows() { return windows; }
        public boolean isDemoOnly() { return demoOnly; }
        public String getNotice() { return notice; }
    }

    public static final class RouteRequest {
        private final LocationSample origin;
        private final WindowOption destination;
        private final TravelMode mode;

        public RouteRequest(LocationSample origin, WindowOption destination, TravelMode mode) {
            if (origin == null || destination == null || mode == null) {
                throw new IllegalArgumentException("Complete route request is required");
            }
            this.origin = origin;
            this.destination = destination;
            this.mode = mode;
        }

        public LocationSample getOrigin() { return origin; }
        public WindowOption getDestination() { return destination; }
        public TravelMode getMode() { return mode; }
    }

    public static final class RoutePreview {
        private final int distanceMeters;
        private final int durationSeconds;
        private final List<GeoPoint> points;

        public RoutePreview(int distanceMeters, int durationSeconds, List<GeoPoint> points) {
            this.distanceMeters = Math.max(0, distanceMeters);
            this.durationSeconds = Math.max(0, durationSeconds);
            this.points = Collections.unmodifiableList(new ArrayList<>(
                points == null ? Collections.emptyList() : points
            ));
        }

        public int getDistanceMeters() { return distanceMeters; }
        public int getDurationSeconds() { return durationSeconds; }
        public List<GeoPoint> getPoints() { return points; }
    }

    private static String clean(String value) {
        return value == null ? "" : value.replaceAll("[\\r\\n\\t]", " ").trim();
    }
}
