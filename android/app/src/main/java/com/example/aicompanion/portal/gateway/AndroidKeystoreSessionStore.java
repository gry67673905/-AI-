package com.example.aicompanion.portal.gateway;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;

import com.example.aicompanion.portal.model.PortalContract.SessionSecrets;
import com.example.aicompanion.portal.model.PortalContract.UserProfile;
import com.google.gson.Gson;

import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.security.KeyStore;

import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** AES-GCM storage backed by Android Keystore. SharedPreferences contains ciphertext only. */
public final class AndroidKeystoreSessionStore implements SecureSessionStore {
    private static final String STORE = "gov_portal_secure_session";
    private static final String VALUE = "encrypted_session_v1";
    private static final String KEY_ALIAS = "gov_portal_session_aes_v1";
    private static final String KEYSTORE = "AndroidKeyStore";
    private static final String TRANSFORMATION = "AES/GCM/NoPadding";
    private static final int GCM_TAG_BITS = 128;

    private final SharedPreferences preferences;
    private final Gson gson = new Gson();

    public AndroidKeystoreSessionStore(Context context) {
        preferences = context.getApplicationContext().getSharedPreferences(STORE, Context.MODE_PRIVATE);
    }

    @Override
    public synchronized Snapshot load() {
        String encoded = preferences.getString(VALUE, "");
        if (encoded == null || encoded.isEmpty()) return Snapshot.empty();
        try {
            byte[] combined = Base64.decode(encoded, Base64.NO_WRAP);
            if (combined.length < 13) throw new IllegalStateException("Invalid encrypted session");
            int ivLength = combined[0] & 0xff;
            if (ivLength < 12 || combined.length <= 1 + ivLength) throw new IllegalStateException("Invalid IV");
            byte[] iv = java.util.Arrays.copyOfRange(combined, 1, 1 + ivLength);
            byte[] encrypted = java.util.Arrays.copyOfRange(combined, 1 + ivLength, combined.length);
            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.DECRYPT_MODE, getOrCreateKey(), new GCMParameterSpec(GCM_TAG_BITS, iv));
            StoredSession stored = gson.fromJson(
                new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8),
                StoredSession.class
            );
            if (stored == null || stored.secrets == null || !stored.secrets.isComplete()) {
                clear();
                return Snapshot.empty();
            }
            return new Snapshot(stored.secrets, stored.profile);
        } catch (Exception ignored) {
            clear();
            return Snapshot.empty();
        }
    }

    @Override
    public synchronized void save(SessionSecrets secrets, UserProfile profile) {
        if (secrets == null || !secrets.isComplete()) throw new IllegalArgumentException("Incomplete session secrets");
        try {
            Cipher cipher = Cipher.getInstance(TRANSFORMATION);
            cipher.init(Cipher.ENCRYPT_MODE, getOrCreateKey());
            byte[] encrypted = cipher.doFinal(
                gson.toJson(new StoredSession(secrets, profile)).getBytes(StandardCharsets.UTF_8)
            );
            byte[] iv = cipher.getIV();
            byte[] combined = new byte[1 + iv.length + encrypted.length];
            combined[0] = (byte) iv.length;
            System.arraycopy(iv, 0, combined, 1, iv.length);
            System.arraycopy(encrypted, 0, combined, 1 + iv.length, encrypted.length);
            preferences.edit().putString(VALUE, Base64.encodeToString(combined, Base64.NO_WRAP)).apply();
        } catch (Exception error) {
            throw new IllegalStateException("无法安全保存登录会话", error);
        }
    }

    @Override
    public synchronized void clear() {
        preferences.edit().remove(VALUE).apply();
    }

    private static SecretKey getOrCreateKey() throws Exception {
        KeyStore keyStore = KeyStore.getInstance(KEYSTORE);
        keyStore.load(null);
        Key existing = keyStore.getKey(KEY_ALIAS, null);
        if (existing instanceof SecretKey) return (SecretKey) existing;

        KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, KEYSTORE);
        generator.init(new KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build());
        return generator.generateKey();
    }

    private static final class StoredSession {
        private SessionSecrets secrets;
        private UserProfile profile;

        @SuppressWarnings("unused")
        StoredSession() {}

        StoredSession(SessionSecrets secrets, UserProfile profile) {
            this.secrets = secrets;
            this.profile = profile;
        }
    }
}
