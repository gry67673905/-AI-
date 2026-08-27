package com.example.aicompanion.portal.gateway;

import android.content.ContentProvider;
import android.content.ContentValues;
import android.database.Cursor;
import android.net.Uri;
import android.os.Binder;
import android.os.Bundle;
import android.os.Process;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.example.aicompanion.portal.model.PortalContract.ApplicantType;
import com.example.aicompanion.portal.model.PortalContract.Role;
import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;

/**
 * Same-application IPC boundary for the encrypted native session.
 *
 * <p>The provider always runs in the default application process. This avoids using
 * SharedPreferences as a cross-process coherence mechanism while keeping tokens out of
 * Intent extras, WebView code, URLs, and logs.</p>
 */
public final class SecureSessionBrokerProvider extends ContentProvider {
    static final String METHOD_LOAD = "load";
    static final String METHOD_SAVE = "save";
    static final String METHOD_CLEAR = "clear";
    static final String KEY_AUTHENTICATED = "authenticated";
    static final String KEY_ACCESS_TOKEN = "access_token";
    static final String KEY_REFRESH_TOKEN = "refresh_token";
    static final String KEY_TOKEN_TYPE = "token_type";
    static final String KEY_PROFILE_ID = "profile_id";
    static final String KEY_DISPLAY_NAME = "display_name";
    static final String KEY_ROLE = "role";
    static final String KEY_APPLICANT_TYPE = "applicant_type";

    private AndroidKeystoreSessionStore store;

    @Override
    public boolean onCreate() {
        if (getContext() == null) return false;
        store = new AndroidKeystoreSessionStore(getContext().getApplicationContext());
        return true;
    }

    @Nullable
    @Override
    public Bundle call(@NonNull String method, @Nullable String arg, @Nullable Bundle extras) {
        enforceSameApplication();
        if (store == null) throw new IllegalStateException("Secure session broker is unavailable");
        switch (method) {
            case METHOD_LOAD:
                return encode(store.load());
            case METHOD_SAVE:
                if (extras == null) throw new IllegalArgumentException("Missing secure session payload");
                store.save(decodeSecrets(extras), decodeProfile(extras));
                return Bundle.EMPTY;
            case METHOD_CLEAR:
                store.clear();
                return Bundle.EMPTY;
            default:
                throw new IllegalArgumentException("Unsupported secure session operation");
        }
    }

    private static Bundle encode(SecureSessionStore.Snapshot snapshot) {
        Bundle result = new Bundle();
        result.putBoolean(KEY_AUTHENTICATED, snapshot.isAuthenticated());
        UserProfile profile = snapshot.getProfile();
        result.putString(KEY_PROFILE_ID, profile.getId());
        result.putString(KEY_DISPLAY_NAME, profile.getDisplayName());
        result.putString(KEY_ROLE, profile.getRole().name());
        result.putString(KEY_APPLICANT_TYPE, profile.getApplicantType().name());
        if (snapshot.isAuthenticated()) {
            SessionSecrets secrets = snapshot.getSecrets();
            result.putString(KEY_ACCESS_TOKEN, secrets.getAccessToken());
            result.putString(KEY_REFRESH_TOKEN, secrets.getRefreshToken());
            result.putString(KEY_TOKEN_TYPE, secrets.getTokenType());
        }
        return result;
    }

    private static SessionSecrets decodeSecrets(Bundle source) {
        SessionSecrets secrets = new SessionSecrets(
            source.getString(KEY_ACCESS_TOKEN, ""),
            source.getString(KEY_REFRESH_TOKEN, ""),
            source.getString(KEY_TOKEN_TYPE, "Bearer")
        );
        if (!source.getBoolean(KEY_AUTHENTICATED, false) || !secrets.isComplete()) {
            throw new IllegalArgumentException("Incomplete secure session payload");
        }
        return secrets;
    }

    private static UserProfile decodeProfile(Bundle source) {
        return new UserProfile(
            source.getString(KEY_PROFILE_ID, ""),
            source.getString(KEY_DISPLAY_NAME, ""),
            Role.fromWire(source.getString(KEY_ROLE, "ANONYMOUS")),
            ApplicantType.fromWire(source.getString(KEY_APPLICANT_TYPE, "NONE"))
        );
    }

    private static void enforceSameApplication() {
        if (Binder.getCallingUid() != Process.myUid()) {
            throw new SecurityException("Secure session broker is same-application only");
        }
    }

    @Nullable @Override public Cursor query(@NonNull Uri uri, @Nullable String[] projection,
        @Nullable String selection, @Nullable String[] selectionArgs, @Nullable String sortOrder) {
        throw new UnsupportedOperationException("Queries are not supported");
    }
    @Nullable @Override public String getType(@NonNull Uri uri) { return null; }
    @Nullable @Override public Uri insert(@NonNull Uri uri, @Nullable ContentValues values) {
        throw new UnsupportedOperationException("Inserts are not supported");
    }
    @Override public int delete(@NonNull Uri uri, @Nullable String selection,
        @Nullable String[] selectionArgs) {
        throw new UnsupportedOperationException("Deletes are not supported");
    }
    @Override public int update(@NonNull Uri uri, @Nullable ContentValues values,
        @Nullable String selection, @Nullable String[] selectionArgs) {
        throw new UnsupportedOperationException("Updates are not supported");
    }
}
