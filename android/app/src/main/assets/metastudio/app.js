(() => {
    'use strict';

    const EXPECTED_SERVER = 'metastudio-api.cn-north-4.myhuaweicloud.com';
    const METASTUDIO_CLIENT = 'metastudio-client.cn-north-4.myhuaweicloud.com';
    const ID = /^[A-Za-z0-9._:-]{1,256}$/;
    const RTC_SUFFIXES = Object.freeze([
        '.dbankcdn.com', '.dbankcdn.cn', '.dbankcloud.ru', '.dbankcloud.cn',
        '.dbankcloud.com', '.hicloud.cn', '.hicloud.com', '.dbankedge.cn'
    ]);
    const SDK_ERROR_STATUS_BY_CODE = Object.freeze({
        '999000001': 'sdk_error_999000001',
        '999000002': 'sdk_error_999000002',
        '999100001': 'sdk_error_999100001',
        '999100002': 'sdk_error_999100002',
        '999100003': 'sdk_error_999100003',
        '999100004': 'sdk_error_999100004',
        '999100005': 'sdk_error_999100005',
        '999100006': 'sdk_error_999100006',
        '999100007': 'sdk_error_999100007',
        '999100008': 'sdk_error_999100008',
        '999200001': 'sdk_error_999200001',
        '999200002': 'sdk_error_999200002',
        '999200003': 'sdk_error_999200003',
        '999200004': 'sdk_error_999200004',
        '999200005': 'sdk_error_999200005',
        '999200006': 'sdk_error_999200006',
        '999300001': 'sdk_error_999300001',
        '999300002': 'sdk_error_999300002',
        '999300003': 'sdk_error_999300003',
        '999300004': 'sdk_error_999300004',
        '999400001': 'sdk_error_999400001',
        '999400002': 'sdk_error_999400002',
        '999400003': 'sdk_error_999400003',
        '999400004': 'sdk_error_999400004',
        '999400005': 'sdk_error_999400005',
        '90000001': 'sdk_error_90000001',
        '90000004': 'sdk_error_90000004',
        '90000005': 'sdk_error_90000005',
        '90100001': 'sdk_error_90100001',
        '90100002': 'sdk_error_90100002',
        '90100003': 'sdk_error_90100003',
        '90100004': 'sdk_error_90100004',
        '90100005': 'sdk_error_90100005',
        '90100006': 'sdk_error_90100006',
        '90100007': 'sdk_error_90100007',
        '90100008': 'sdk_error_90100008',
        '90100009': 'sdk_error_90100009',
        '90100010': 'sdk_error_90100010',
        '90100011': 'sdk_error_90100011',
        '90100012': 'sdk_error_90100012',
        '90100013': 'sdk_error_90100013',
        '90100014': 'sdk_error_90100014',
        '90100015': 'sdk_error_90100015',
        '90100016': 'sdk_error_90100016',
        '90100017': 'sdk_error_90100017',
        '90100018': 'sdk_error_90100018',
        '90100019': 'sdk_error_90100019',
        '90100020': 'sdk_error_90100020',
        '90100021': 'sdk_error_90100021',
        '90100022': 'sdk_error_90100022',
        '90100023': 'sdk_error_90100023',
        '90100024': 'sdk_error_90100024',
        '90100025': 'sdk_error_90100025',
        '90100026': 'sdk_error_90100026',
        '90100027': 'sdk_error_90100027',
        '90100028': 'sdk_error_90100028',
        '90100029': 'sdk_error_90100029',
        '90100030': 'sdk_error_90100030',
        '90100031': 'sdk_error_90100031',
        '90100032': 'sdk_error_90100032',
        '90100033': 'sdk_error_90100033',
        '90100034': 'sdk_error_90100034',
        '90100035': 'sdk_error_90100035',
        '90100036': 'sdk_error_90100036',
        '90100037': 'sdk_error_90100037',
        '90100038': 'sdk_error_90100038',
        '90100100': 'sdk_error_90100100',
        '90100200': 'sdk_error_90100200',
        '90100600': 'sdk_error_90100600',
        '4005': 'sdk_error_4005'
    });
    const MSS_ERROR_SUFFIXES = new Set([
        '00000001', '00000002', '00000003', '00000004',
        '47010001', '47010002', '47010003', '47010004', '47010005', '47010006',
        '47010007', '47010008', '47010009', '47010010', '47010011', '47010012',
        '47010013', '47010014', '47010015', '47010016', '47010020', '47010021',
        '47010022', '47010023', '47010024', '47010025', '47010026', '47010027',
        '47010028', '47010029', '47010030', '47010031', '47010032', '47010033',
        '47010034', '47010035', '47010036', '47010037', '47010038', '47010039',
        '47010040', '47010043', '47010044', '47010045', '47010046', '47010047',
        '47010048', '47010049', '47010050', '47010051', '47010063', '47010065',
        '47010066', '47010100', '47010101', '47010102', '47010103', '47010104',
        '47010105', '47010106', '47010107', '47010111', '47010119', '47010120',
        '47010121', '47010122', '47010124', '47010125', '47010126', '47010127',
        '47010128', '47010130', '47010131', '47010134', '47010136', '47010141',
        '47010143', '47010144', '47010145', '47010146', '47010147', '47010148',
        '47010150', '47010151', '47010152', '47010154', '47010155', '47010156',
        '47010157', '47010158', '47010163', '47015005', '47015006', '47015008',
        '47015009', '47015010', '47015011', '47015012', '47015015', '47015017',
        '47015018', '47015019', '47015028', '47015029', '47015030', '47015031'
    ]);
    let taskCreated = false;

    const nativePort = () => window.GovDigitalHumanNative;
    const post = (payload) => {
        const port = nativePort();
        if (!port || typeof port.postMessage !== 'function') return false;
        port.postMessage(JSON.stringify(payload));
        return true;
    };
    const status = (value) => post({event: 'sdk_status', status: value});
    const gate = (message, state) => {
        document.getElementById('hard-gate-message').textContent = message;
        document.getElementById('hard-gate').hidden = false;
        status(state);
    };

    const extractIntent = (answer) => {
        if (!answer || answer.isLast !== true || !ID.test(String(answer.chatId || ''))) return null;
        let extension = answer.extendParam;
        if (typeof extension === 'string') {
            try { extension = JSON.parse(extension); } catch (_) { return null; }
        }
        if (!extension || typeof extension !== 'object' || Array.isArray(extension)) return null;
        const intentId = String(extension.intent_id || '');
        if (!ID.test(intentId) || extension.requires_confirmation !== true) return null;
        return {
            event: 'semantic_final',
            chat_id: String(answer.chatId),
            intent_id: intentId,
            is_last: true
        };
    };

    const safeSdkErrorStatus = (error) => {
        try {
            if (!error || typeof error !== 'object' || Array.isArray(error)) {
                return 'sdk_error_unknown';
            }
            const candidate = Object.prototype.hasOwnProperty.call(error, 'code')
                ? error.code : error.errorCode;
            let code = '';
            if (typeof candidate === 'string') code = candidate;
            if (typeof candidate === 'number' && Number.isSafeInteger(candidate)) code = String(candidate);
            if (/^MSS\.[0-9]{8}$/.test(code)) {
                const suffix = code.substring(4);
                return MSS_ERROR_SUFFIXES.has(suffix)
                    ? `sdk_error_mss_${suffix}` : 'sdk_error_unknown';
            }
            if (!(/^[0-9]{8,9}$/.test(code) || code === '4005')) {
                return 'sdk_error_unknown';
            }
            return SDK_ERROR_STATUS_BY_CODE[code] || 'sdk_error_unknown';
        } catch (_) {
            return 'sdk_error_unknown';
        }
    };

    const isIpLiteral = (host) => {
        const unwrapped = host.startsWith('[') && host.endsWith(']')
            ? host.substring(1, host.length - 1) : host;
        if (unwrapped.includes(':')) return /^[0-9a-f:.]+$/i.test(unwrapped);
        if (!/^[0-9]{1,3}(?:\.[0-9]{1,3}){3}$/.test(unwrapped)) return false;
        return unwrapped.split('.').every((part) => Number(part) <= 255);
    };

    const safeEndpointCategory = (rawAddress) => {
        try {
            if (typeof rawAddress !== 'string') return 'other_other';
            const address = rawAddress.trim();
            if (!address || address.length > 2048) return 'other_other';
            const hasExplicitScheme = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(address);
            // The provider may return a bare Domain:port value. The prefix is
            // used for parsing only and is never used for a network request.
            const parsed = new URL(hasExplicitScheme ? address : `wss://${address}`);
            const host = parsed.hostname.toLowerCase().replace(/\.$/, '');
            let hostCategory = 'other';
            if (host === EXPECTED_SERVER) {
                hostCategory = 'meta';
            } else if (host === METASTUDIO_CLIENT) {
                hostCategory = 'client';
            } else if (RTC_SUFFIXES.some((suffix) =>
                host.endsWith(suffix) && host.length > suffix.length)) {
                hostCategory = 'rtc';
            } else if (isIpLiteral(host)) {
                hostCategory = 'ip';
            } else if (host === 'myhuaweicloud.com' || host.endsWith('.myhuaweicloud.com')) {
                hostCategory = 'huawei';
            }
            const inferredPort = parsed.port
                || ((parsed.protocol === 'wss:' || parsed.protocol === 'https:') ? '443' : '');
            const portCategory = inferredPort === '443' || inferredPort === '6447'
                ? inferredPort : 'other';
            return `${hostCategory}_${portCategory}`;
        } catch (_) {
            return 'other_other';
        }
    };

    const safeWebsocketStatus = (job) => {
        const address = job && typeof job.websocketAddr === 'string' ? job.websocketAddr : '';
        return `ready_ws_${safeEndpointCategory(address)}`;
    };

    const eventListeners = Object.freeze({
        error: (error) => status(safeSdkErrorStatus(error)),
        jobInfoChange: (job) => {
            // create() may resolve even when parameter or onceCode validation
            // fails. Only the provider's ready event with a concrete job ID is
            // authoritative.
            if (job && job.isReady === true && ID.test(String(job.jobId || ''))) {
                status(safeWebsocketStatus(job));
            }
        },
        enterActive: () => status('active'),
        jobEnd: () => status('ended'),
        semanticRecognized: (answer) => {
            const intent = extractIntent(answer);
            if (intent) post(intent);
        }
    });

    const createTask = async (session) => {
        if (taskCreated) return;
        if (!session || session.type !== 'client_session'
            || session.server_address !== EXPECTED_SERVER
            || !ID.test(String(session.session_id || ''))
            || !/^[A-Za-z0-9_-]{1,128}$/.test(String(session.robot_id || ''))
            || typeof session.once_code !== 'string'
            || session.once_code.length < 8 || session.once_code.length > 4096) {
            gate('后端返回的数字人启动包未通过校验。', 'error');
            return;
        }
        taskCreated = true;
        status('creating');
        const launch = {
            serverAddress: EXPECTED_SERVER,
            onceCode: session.once_code,
            robotId: session.robot_id,
            containerId: 'ics-sdk',
            logLevel: 'none',
            // MetaStudio echoes this opaque client identifier to the LLM
            // callback as extend_param.client_id.  It is the only link to the
            // short-lived server-side session; no JWT or account data enters
            // the WebView or Huawei callback payload.
            extendParamStr: JSON.stringify({client_id: String(session.session_id)}),
            config: {enableCaption: true, enableChatBtn: true},
            eventListeners
        };
        session.once_code = '';
        try {
            await window.HwICSUiSdk.create(launch);
            launch.onceCode = '';
        } catch (_) {
            launch.onceCode = '';
            taskCreated = false;
            gate('无法创建 MetaStudio 数字人交互任务。', 'error');
        }
    };

    if (nativePort() && typeof nativePort().addEventListener === 'function') {
        nativePort().addEventListener('message', (event) => {
            if (typeof event.data !== 'string') return;
            let session;
            try { session = JSON.parse(event.data); } catch (_) { return; }
            void createTask(session);
        });
    } else if (nativePort()) {
        nativePort().onmessage = (event) => {
            if (!event || typeof event.data !== 'string') return;
            let session;
            try { session = JSON.parse(event.data); } catch (_) { return; }
            void createTask(session);
        };
    }

    document.getElementById('close-button').addEventListener('click', () => post({event: 'close'}));

    window.addEventListener('securitypolicyviolation', (event) => {
        try {
            if (!event || event.effectiveDirective !== 'connect-src') return;
            const address = typeof event.blockedURI === 'string' ? event.blockedURI : '';
            status(`csp_connect_${safeEndpointCategory(address)}`);
        } catch (_) {
            status('csp_connect_other_other');
        }
    });

    const bootstrap = async () => {
        if (!post({event: 'sdk_status', status: 'checking_browser'})) {
            document.getElementById('hard-gate-message').textContent = '安全原生消息通道不可用。';
            document.getElementById('hard-gate').hidden = false;
            return;
        }
        if (!window.HwICSUiSdk || typeof window.HwICSUiSdk.checkBrowserSupport !== 'function'
            || typeof window.HwICSUiSdk.create !== 'function') {
            gate('MetaStudio Web SDK 5.0.6 未正确加载。', 'sdk_missing');
            return;
        }
        status('checking_browser');
        try {
            const supported = await window.HwICSUiSdk.checkBrowserSupport();
            if (!supported) {
                gate('当前 Android System WebView 未通过 MetaStudio 兼容性检查。', 'unsupported');
                return;
            }
            post({event: 'page_ready'});
        } catch (_) {
            gate('无法完成 MetaStudio 浏览器兼容性检查。', 'error');
        }
    };

    window.addEventListener('pagehide', () => {
        if (taskCreated && window.HwICSUiSdk && typeof window.HwICSUiSdk.destroy === 'function') {
            try { void window.HwICSUiSdk.destroy(); } catch (_) { /* no secret or error forwarding */ }
        }
    });

    void bootstrap();
})();
