package com.example.aicompanion.portal.gateway;

import android.content.ContentResolver;
import android.content.Context;
import android.net.Uri;
import android.os.Bundle;

import com.example.aicompanion.BuildConfig;
import com.example.aicompanion.portal.model.PortalContract.ApplicantType;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;

import java.io.File;
import java.io.RandomAccessFile;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicBoolean;

/** Secure session IPC client shared by the main and isolated digital-human processes. */
public final class BrokeredSecureSessionStore implements CoordinatedSecureSessionStore {
    private static final Uri BROKER_URI = Uri.parse(
        "content://" + BuildConfig.APPLICATION_ID + ".secure-session-broker"
    );
    private static final Semaphore LOCAL_REFRESH_GATE = new Semaphore(1, true);

    private final ContentResolver resolver;
    private final File refreshLockFile;

    public BrokeredSecureSessionStore(Context context) {
        Context application = context.getApplicationContext();
        resolver = application.getContentResolver();
        refreshLockFile = new File(application.getNoBackupFilesDir(), "secure-session-refresh.lock");
    }

    @Override
    public synchronized Snapshot load() {
        try {
            Bundle result = resolver.call(
                BROKER_URI, SecureSessionBrokerProvider.METHOD_LOAD, null, null
            );
            if (result == null || !result.getBoolean(
                SecureSessionBrokerProvider.KEY_AUTHENTICATED, false
            )) {
                return Snapshot.empty();
            }
            SessionSecrets secrets = new SessionSecrets(
                result.getString(SecureSessionBrokerProvider.KEY_ACCESS_TOKEN, ""),
                result.getString(SecureSessionBrokerProvider.KEY_REFRESH_TOKEN, ""),
                result.getString(SecureSessionBrokerProvider.KEY_TOKEN_TYPE, "Bearer")
            );
            if (!secrets.isComplete()) return Snapshot.empty();
            UserProfile profile = new UserProfile(
                result.getString(SecureSessionBrokerProvider.KEY_PROFILE_ID, ""),
                result.getString(SecureSessionBrokerProvider.KEY_DISPLAY_NAME, ""),
                Role.fromWire(result.getString(SecureSessionBrokerProvider.KEY_ROLE, "ANONYMOUS")),
                ApplicantType.fromWire(result.getString(
                    SecureSessionBrokerProvider.KEY_APPLICANT_TYPE, "NONE"
                ))
            );
            return new Snapshot(secrets, profile);
        } catch (RuntimeException unavailable) {
            throw new IllegalStateException("Secure session broker is unavailable", unavailable);
        }
    }

    @Override
    public synchronized void save(SessionSecrets secrets, UserProfile profile) {
        if (secrets == null || !secrets.isComplete()) {
            throw new IllegalArgumentException("Incomplete session secrets");
        }
        UserProfile safeProfile = profile == null ? UserProfile.anonymous() : profile;
        Bundle payload = new Bundle();
        payload.putBoolean(SecureSessionBrokerProvider.KEY_AUTHENTICATED, true);
        payload.putString(SecureSessionBrokerProvider.KEY_ACCESS_TOKEN, secrets.getAccessToken());
        payload.putString(SecureSessionBrokerProvider.KEY_REFRESH_TOKEN, secrets.getRefreshToken());
        payload.putString(SecureSessionBrokerProvider.KEY_TOKEN_TYPE, secrets.getTokenType());
        payload.putString(SecureSessionBrokerProvider.KEY_PROFILE_ID, safeProfile.getId());
        payload.putString(SecureSessionBrokerProvider.KEY_DISPLAY_NAME, safeProfile.getDisplayName());
        payload.putString(SecureSessionBrokerProvider.KEY_ROLE, safeProfile.getRole().name());
        payload.putString(
            SecureSessionBrokerProvider.KEY_APPLICANT_TYPE,
            safeProfile.getApplicantType().name()
        );
        Bundle result = resolver.call(
            BROKER_URI, SecureSessionBrokerProvider.METHOD_SAVE, null, payload
        );
        if (result == null) throw new IllegalStateException("Secure session was not persisted");
    }

    @Override
    public synchronized void clear() {
        Bundle result = resolver.call(
            BROKER_URI, SecureSessionBrokerProvider.METHOD_CLEAR, null, null
        );
        if (result == null) throw new IllegalStateException("Secure session was not cleared");
    }

    @Override
    public RefreshLease acquireRefresh(Snapshot expected) {
        boolean localAcquired = false;
        RandomAccessFile file = null;
        FileChannel channel = null;
        FileLock lock = null;
        try {
            LOCAL_REFRESH_GATE.acquire();
            localAcquired = true;
            file = new RandomAccessFile(refreshLockFile, "rw");
            channel = file.getChannel();
            lock = channel.lock();
            Snapshot current = load();
            if (!sameRefreshToken(expected, current)) {
                closeResources(lock, channel, file, true);
                return new RefreshLease(false, current, null);
            }
            RefreshHandle handle = new RefreshHandle(
                expected.getSecrets().getRefreshToken(), lock, channel, file
            );
            return new RefreshLease(true, current, handle);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            closeResources(lock, channel, file, localAcquired);
            throw new IllegalStateException("Secure session refresh was interrupted", interrupted);
        } catch (Exception failure) {
            closeResources(lock, channel, file, localAcquired);
            throw new IllegalStateException("Secure session refresh lock is unavailable", failure);
        }
    }

    @Override
    public Snapshot completeRefresh(
        RefreshLease lease, SessionSecrets secrets, UserProfile profile
    ) {
        RefreshHandle handle = requireOwner(lease);
        try {
            Snapshot current = load();
            if (sameRefreshToken(handle.expectedRefreshToken, current)) {
                save(secrets, profile);
            }
            return load();
        } finally {
            handle.close();
        }
    }

    @Override
    public Snapshot failRefresh(RefreshLease lease, boolean invalidateCurrent) {
        RefreshHandle handle = requireOwner(lease);
        try {
            Snapshot current = load();
            if (invalidateCurrent && sameRefreshToken(handle.expectedRefreshToken, current)) {
                clear();
            }
            return load();
        } finally {
            handle.close();
        }
    }

    private static RefreshHandle requireOwner(RefreshLease lease) {
        if (lease == null || !lease.isOwner() || !(lease.getHandle() instanceof RefreshHandle)) {
            throw new IllegalArgumentException("Refresh lease is not owned by this process");
        }
        return (RefreshHandle) lease.getHandle();
    }

    private static boolean sameRefreshToken(Snapshot first, Snapshot second) {
        return first != null && first.isAuthenticated()
            && sameRefreshToken(first.getSecrets().getRefreshToken(), second);
    }

    private static boolean sameRefreshToken(String expected, Snapshot current) {
        if (expected == null || current == null || !current.isAuthenticated()) return false;
        return MessageDigest.isEqual(
            expected.getBytes(StandardCharsets.UTF_8),
            current.getSecrets().getRefreshToken().getBytes(StandardCharsets.UTF_8)
        );
    }

    private static void closeResources(
        FileLock lock, FileChannel channel, RandomAccessFile file, boolean releaseLocal
    ) {
        try { if (lock != null && lock.isValid()) lock.release(); } catch (Exception ignored) {}
        try { if (channel != null) channel.close(); } catch (Exception ignored) {}
        try { if (file != null) file.close(); } catch (Exception ignored) {}
        if (releaseLocal) LOCAL_REFRESH_GATE.release();
    }

    private static final class RefreshHandle {
        private final String expectedRefreshToken;
        private final FileLock lock;
        private final FileChannel channel;
        private final RandomAccessFile file;
        private final AtomicBoolean closed = new AtomicBoolean();

        RefreshHandle(
            String expectedRefreshToken, FileLock lock, FileChannel channel, RandomAccessFile file
        ) {
            this.expectedRefreshToken = expectedRefreshToken;
            this.lock = lock;
            this.channel = channel;
            this.file = file;
        }

        void close() {
            if (closed.compareAndSet(false, true)) {
                closeResources(lock, channel, file, true);
            }
        }
    }
}
