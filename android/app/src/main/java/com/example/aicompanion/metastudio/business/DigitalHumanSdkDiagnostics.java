package com.example.aicompanion.metastudio.business;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Set;

/** Fixed, non-sensitive SDK diagnostics accepted from the isolated wrapper. */
public final class DigitalHumanSdkDiagnostics {
    private static final String ERROR_PREFIX = "sdk_error_";
    private static final String MSS_STATUS_PREFIX = "sdk_error_mss_";
    private static final String READY_ENDPOINT_PREFIX = "ready_ws_";
    private static final String CSP_ENDPOINT_PREFIX = "csp_connect_";

    private static final Set<String> ENDPOINT_HOST_CATEGORIES = immutableSet(
        "meta", "client", "rtc", "huawei", "ip", "other"
    );
    private static final Set<String> ENDPOINT_PORT_CATEGORIES = immutableSet(
        "443", "6447", "other"
    );

    private static final Set<String> ERROR_CODES = immutableSet(
        "999000001", "999000002",
        "999100001", "999100002", "999100003", "999100004",
        "999100005", "999100006", "999100007", "999100008",
        "999200001", "999200002", "999200003", "999200004",
        "999200005", "999200006",
        "999300001", "999300002", "999300003", "999300004",
        "999400001", "999400002", "999400003", "999400004", "999400005",
        "90000001", "90000004", "90000005",
        "90100001", "90100002", "90100003", "90100004", "90100005",
        "90100006", "90100007", "90100008", "90100009", "90100010",
        "90100011", "90100012", "90100013", "90100014", "90100015",
        "90100016", "90100017", "90100018", "90100019", "90100020",
        "90100021", "90100022", "90100023", "90100024", "90100025",
        "90100026", "90100027", "90100028", "90100029", "90100030",
        "90100031", "90100032", "90100033", "90100034", "90100035",
        "90100036", "90100037", "90100038",
        "90100100", "90100200", "90100600", "4005"
    );

    private static final Set<String> MSS_ERROR_SUFFIXES = immutableSet(
        "00000001", "00000002", "00000003", "00000004",
        "47010001", "47010002", "47010003", "47010004", "47010005", "47010006",
        "47010007", "47010008", "47010009", "47010010", "47010011", "47010012",
        "47010013", "47010014", "47010015", "47010016", "47010020", "47010021",
        "47010022", "47010023", "47010024", "47010025", "47010026", "47010027",
        "47010028", "47010029", "47010030", "47010031", "47010032", "47010033",
        "47010034", "47010035", "47010036", "47010037", "47010038", "47010039",
        "47010040", "47010043", "47010044", "47010045", "47010046", "47010047",
        "47010048", "47010049", "47010050", "47010051", "47010063", "47010065",
        "47010066", "47010100", "47010101", "47010102", "47010103", "47010104",
        "47010105", "47010106", "47010107", "47010111", "47010119", "47010120",
        "47010121", "47010122", "47010124", "47010125", "47010126", "47010127",
        "47010128", "47010130", "47010131", "47010134", "47010136", "47010141",
        "47010143", "47010144", "47010145", "47010146", "47010147", "47010148",
        "47010150", "47010151", "47010152", "47010154", "47010155", "47010156",
        "47010157", "47010158", "47010163", "47015005", "47015006", "47015008",
        "47015009", "47015010", "47015011", "47015012", "47015015", "47015017",
        "47015018", "47015019", "47015028", "47015029", "47015030", "47015031"
    );

    private static final Set<String> WEBSOCKET_CODES = immutableSet(
        "999200001", "999200002", "999200003", "999200004", "999200005", "999200006",
        "90100008", "90100012", "90100013", "90100014", "90100015", "90100016",
        "90100034", "4005"
    );

    private static final Set<String> AUDIO_CODES = immutableSet(
        "999100004", "90100002", "90100003", "90100004", "90100005", "90100006",
        "90100017", "90100018", "90100019", "90100020", "90100021", "90100038"
    );

    private static final Set<String> UI_CODES = immutableSet(
        "999300001", "999300002", "999300003", "999300004"
    );

    private static final Set<String> STATE_CODES = immutableSet(
        "999000001", "999000002",
        "999400001", "999400002", "999400003", "999400004", "999400005"
    );

    private static final Set<String> MSS_WEBSOCKET_SUFFIXES = immutableSet(
        "47010100", "47010101", "47010102", "47010103", "47010104", "47010105",
        "47010106", "47010107", "47010111", "47015005", "47015006"
    );

    private static final Set<String> MSS_SIS_SUFFIXES = immutableSet(
        "47010141", "47010143", "47015015", "47015018", "47015019",
        "47015028", "47015029", "47015030", "47015031"
    );

    private DigitalHumanSdkDiagnostics() {}

    public static boolean isAllowedErrorStatus(String status) {
        return extractAllowedCode(status) != null || "sdk_error_unknown".equals(status);
    }

    public static boolean isAllowedEndpointStatus(String status) {
        return endpointParts(status) != null;
    }

    public static Set<String> allowedErrorStatuses() {
        Set<String> statuses = new HashSet<>();
        for (String code : ERROR_CODES) statuses.add(ERROR_PREFIX + code);
        for (String suffix : MSS_ERROR_SUFFIXES) statuses.add(MSS_STATUS_PREFIX + suffix);
        statuses.add("sdk_error_unknown");
        return Collections.unmodifiableSet(statuses);
    }

    public static String friendlyMessage(String status) {
        String endpointMessage = friendlyEndpointMessage(status);
        if (endpointMessage != null) return endpointMessage;
        if ("sdk_error_unknown".equals(status)) return "数字人服务异常（未识别的安全诊断类别）";
        String code = extractAllowedCode(status);
        if (code == null) return null;
        if (code.startsWith("MSS.")) {
            String suffix = code.substring(4);
            if (MSS_WEBSOCKET_SUFFIXES.contains(suffix)) {
                return "数字人服务端 WebSocket 通道异常（诊断码 " + code + "）";
            }
            if (MSS_SIS_SUFFIXES.contains(suffix)) {
                return "数字人 SIS 语音服务异常（诊断码 " + code + "）";
            }
            return "数字人云服务异常（诊断码 " + code + "）";
        }
        if (WEBSOCKET_CODES.contains(code)) return "数字人 WebSocket 通道异常（诊断码 " + code + "）";
        if (AUDIO_CODES.contains(code)) return "数字人音频设备异常（诊断码 " + code + "）";
        if (UI_CODES.contains(code)) return "数字人页面参数异常（诊断码 " + code + "）";
        if (STATE_CODES.contains(code)) return "数字人当前状态不允许此操作（诊断码 " + code + "）";
        return "数字人实时音视频服务异常（诊断码 " + code + "）";
    }

    private static String friendlyEndpointMessage(String status) {
        String[] parts = endpointParts(status);
        if (parts == null) return null;
        String hostLabel;
        switch (parts[1]) {
            case "meta": hostLabel = "MetaStudio API"; break;
            case "client": hostLabel = "MetaStudio Client"; break;
            case "rtc": hostLabel = "华为 RTC"; break;
            case "huawei": hostLabel = "其他华为云服务"; break;
            case "ip": hostLabel = "IP 地址"; break;
            default: hostLabel = "其他目标";
        }
        String portLabel = "other".equals(parts[2]) ? "其他" : parts[2];
        if ("ready".equals(parts[0])) {
            return "数字人已就绪（连接类别：" + hostLabel + "，端口：" + portLabel
                + "），请点击页面中的开始对话";
        }
        return "数字人连接被 CSP 安全策略拦截（目标类别：" + hostLabel
            + "，端口：" + portLabel + "）";
    }

    private static String[] endpointParts(String status) {
        if (status == null) return null;
        String kind;
        String remainder;
        if (status.startsWith(READY_ENDPOINT_PREFIX)) {
            kind = "ready";
            remainder = status.substring(READY_ENDPOINT_PREFIX.length());
        } else if (status.startsWith(CSP_ENDPOINT_PREFIX)) {
            kind = "csp";
            remainder = status.substring(CSP_ENDPOINT_PREFIX.length());
        } else {
            return null;
        }
        for (String host : ENDPOINT_HOST_CATEGORIES) {
            String prefix = host + "_";
            if (!remainder.startsWith(prefix)) continue;
            String port = remainder.substring(prefix.length());
            if (ENDPOINT_PORT_CATEGORIES.contains(port)) return new String[]{kind, host, port};
        }
        return null;
    }

    private static String extractAllowedCode(String status) {
        if (status != null && status.startsWith(MSS_STATUS_PREFIX)) {
            String suffix = status.substring(MSS_STATUS_PREFIX.length());
            return MSS_ERROR_SUFFIXES.contains(suffix) ? "MSS." + suffix : null;
        }
        if (status == null || !status.startsWith(ERROR_PREFIX)) return null;
        String code = status.substring(ERROR_PREFIX.length());
        return ERROR_CODES.contains(code) ? code : null;
    }

    private static Set<String> immutableSet(String... values) {
        return Collections.unmodifiableSet(new HashSet<>(Arrays.asList(values)));
    }
}
