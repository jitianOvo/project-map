package me.jitian.projectmap;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

final class LoginVault {
    private static final String ALIAS = "ProjectMap.Login.v1";
    private final SharedPreferences preferences;

    LoginVault(Context context) {
        preferences = context.getSharedPreferences("project-map-login", Context.MODE_PRIVATE);
    }

    private String reference(String endpoint) throws Exception {
        return Base64.encodeToString(MessageDigest.getInstance("SHA-256").digest(endpoint.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
    }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(ALIAS, null);
    }

    synchronized boolean save(String endpoint, String account) throws Exception {
        if (account.length() > 4096 || new JSONObject(account).has("password")) throw new Exception("登录数据无效");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        cipher.updateAAD(endpoint.getBytes(StandardCharsets.UTF_8));
        JSONObject encrypted = new JSONObject()
            .put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP))
            .put("data", Base64.encodeToString(cipher.doFinal(account.getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP));
        return preferences.edit().putString(reference(endpoint), encrypted.toString()).commit();
    }

    synchronized String read(String endpoint) throws Exception {
        String value = preferences.getString(reference(endpoint), "");
        if (value.isEmpty()) return "{}";
        JSONObject encrypted = new JSONObject(value);
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(encrypted.getString("iv"), Base64.NO_WRAP)));
        cipher.updateAAD(endpoint.getBytes(StandardCharsets.UTF_8));
        return new String(cipher.doFinal(Base64.decode(encrypted.getString("data"), Base64.NO_WRAP)), StandardCharsets.UTF_8);
    }

    synchronized boolean clear(String endpoint) throws Exception {
        return preferences.edit().remove(reference(endpoint)).commit();
    }
}
