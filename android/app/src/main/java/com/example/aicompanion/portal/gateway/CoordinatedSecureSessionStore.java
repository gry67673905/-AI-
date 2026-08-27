package com.example.aicompanion.portal.gateway;

import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;

/** Serializes one-use refresh-token rotation across native application processes. */
public interface CoordinatedSecureSessionStore extends SecureSessionStore {
    RefreshLease acquireRefresh(Snapshot expected);
    Snapshot completeRefresh(RefreshLease lease, SessionSecrets secrets, UserProfile profile);
    Snapshot failRefresh(RefreshLease lease, boolean invalidateCurrent);

    final class RefreshLease {
        private final boolean owner;
        private final Snapshot snapshot;
        private final Object handle;

        RefreshLease(boolean owner, Snapshot snapshot, Object handle) {
            this.owner = owner;
            this.snapshot = snapshot == null ? Snapshot.empty() : snapshot;
            this.handle = handle;
        }

        public boolean isOwner() { return owner; }
        public Snapshot getSnapshot() { return snapshot; }
        Object getHandle() { return handle; }
    }
}
