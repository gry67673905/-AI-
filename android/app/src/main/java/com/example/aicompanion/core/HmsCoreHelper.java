package com.example.aicompanion.core;

import android.app.Activity;
import android.content.Context;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;

import com.huawei.hms.api.ConnectionResult;
import com.huawei.hms.api.HuaweiApiAvailability;

public final class HmsCoreHelper {
    private static final String HMS_CORE_PACKAGE = "com.huawei.hwid";

    private HmsCoreHelper() {}

    public static int availability(Context context) {
        return HuaweiApiAvailability.getInstance().isHuaweiMobileServicesAvailable(context);
    }

    public static boolean isAvailable(Context context) {
        return availability(context) == ConnectionResult.SUCCESS;
    }

    public static String describe(Context context) {
        int code = availability(context);
        String version = installedVersion(context);
        return code == ConnectionResult.SUCCESS
            ? "HMS Core 可用" + (version.isEmpty() ? "" : "，版本 " + version)
            : "HMS Core 不可用，错误码 " + code + (version.isEmpty() ? "" : "，已安装版本 " + version);
    }

    public static void resolve(Activity activity, int requestCode) {
        int code = availability(activity);
        if (code != ConnectionResult.SUCCESS) {
            HuaweiApiAvailability.getInstance().getErrorDialog(activity, code, requestCode).show();
        }
    }

    private static String installedVersion(Context context) {
        try {
            PackageInfo info = context.getPackageManager().getPackageInfo(HMS_CORE_PACKAGE, 0);
            return info.versionName == null ? "" : info.versionName;
        } catch (PackageManager.NameNotFoundException ignored) {
            return "";
        }
    }
}

