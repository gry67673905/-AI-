package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;

/** Native-only encrypted session persistence. */
public interface SecureSessionStore {
    Snapshot load();
    void save(SessionSecrets secrets, UserProfile profile);
    void clear();

    final class Snapshot {
        private final SessionSecrets secrets;
        private final UserProfile profile;

        public Snapshot(SessionSecrets secrets, UserProfile profile) {
            this.secrets = secrets;
            this.profile = profile;
        }

        public static Snapshot empty() { return new Snapshot(null, UserProfile.anonymous()); }
        public SessionSecrets getSecrets() { return secrets; }
        public UserProfile getProfile() { return profile == null ? UserProfile.anonymous() : profile; }
        public boolean isAuthenticated() { return secrets != null && secrets.isComplete(); }
    }
}
