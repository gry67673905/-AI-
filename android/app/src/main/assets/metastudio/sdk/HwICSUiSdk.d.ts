export declare class HwICSUiSdk {
    static version: string;
    static buildTime: string;
    static checkBrowserSupport(strictCheckBrowser?: boolean): Promise<boolean>;
    static checkTransparentBgSupport(): Promise<boolean>;
    static create(param: CreateParam): Promise<void>;
    static setConfig(config: ConfigMap): Promise<void>;
    static setLogLevel(logLevel: LogLevel): void;
    static addEventListeners(eventMap: EventMap): void;
    static destroy(): Promise<void>;
    static getJobInfo(): Promise<JobInfo>;
    static startSpeak(): Promise<UISdkResult>;
    static stopSpeak(): Promise<UISdkResult>;
    static startUserSpeak(param?: StartUserSpeakParam): Promise<UISdkResult>;
    static stopUserSpeak(): Promise<UISdkResult>;
    static unmuteRemoteAudio(): Promise<boolean>;
    static muteRemoteAudio(): Promise<boolean>;
    static interruptSpeaking(): Promise<UISdkResult>;
    static sendTextQuestion(param: TextQuestionParam): Promise<TextQuestionResult>;
    static startChat(param: {
        interactionMode: InteractionMode;
        wakeupType?: WakeupType;
        preCheckPermissions?: boolean;
    }): Promise<ChatResult>;
    static stopChat(): Promise<ChatResult>;
    static activeInteractionMode(): Promise<InteractionModeResult>;
    static interactionModeSwitch(param: {
        interactionMode: InteractionMode;
    }): Promise<InteractionModeResult>;
    static getLanguageInfo(): LanguageInfo;
    static changeLanguage(param: {
        langCode: LanguageCode;
    }): Promise<UISdkResult>;
    static sendDrivenText(param: TextDrivenParam): Promise<ChatResult>;
    static startLocalWakeupRecord(): Promise<void>;
    static stopLocalWakeupRecord(): Promise<void>;
    static initResourcePath(param: ResourcePath): Promise<void>;
    static setThirdPartyConfig(config: ThirdPartyConfig): Promise<UISdkResult>;
    static sendCustomLocalAudio(audioData: AudioData): Promise<void>;
    static playRemoteVideo(): Promise<UISdkResult | void>;
    static startStreamRecord(): Promise<void>;
    static stopStreamRecord(): Promise<void>;
    static subscribe(): Promise<void>;
    static unSubscribe(): Promise<void>;
}
export declare enum RetCodes {
    SUCCESS = "MSS.00000000",
    NORMAL_FAILED = "MSS.00000001",
    SERVER_ERROR = "MSS.00000002",
    ERROR_PARAM = "MSS.00000003",
    AUTH_FAILED = "MSS.00000004",
    DIALOG_NOT_EXIST = "MSS.47010001",
    RPC_ACTION_NOT_EXIST = "MSS.47010002",
    ICS_EXCEPTION = "MSS.47010003",
    REQUEST_TOO_FREQUENTLY = "MSS.47010004",
    GET_DAC_ASSERT_FAIL = "MSS.47010005",
    GET_DHM_STYLE_FAIL = "MSS.47010006",
    GET_SFS_CACHE_FAIL = "MSS.47010007",
    TENANT_CLEANUP_JOB_STOPPED = "MSS.47010008",
    NO_PERMISSION_USE = "MSS.47010009",
    CHAT_SERVICE_IS_ACTIVED = "MSS.47010010",
    CHAT_SERVICE_IS_INACTIVED = "MSS.47010011",
    DIALOG_HAS_FINISH = "MSS.47010012",
    CHAT_SERVICE_CONCURRENCY_NOT_ENOUGH = "MSS.47010013",
    DIALOG_STATE_UNAVAILABLE = "MSS.47010014",
    SEND_EVENT_CALLBACK_FAIL = "MSS.47010015",
    DIALOG_WAIT_IS_NULL = "MSS.47010016",
    SKILL_NAME_EXIST = "MSS.47010020",
    SKILL_IDENTIFY_EXIST = "MSS.47010021",
    SKILL_NOT_EXIST = "MSS.47010022",
    SKILL_NO_PERMISSION = "MSS.47010023",
    INTENT_NAME_EXIST = "MSS.47010024",
    INTENT_IDENTIFY_CREATE_FAILED = "MSS.47010025",
    INTENT_COUNT_EXCEED_MAX_VALUE = "MSS.47010026",
    INTENT_NOT_EXIST = "MSS.47010027",
    INTENT_NO_PERMISSION = "MSS.47010028",
    QUESTION_EXIST = "MSS.47010029",
    QUESTION_NOT_EXIST = "MSS.47010030",
    QUESTION_NO_PERMISSION = "MSS.47010031",
    QUESTION_BATCH_LIST_EMPTY = "MSS.47010032",
    ROBOT_NAME_EXIST = "MSS.47010033",
    ROBOT_NOT_EXIST = "MSS.47010034",
    ROBOT_NO_PERMISSION = "MSS.47010035",
    EXPORT_SKILL_FAILED = "MSS.47010036",
    START_SMART_CHAT_FAILED = "MSS.47010037",
    STOP_SMART_CHAT_FAILED = "MSS.47010038",
    SHOW_SMART_CHAT_FAILED = "MSS.47010039",
    DIALOG_CONCURRENT_EXCEED_MAX_VALUE = "MSS.47010040",
    ACTIVE_CODE_AUTH_FAILED = "MSS.47010043",
    ACTIVE_CODE_AUTH_LOCKED = "MSS.47010044",
    ACTIVE_CODE_AUTH_EXPIRED = "MSS.47010045",
    ONCE_CODE_AUTH_FAILED = "MSS.47010046",
    ONCE_CODE_AUTH_LOCKED = "MSS.47010047",
    GENERATE_SLIDE_VERIFICATON_FAILED = "MSS.47010048",
    SLIDE_VERIFICATON_NOT_EXIST = "MSS.47010049",
    SLIDE_VERIFICATON_VERIFY_FAILED = "MSS.47010050",
    SLIDE_VERIFICATON_VERIFY_FAILED_AND_EXCEED_MAX_TIMES = "MSS.47010051",
    DIALOG_NO_PERMISSION = "MSS.47010063",
    FAILED_TO_QUERY_TENANT_ID = "MSS.47010065",
    HOT_QUESTION_NOT_EXIST = "MSS.47010066",
    WS_INTERNAL_ERROR = "MSS.47010100",
    MESSAGE_PARSE_ERROR = "MSS.47010101",
    WS_ROBOT_ID_IS_EMPTY = "MSS.47010102",
    UNKNOWN_ACTION = "MSS.47010103",
    CONNECT_AIUI_TIMEOUT = "MSS.47010104",
    CONNECT_APP_TIMEOUT = "MSS.47010104",
    AUTHTOKEN_INVALID = "MSS.47010105",
    QUERYPARAM_INVALID = "MSS.47010106",
    CLIENT_ERROR_MESSAGE = "MSS.47010107",
    WEBCLIENT_START_CHAT_WORKER_DISCONNECT = "MSS.47010111",
    CHANNEL_RECORED_NOT_FOUND = "MSS.47010119",
    INTERACTIVE_NUMBER_IS_INSUFFICIENT = "MSS.47010120",
    TOKEN_NUMBER_IS_INSUFFICIENT = "MSS.47010121",
    RPC_CALL_FAILED = "MSS.47010122",
    AIUI_UNAUTHORIZED = "MSS.47010124",
    SPARK_UNAUTHORIZED = "MSS.47010125",
    MOBVOI_QUANTITY_NOT_ENOUGH = "MSS.47010126",
    MOBVOI_UNAUTHORIZED = "MSS.47010127",
    MOBVOI_ROLE_ID_IS_INVALID = "MSS.47010128",
    THIRD_PARTY_LANGUAGE_MODEL_EMPTY = "MSS.47010130",
    THIRD_PARTY_LANGUAGE_MODEL_URL_EMPTY = "MSS.47010131",
    THIRD_PARTY_LANGUAGE_MODEL_URL_INVALID = "MSS.47010134",
    IFLY_APPLICATION_SCENE_CONFIG_ERROR = "MSS.47010136",
    SIS_AUTHORIZATION_FAILED = "MSS.47010141",
    CURRENT_LANGUAGE_NOT_SUPPORT_RECOGNITION = "MSS.47010143",
    ICS_NOT_IN_TEXT_MODE = "MSS.47010144",
    ICS_TEXT_QUESTION_LENGTH_LIMITED = "MSS.47010145",
    ICS_TEXT_QUESTION_IS_EMPTY = "MSS.47010146",
    ICS_TEXT_QUESTION_NOT_IN_WAIT_QUESTION_STATUS = "MSS.47010147",
    ICS_INVALID_INTERACTION_MODE = "MSS.47010148",
    MOBVOI_REQUEST_FLOW_LIMITED = "MSS.47010150",
    UPLOAD_LOG_COUNT_EXCEED_MAX_COUNT = "MSS.47010151",
    ICS_EXTEND_PARAM_INVALID = "MSS.47010152",
    PACIFY_WORDS_EXIST = "MSS.47010154",
    PACIFY_WORDS_COUNT_EXCEED_MAX_VALUE = "MSS.47010155",
    PACIFY_WORDS_NOT_EXIST = "MSS.47010156",
    PACIFY_WORDS_NO_PERMISSION = "MSS.47010157",
    PACIFY_WORDS_INTENT_NOT_SUPPORT = "MSS.47010158",
    ICS_ROBOT_ROOM_ID_EMPTY = "MSS.47010163",
    SINGLE_TENANT_WEBSOCKET_LINKS_EXCEEDS = "MSS.47015005",
    WEBSOCKET_LINKS_EXCEEDS = "MSS.47015006",
    ICS_UNMATCHED_APP_TYPE_AIUI = "MSS.47015008",
    ICS_UNMATCHED_APP_TYPE_SPARK = "MSS.47015009",
    ICS_THIRD_PARTY_DRIVER_NOT_ALLOWED_WEB_START_CHAT = "MSS.47015010",
    ICS_MEDIA_SERVICE_ADDR_IS_EMPTY = "MSS.47015011",
    ICS_MEDIA_NEGOTIATE_FAILED = "MSS.47015012",
    ICS_SIS_FROZEN_ERROR = "MSS.47015015",
    ICS_THIRD_PARTY_DRIVE_NOT_ALLOWED_THIS_WEB_MESSAGE = "MSS.47015017",
    ICS_MOBVOI_ASR_UNAUTHORIZED = "MSS.47015018",
    ICS_ASR_WAIT_VOICE_TIME_OUT = "MSS.47015019",
    ICS_SIS_SERVICE_NOT_SUBSCRIBE = "MSS.47015028",
    ICS_AUDIO_REPORT_TASK_EXIST = "MSS.47015029",
    ICS_CREATE_AUDIO_RECORD_TASK_FAILED = "MSS.47015030",
    ICS_AUDIO_RECORD_NOT_ENABLE = "MSS.47015031"
}
export declare enum MPSRetCodes {
    SUCCESS = "00000000",
    FAILED = "00000001",
    INTERNAL_ERROR = "00000002",
    INVALID_PARAMETER = "00000003",
    ILLEGAL_ACCESS = "00000004",
    MPS_NAME_INCLUDE_INVALID_SYMBOL = "20010001",
    NO_MATCH_TEMPLATE = "20010003",
    REFRESH_ASSET_FAILED = "20010010",
    NO_ENOUGH_RESOURCE = "20010035",
    NATS_PUBLISH_FAILURE = "20010040",
    NATS_SUBSCRIBE_FAILURE = "20010041",
    NATS_DELETE_SUBJECT_FAILURE = "20010042",
    NATS_INTERNAL_ERROR = "20010043",
    DIGITAL_HUMAN_NOT_AVAILABLE = "20010044",
    MPS_ROOM_INFO_NOT_FOUND = "20010045",
    ROOM_ID_JOB_EXIST = "20010046",
    ASSET_NOT_EXIST = "20010047",
    ASSET_INFO_INVALID = "20010050",
    INVALID_COMMAND = "20010053",
    QUOTA_INSUFFICIENT = "20010056",
    REQUEST_TMS_UNAVAILABLE = "20010060",
    LIVE_QUOTA_INSUFFICIENT = "20010065",
    MPS_CHANGE_FINISHED_JOB_STATE_FAILED = "20010066",
    AUDIO_NOT_FOUND_URL = "20010067",
    MPS_FIELD_VERIFY_FAIL = "20010070",
    MPS_ASSET_ID_UNAVAILABLE = "20010071",
    MPS_JOB_NOT_EXISTED = "20010074",
    CHAT_QUOTA_INSUFFICIENT = "20010075",
    MPS_TASK_EXPIRED = "20010076",
    CONVERSATION_RESOURCE_FULL = "20010089",
    TONE_RESOURCE_ERROR = "20010131",
    CHAT_JOBS_NUM_IS_OVER_CONCURRENCY = "20010135",
    CHAT_SUM_CONCURRENCY_OR_JOBS_NUM_IS_OVER_RESOURCES_NUM = "20010139",
    MPS_ASSET_ID_INVALID = "20010140",
    MPS_JOB_HEARTBEAT_FAILED = "20010146",
    MPS_ROOM_NAME_DUPLICATE = "20010148"
}
export declare enum WorkerRetCodes {
    DHICIS_ERROR = "47000001",
    DHICIS_INFER_SERVICE_ERROR = "47000002",
    DHICIS_TASK_READY_ERROR = "47000003",
    DHICIS_CREATE_INFER_MODEL_ERROR = "47000004",
    DHICIS_WORKER_JOIN_ROOM_FAIL = "47000005",
    DHICIS_MANAGER_SERVICE_ERROR = "47000006",
    DHICIS_JOB_STOP_BY_COMMAND = "47000007",
    DHICIS_FSM_STATE_TIME_OUT = "47000009",
    DHICIS_ICS_ERROR = "47000010",
    DHICIS_RTSA_ROOM_EMPTY = "47000011",
    DHICIS_RTSA_REPORT_LEAVE_ROOM = "47000012",
    DHICIS_MODEL_FILE_DOWN_FAIL = "47000013",
    DHICIS_BACKGROUND_FILE_DOWN_FAIL = "47000014",
    DHICIS_WORKER_JOIN_ROOM_TIMEOUT = "47000015",
    DHICIS_JOIN_ROOM_TASK_FAIL = "47000016",
    DHICIS_TTS_PREHEAT_TASK_FAIL = "47000017",
    DHICIS_DATA_PACKAGE_IS_NOT_ZIP = "47000018",
    DHICIS_TOO_MANY_ENTRIES_IN_PACKAGE = "47000019",
    DHICIS_PACKAGE_TOO_LARGE = "47000020",
    DHICIS_FILE_IN_PACKAGE_TOO_LARGE = "47000021",
    DHICIS_UNEXPECTED_DIRECTORY_IN_PACKAGE = "47000022",
    DHICIS_PACKAGE_ENTRY_ILLEGAL_NAME = "47000023",
    DHICIS_FILE_NAME_INVALID = "47000024",
    DHICIS_JOB_INFO_PARA_INVALID = "47000025",
    DHICIS_FSM_STATE_ERROR = "47000027",
    DHICIS_TTS_CONVERT_FAIL = "47000029",
    DHICIS_NO_IDLE_WORK = "47002000",
    DHICIS_NO_RESOURCE = "47002001",
    DHICIS_RESOURCE_LIMITED = "47002002"
}
export declare enum WBWRetCodes {
    WBW_AGENT_ROLE_NOT_EXISTED = "47050001",
    WBW_LLM_NOT_EXISTED = "47050002",
    WBW_LLM_INVALID_MODEL = "47050003",
    WBW_LLM_ACCESS_FAILED = "47050004"
}
export declare enum WBMRetCodes {
    WBM_LLM_CONFIG_NOT_EXIST = "47030103",
    WBM_LLM_CONFIG_NO_PERMISSION = "47030104",
    WBM_PLUGIN_CONFIG_NOT_EXIST = "47030114",
    WBM_PLUGIN_CONFIG_NO_PERMISSION = "47030115"
}
export declare enum WBCRetCodes {
    WBC_ROLE_NOT_EXIST = "47040041",
    WBC_CONFIG_NO_PERMISSION = "47040042"
}
export declare enum TTSCRetCodes {
    TTS_ACCESS_CONFIG_ERROR = "20050038",
    TTS_INSUFFICIENT_ACCOUNT_BALANCE = "20050039",
    TTS_INVALID_TEXT = "20050040",
    TTS_NO_ACCESS_CONFIG = "20050029",
    TTS_TO_LONG_WORD_TEXT = "20051001",
    TTS_VOICE_ASSET_UNACTIVATED = "20050042",
    TTS_UNSUPPORTED_LANGUAGE_TEXT = "20050064"
}
export declare enum SDKErrorCode {
    MPS_JOB_STATE_NULL = "999000001",
    MPS_JOB_STATE_ERROR = "999000002",
    RTC_PROMISE_ERROR = "999100001",
    RTC_CATCH_ERROR = "999100002",
    RTC_KICK_OUT = "999100003",
    RTC_AUDIO_DEVICE_ERROR = "999100004",
    RTC_PEER_LEAVE = "999100005",
    RTC_KICK_ROOM = "999100006",
    RTC_NOT_INIT = "999100007",
    RTC_JOIN_TIMEOUT = "999100008",
    WEBSOCKET_CONNECT_ERROR = "999200001",
    WEBSOCKET_RESPONSE_TIMEOUT = "999200002",
    WEBCLIENT_WEBSOCKET_CHANNEL_ABNORMAL = "999200003",
    WEBSOCKET_NETWORK_ERROR = "999200004",
    WEBSOCKET_KICK_OUT = "999200005",
    WEBSOCKET_CONNECT_TIMEOUT = "999200006",
    UI_NO_PARENT = "999300001",
    UI_PARAM_ERROR = "999300002",
    UI_LANGUAGE_LIST_EMPTY = "999300003",
    UI_LANGUAGE_CODE_NOT_SUPPORT = "999300004",
    METHOD_PROHIBITED_EXECUTION = "999400001",
    METHOD_NOT_ALLOW_NOT_AUTH = "999400002",
    WORKER_JOB_STOP_BY_MUTE_OVERTIME = "999400003",
    METHOD_REPEAT_CALLS = "999400004",
    JOB_NOT_READY = "999400005"
}
export declare enum ICSEventKey {
    ERROR = "error",
    JOB_INFO_CHANGE = "jobInfoChange",
    SPEAKING_START = "speakingStart",
    SPEAKING_STOP = "speakingStop",
    SPEECH_RECOGNIZED = "speechRecognized",
    SEMANTIC_RECOGNIZED = "semanticRecognized",
    ENTER_SLEEP = "enterSleep",
    ENTER_ACTIVE = "enterActive",
    LANGUAGE_INFO_CHANGE = "languageInfoChange",
    JOB_END_MENTION = "jobEndMention",
    JOB_END = "jobEnd"
}
export declare enum WakeupType {
    VOICE = "VOICE",
    RADAR = "RADAR",
    INFRARED = "INFRARED",
    CAMERA = "CAMERA"
}
export declare enum LanguageCode {
    ZH_CN = "zh_CN",
    EN_US = "en_US"
}
export declare enum VoiceLanguageCode {
    CN = "CN",
    EN = "EN"
}
export declare enum ConfigKey {
    ENABLE_CAPTION = "enableCaption",
    ENABLE_CHAT_BTN = "enableChatBtn",
    ENABLE_HOT_ISSUES = "enableHotIssues",
    ENABLE_BUSINESS_TRACK = "enableBusinessTrack",
    ENABLE_WEAK_ERROR_INFO = "enableWeakErrorInfo",
    ENABLE_JOB_CACHE = "enableJobCache",
    USE_DEFAULT_BACKGROUND = "useDefaultBackground",
    ENABLE_NETWORK_CHECK = "enableNetworkCheck",
    ENABLE_DEVICE_SETTING = "enableDeviceSetting",
    SHOW_LANGUAGE_UI = "showLanguageUI",
    DESTROY_BEFORE_CLOSE = "destroyBeforeClose",
    ENABLE_LOCAL_WAKEUP = "enableLocalWakeup",
    ENABLE_VAD_INTERRUPT = "enableVadInterrupt",
    FIRST_CREATE_LOCAL_STREAM = "firstCreateLocalStream",
    ENABLE_STORAGE_CACHE = "enableStorageCache",
    ENABLE_MEDIA_VIEWER = "enableMediaViewer",
    DEFAULT_MUTE_REMOTE_AUDIO = "defaultMuteRemoteAudio",
    AUTO_PLAY_REMOTE_VIDEO = "autoPlayRemoteVideo",
    ENABLE_COLLECT_AUDIO_DEMAND = "enableCollectAudioDemand",
    ENABLE_ORIGIN_CUT_ALGORITHM = "enableOriginCutAlgorithm",
    ENABLE_VERBATIM = "enableVerbatim",
    USE_WORKER_WAKEUP = "useWorkerWakeup",
    PRE_CHECK_PERMISSIONS = "preCheckPermissions"
}
export declare enum SparkRTCErrorCode {
    RTC_ERR_CODE_SUCCESS = "0",
    RTC_ERR_CODE_RTC_SDK_ERROR = "90000001",
    RTC_ERR_CODE_WAIT_RSP_TIMEOUT = "90000004",
    RTC_ERR_CODE_INVALID_PARAMETER = "90000005",
    RTC_ERR_CODE_INVALID_OPERATION = "90100001",
    RTC_ERR_CODE_NOT_SUPPORT_MEDIA_DEVICES = "90100002",
    RTC_ERR_CODE_NO_AVAILABLE_DEVICES = "90100003",
    RTC_ERR_CODE_NO_AVAILABLE_VIDEO_INPUT_DEVICES = "90100004",
    RTC_ERR_CODE_NO_AVAILABLE_AUDIO_INPUT_DEVICES = "90100005",
    RTC_ERR_CODE_NO_AVAILABLE_AUDIO_OUTPUT_DEVICES = "90100006",
    RTC_ERR_CODE_STATUS_ERROR = "90100007",
    RTC_ERR_CODE_WEBSOCKET_NOT_CONNECTED = "90100008",
    RTC_ERR_CODE_WAIT_CONFIG_FAIL = "90100009",
    RTC_ERR_CODE_PUBLISH_RESPONSE_FAIL = "90100010",
    RTC_ERR_CODE_REGION_NOT_COVERED = "90100011",
    RTC_ERR_CODE_WEBSOCKET_CONNECT_TIMEOUT = "90100012",
    RTC_ERR_CODE_WEBSOCKET_RECONNECT_TIMEOUT = "90100013",
    RTC_ERR_CODE_WEBSOCKET_NOT_OPEN = "90100014",
    RTC_ERR_CODE_WEBSOCKET_INTERRUPTED = "90100015",
    RTC_ERR_CODE_WEBSOCKET_CONNECT_ERROR = "90100016",
    RTC_ERR_CODE_CAPTURE_PERMISSION_DENIED = "90100017",
    RTC_ERR_CODE_CAPTURE_OVER_CONSTRAINED = "90100018",
    RTC_ERR_CODE_CAPTURE_DEVICE_NOT_FOUND = "90100019",
    RTC_ERR_CODE_CAPTURE_DEVICE_NOT_READABLE = "90100020",
    RTC_ERR_CODE_PLAY_NOT_ALLOW = "90100021",
    RTC_ERR_CODE_ROLE_NO_PERMISSION = "90100022",
    RTC_ERR_CODE_ANSWER_SDP_INVALID = "90100023",
    RTC_ERR_CODE_MEDIA_UPSTREAM_UNSUPPORTED = "90100024",
    RTC_ERR_CODE_WEBRTC_UNSUPPORTED = "90100025",
    RTC_ERR_CODE_MEDIA_NETWORK_ERROR = "90100026",
    RTC_ERR_CODE_CLIENT_RELAY_ROOM_OVER_MAXNUM = "90100027",
    RTC_ERR_CODE_CLIENT_RELAY_JOINER_OVER_MAXNUM = "90100028",
    RTC_ERR_CODE_ROOM_STREAM_STATUS_PAUSED = "90100029",
    RTC_ERR_CODE_SIGNATURE_EXPIRED = "90100030",
    RTC_ERR_CODE_SIGNATURE_INVALID = "90100031",
    RTC_ERR_CODE_WINDOW_OR_NAVIGATOR_UNSUPPORTED = "90100032",
    RTC_ERR_CODE_CHROME_VERSION_UNSUPPORTED = "90100033",
    RTC_ERR_CODE_WEBSOCKET_UNSUPPORTED = "90100034",
    RTC_ERR_CODE_WEBRTC_AVC_ENCODE_UNSUPPORTED = "90100035",
    RTC_ERR_CODE_WEBRTC_AVC_DECODE_UNSUPPORTED = "90100036",
    RTC_ERR_CODE_WEBRTC_WECHAT_UNSUPPORTED = "90100037",
    RTC_ERR_CODE_AUDIO_ERROR = "90100038",
    RTC_ERR_CODE_RTC_ACS = "90100100",
    RTC_ERR_CODE_RTC_CONTROL_ERROR = "90100200",
    RTC_ERR_CODE_SFU_ERROR = "90100600",
    RTC_WEBSOCKET_ERR_NEED_REJOIN = "4005"
}
export declare enum InteractionMode {
    AUDIO = "AUDIO",
    TEXT = "TEXT"
}
export type HttpErrorCode = MPSRetCodes | RetCodes | WorkerRetCodes | WBWRetCodes | SDKErrorCode | TTSCRetCodes;
export declare enum MediaType {
    VIDEO = "VIDEO",
    IMAGE = "IMAGE"
}
export type EventMap = {
    [key in ICSEventKey]?: Function;
};
export type ConfigMap = {
    [key in ConfigKey]?: boolean;
};
export type LogLevel = 'debug' | 'info' | 'warn' | 'error' | 'none';
export interface InnerInitParam {
    robotId?: string;
    serverAddress: string;
    taskUrl?: string;
    config?: ConfigMap;
    containerId: string;
    logLevel?: LogLevel;
    eventListeners?: EventMap;
    extendParamStr?: string;
}
export interface CreateParam extends InnerInitParam {
    onceCode?: string;
}
export interface UISdkResult {
    result: boolean;
    errorCode?: SparkRTCErrorCode | SDKErrorCode | HttpErrorCode;
    errorMsg?: string;
}
export interface InteractionModeResult extends UISdkResult {
    interactionMode?: InteractionMode;
}
export interface TextQuestionResult extends UISdkResult {
    chatId: string;
}
export interface ChatResult extends UISdkResult {
    chatId: string;
    sessionId?: string;
}
export interface JobInfo {
    jobId: string;
    websocketAddr: string;
    jobInfo?: SmartChat | SmartChatState | null;
}
export interface LanguageInfo extends UISdkResult {
    languageList?: Array<VoiceLanguageItem>;
    currentLanguage?: LanguageCode;
}
export interface JobEndMentionInfo {
    jobId: string;
    restTime: number;
}
export interface JobEndInfo {
    jobId: string;
    reason: string;
}
export interface TextDrivenParam {
    text: string;
    isLast?: boolean;
}
export interface TextQuestionParam {
    text: string;
    questionParam?: string;
}
export interface ResourcePath {
    wasmPath: string;
    dataPath: string;
    initModel?: boolean;
    useWorker?: boolean;
}
export interface UHanConfig {
    origin?: string;
    enable?: boolean;
    sleepDelay?: number;
    showVideoUi?: boolean;
    host?: string;
}
export interface CustomRecordConfig {
    enable?: boolean;
}
export interface ThirdPartyConfig {
    uHan?: UHanConfig;
    uHanV2?: UHanConfig;
    customRecord?: CustomRecordConfig;
}
export interface AudioData {
    base64Data?: string;
    uint8Arr?: Uint8Array;
    time?: number;
}
export interface VoiceLanguageItem {
    language: LanguageCode;
    language_desc: string;
}
export interface StartUserSpeakParam {
    preCheckPermissions?: boolean;
}