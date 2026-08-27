package com.example.aicompanion.navigation.business;

import java.util.UUID;

/** The portal-to-native boundary accepts one canonical UUID and no destination data. */
public final class ServiceIdPolicy {
    public String normalize(String raw) {
        if (raw == null || !raw.equals(raw.trim()) || raw.length() != 36) return null;
        try {
            UUID parsed = UUID.fromString(raw);
            String canonical = parsed.toString();
            return canonical.equals(raw) ? canonical : null;
        } catch (IllegalArgumentException invalid) {
            return null;
        }
    }
}
