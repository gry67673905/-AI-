package com.example.aicompanion.navigation.business;

import com.example.aicompanion.navigation.model.ServiceNavigationContract.GeoPoint;
import com.example.aicompanion.navigation.model.ServiceNavigationContract.WindowOption;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/** Sorts only in app memory; neither the backend query nor its logs receive the user's position. */
public final class NearbyWindowSelector {
    private static final double EARTH_RADIUS_METERS = 6_371_000d;

    public List<WindowOption> select(List<WindowOption> source, GeoPoint current, int limit) {
        List<WindowOption> sorted = new ArrayList<>(source == null
            ? java.util.Collections.emptyList() : source);
        Comparator<WindowOption> fallback = Comparator
            .comparingInt(WindowOption::getPriority)
            .thenComparing(WindowOption::getName)
            .thenComparing(WindowOption::getId);
        if (current == null) {
            sorted.sort(fallback);
        } else {
            sorted.sort(Comparator
                .comparingDouble((WindowOption item) -> distanceMeters(current, item.getPoint()))
                .thenComparing(fallback));
        }
        int safeLimit = Math.max(0, Math.min(limit, sorted.size()));
        return new ArrayList<>(sorted.subList(0, safeLimit));
    }

    public double distanceMeters(GeoPoint first, GeoPoint second) {
        double lat1 = Math.toRadians(first.getLatitude());
        double lat2 = Math.toRadians(second.getLatitude());
        double deltaLat = lat2 - lat1;
        double deltaLon = Math.toRadians(second.getLongitude() - first.getLongitude());
        double a = Math.sin(deltaLat / 2d) * Math.sin(deltaLat / 2d)
            + Math.cos(lat1) * Math.cos(lat2)
            * Math.sin(deltaLon / 2d) * Math.sin(deltaLon / 2d);
        return EARTH_RADIUS_METERS * 2d * Math.atan2(Math.sqrt(a), Math.sqrt(1d - a));
    }
}
