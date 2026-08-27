# MetaStudio 智能交互云端接入

## 状态与安全边界

MetaStudio 是可选能力，`deploy/cloud.env` 默认 `METASTUDIO_ENABLED=false`。关闭时，云端现有政务 API、团队 RAG 和普通/SSE 咨询不依赖华为云 IAM 或 robotId，也不会发起供应方调用；Android 构建仍会验证已随应用固定打包的官方 SDK 资产，避免以后仅切服务器开关就加载未核验文件。缺失配置不能被模板值静默替代。

启用后，Android 本地包装页加载华为云智能交互 Web SDK 5.0.6，通过本系统后端获取短期 `onceCode`、固定北京四 `serverAddress` 和 `robotId`。AK/SK、应用 Key 和 robotId 都不会编译进 APK。MetaStudio 调用本系统 LLM 回调时，后端先验证 MSS_A HMAC、时间窗和重放，再进入现有咨询协调者。

这会扩大原有“端侧语音、不上传原始音频”的边界：用户选择数字人交互后，音频和交互数据可能由华为 SDK 直接发送至华为云。正式使用前必须完成用户告知/同意、隐私影响评估、数据地域与保留策略确认；演示时只使用合成问题和演示账号。

## 固定接口合同

| 接口 | 调用方 | 说明 |
| --- | --- | --- |
| `POST /api/v1/integrations/metastudio/client-sessions` | Android 原生网关 | 后端用服务端 IAM 凭据换取短期会话，并只返回 SDK 所需白名单字段 |
| `POST /api/v1/integrations/metastudio/llm` | MetaStudio | 唯一 LLM 回调；请求体 `is_stream=true` 时仍由同一路径返回 SSE，不暴露拆分端点 |
| `POST /api/v1/integrations/metastudio/action-intents/{id}/exchange` | Android 原生网关 | 使用 Bearer Token 一次性交换已验证的动作意图；Web SDK 不能直接调用任意政务写接口 |

回调 URL 本身不得带 query。MetaStudio 以 MSS_A 方式在每次请求动态添加 `secret` 和 `time_stamp`；后端的默认重放窗口为 300 秒。Nginx 精确匹配该路径，始终设置 `proxy_buffering off`，所以普通 JSON 和 SSE 都不会被代理缓冲。云端 Uvicorn 的原始 access log 被关闭，由 Nginx 提供脱敏后的请求可观测性。

客户端创建会话后，包装页通过 `extendParamStr` 发送的 `client_id` 是后端生成的不透明会话 UUID。返回 Android 的 `expires_at` 只表示 onceCode 启动包的固定 5 分钟有效期；Redis 中另存 `context_expires_at`，默认保留 30 分钟，使 SDK 首次加载和后续对话回调不会因 onceCode 到期而丢失账号、角色及意图绑定。它不是账号 ID、JWT、MetaStudio 回调体中的供应方 `session_id`，也不是 Web SDK 每轮识别事件中的 `chatId`。这四类标识不得互相替代或从一个推导另一个。

## MetaStudio 控制台（方案二）

本项目固定选择“第三方大脑回调模式”，由现有 DeepSeek、MCP、双 RAG 和政务协调器继续充当大脑。控制台按下表填写：

| 截图参数 | 最终配置 |
| --- | --- |
| 第三方应用 | `第三方大脑（大模型）` |
| 应用名称 | `智慧政务“一网通办”数字人（演示）` |
| APPID | `init-cloud-secrets.sh` 在服务器生成的独立 32 位小写十六进制标识 |
| APPKEY | 服务器 root-only `deploy/secrets/metastudio_app_key` 中的独立 32 位随机小写十六进制密钥，只粘贴到控制台 |
| 第三方语言模型地址 | `https://123.249.68.176/api/v1/integrations/metastudio/llm` |
| 流式响应 | 先关闭；非流式协议验收通过后开启，再验收精确 SSE 封包及中断行为 |
| 多轮语境理解能力 | `5`（当前问题以及最近 4 组脱敏问答） |
| ASR 服务 | `华为云 SIS` |
| 对话内容合规审核 | 开启 |
| 尾静音时长 | `1000 ms` |
| 委托语音交互服务（SIS） | 开启，并完成 MetaStudio 所需委托授权 |
| Region | 华北－北京四 `cn-north-4` |

本机为本项目生成的 APPID 与 APPKEY 同时保存在
`docs/metastudio-console-values.local.md`。该私密配置单及 `deploy/secrets/metastudio_app_key`
都被 Git 明确忽略；请从私密配置单复制到华为控制台，不要把内容转录到本文件、提交记录、截图或聊天消息中。
部署时必须使用私密配置单中的同一 APPID，并将同一 APPKEY 安装为服务器 root-only Docker secret，
否则 MetaStudio 回调签名校验必然失败。

APPID/APPKEY 是本项目专用的回调身份，不是华为 AK/SK、Project ID、DeepSeek 或 DashScope 密钥。控制台发布活动后得到的 `robotId` 是非秘密部署配置；华为 AK/SK 只留在服务器 secret 中，用最小权限签名申请一次性 `onceCode`。

控制台给出的“发布链接”和“激活码”仅用于发布页人工验收。部署工具可以从发布链接的
`robot_id` 查询参数提取 `METASTUDIO_ROBOT_ID`，但 Android 不加载该发布链接、不保存激活码，
也不能用激活码替代 Web SDK 所需的五分钟单次 `onceCode`。本机收到的发布信息只保存在被 Git
忽略的 `docs/metastudio-console-values.local.md` 中。

## SIS 委托边界

SIS 实时语音识别需要在华为云开通，并授权 MetaStudio 委托调用。SIS、RTC、数字人口型和播报均由 MetaStudio 侧完成：本项目后端不直接调用 SIS，不保存 SIS endpoint/credential，也不接收或转发原始音频；数字人页不同时启动 Android `SpeechRecognizer` 或本地 TTS。现有端侧语音能力只保留给普通聊天模式。

数字人包装页启用 Web SDK 官方字幕并注册 `speechRecognized` 事件。SDK 自身按照 `chatId + resultId` 覆盖显示中间文字，`isLast=true` 后进入等待回答状态；本项目不再复制、拼接或保存一份字幕原文。包装页只向原生消息桥发送 `asr_partial`、`asr_final` 等固定状态枚举；它不会通过原生桥或新增请求转发 `speechRecognized` 的语音原文及其 `chatId`/`resultId`，也不会把中间结果写入公共缓存或日志。MetaStudio 官方 LLM 回调协议中原有的会话字段不受此限制。最终 `semanticRecognized` 事件只将经校验的不透明语义 `chatId` 和 `intent_id` 交给原生层及意图交换接口，不携带 ASR 原文。迟到包、非法包和最终包后的同轮状态会被忽略；休眠或会话结束后的事件也不再接受。第三方 LLM 回调仍只处理 MetaStudio 提交的完整 `messages`，不得因为本地中间结果额外发起模型、RAG 或业务操作。

SDK 启动参数显式设置 `enableCollectAudioDemand=false`，因此用户首次主动开始语音会话后持续拾音，直至 Activity 离开前台并销毁任务；设置 `enableVadInterrupt=true` 允许人声打断数字人播报。首次开始仍保留用户点击和麦克风授权，不在页面加载时静默开麦。尾静音负责产生每轮最终结果，持续拾音不等于取消问答轮次边界。

初始热词至少配置：`一网通办`、`社保卡`、`公积金`、`营业执照`、`身份证补领`。首轮真机验收后只根据脱敏的误识别统计调整热词，不把群众原始录音或完整 ASR 文本写入运维日志。

## 华北－北京四固定参数

| 配置 | 固定值 |
| --- | --- |
| MetaStudio Region | `cn-north-4` |
| MetaStudio OpenAPI | `https://metastudio.cn-north-4.myhuaweicloud.com` |
| 智能交互客户端 `serverAddress` | `metastudio-api.cn-north-4.myhuaweicloud.com`（SDK 要求纯主机名，不带 scheme/path） |

MetaStudio Web SDK 文档给出的北京四智能交互地址为 `metastudio-api.cn-north-4.myhuaweicloud.com`。参考：[MetaStudio Web SDK 主入口](https://support.huaweicloud.com/api-metastudio/metastudio_08_0010.html)、[MetaStudio 创建应用 API](https://support.huaweicloud.com/api-metastudio/CreateRobot.html)。SIS 的 Region、ASR 和委托只在 MetaStudio/SIS 控制台配置，因此 `compose.metastudio.yaml` 和 `cloud.env` 故意不存在 `SIS_*` 后端变量。

## SDK 资产硬门禁

Web SDK 受华为云分发条款约束，不提交到公共仓库，也不从未知 CDN 动态加载。先从 MetaStudio 控制台/官方支持渠道取得 5.0.6 完整包并完成供应方 CMS/签名校验，再把包内文件按原相对目录放入：

```text
android/app/src/main/assets/metastudio/sdk/
├── HwICSUiSdk.js
├── HwICSUiSdk.css
├── HwICSUiSdk.d.ts
├── HwICSUiSdk.esm.js
├── images/{aiChatImg.png,bg_mobile.png,bg.png}
├── modelData.js
├── package.json
├── wasmData.js
├── provenance/HwICSUiSdk-5.0.6.zip.cms
└── sdk-integrity.json
```

`sdk-integrity.json` 必须声明精确的 11 项资产清单，不允许缺项或额外文件；摘要不能由清单自身决定，部署脚本和 Android 构建脚本都固定保存官方 5.0.6 的预期值并重新读取每个实际文件计算 SHA-256。固定供应包证据为：

- ZIP SHA-256：`d8d028588b35580856d8cc1fc35b67b50fbc8f99525c45ea5d990feec86c7641`
- detached CMS SHA-256：`2bae230d3585e753adec0f001b81eb080f66c1a9cd2b99dea59c1f2827bbf0ea`
- 签名者证书 thumbprint：`ad39bc7c7a3d6bc0df3e91d53c023aabecc62b64`

门禁要求 marker 的 `version=5.0.6`、`cms_verified=true`、固定 `archive_sha256`、固定 `cms_sha256`、固定签名者及完整逐文件哈希全部匹配，并拒绝空文件、符号链接、额外文件和旧的通用 `sha256` 自证字段。任何一层失败都必须停止，不能退回远程脚本、空壳 SDK 或把 robotId 写死进 APK。

## 云端配置和 secrets

先保持关闭状态复制配置：

```bash
sudo cp deploy/cloud.env.example deploy/cloud.env
sudo chmod 600 deploy/cloud.env
```

先将 `METASTUDIO_ENABLED=true` 写入 `deploy/cloud.env`。首次运行 `init-cloud-secrets.sh` 会在服务器本地生成独立的 32 位小写十六进制 `METASTUDIO_APP_ID`，并把它写回 `cloud.env`；同时生成不回显的 32 位小写十六进制 `APPKEY`，只保存于 root-only Docker secret。两者均不得复用 Project ID、华为 AK/SK、DeepSeek 或 DashScope 密钥。随后填写真实的 `METASTUDIO_PROJECT_ID`、`METASTUDIO_ROBOT_ID` 和公网 HTTPS `METASTUDIO_CALLBACK_URL`。回调必须精确为：

```text
https://<公网域名或IP>/api/v1/integrations/metastudio/llm
```

从华为云创建最小权限 IAM 用户/委托，只授予北京四对应项目所需 MetaStudio 权限。不要使用主账号永久密钥，不要在 `cloud.env`、命令参数、APK 或日志中写入 AK/SK。准备权限为 `0600` 的临时文件后，再安全导入：

```bash
sudo env \
  DEEPSEEK_API_KEY_FILE=/root/secure/deepseek.key \
  DASHSCOPE_API_KEY_FILE=/root/secure/dashscope.key \
  METASTUDIO_HUAWEI_ACCESS_KEY_FILE=/root/secure/huawei-iam-ak \
  METASTUDIO_HUAWEI_SECRET_KEY_FILE=/root/secure/huawei-iam-sk \
  deploy/scripts/init-cloud-secrets.sh
```

脚本默认生成 APPKEY 且不回显；需要把它填入 MetaStudio 控制台时，只能由服务器管理员在受控终端读取 `deploy/secrets/metastudio_app_key` 并直接粘贴，完成后清理终端剪贴板与会话记录。如果控制台中已经固定了另一枚符合 32 位小写十六进制约束的 APPKEY，可通过 `METASTUDIO_APP_KEY_FILE` 一次性导入覆盖初始生成步骤。

脚本只安装为 root 所有、容器内 `0400` 的单行 Docker secret，不显示内容。云端只允许以下文件变量，直接的 `METASTUDIO_APP_KEY`、`METASTUDIO_HUAWEI_ACCESS_KEY`、`METASTUDIO_HUAWEI_SECRET_KEY` 一旦出现在 `cloud.env`，部署立即失败：

- `METASTUDIO_APP_KEY_FILE=/run/secrets/metastudio_app_key`
- `METASTUDIO_HUAWEI_ACCESS_KEY_FILE=/run/secrets/metastudio_huawei_access_key`
- `METASTUDIO_HUAWEI_SECRET_KEY_FILE=/run/secrets/metastudio_huawei_secret_key`

启用时 `cloud_compose` 自动叠加 `compose.metastudio.yaml`；关闭时不加载该覆盖文件，也不要求三项 MetaStudio secret。`deploy.sh` 在构建或重启容器前执行 SDK、robotId、项目、App、回调 URL、北京四 endpoint、IAM secret 和 Nginx 脱敏规则硬门禁；两个 Nginx 切流脚本也会重复执行同一静态检查。

## Nginx 日志与 SSE

MetaStudio 回调的 `secret` 位于 query，不能使用包含完整请求行的默认日志格式。IP 与域名模板都为精确回调路径配置专用 access log，只保留 `$request_method`、规范化 `$uri`、状态、字节数、耗时和 upstream 状态；格式明确禁止 `$args`、`$query_string`、`$request`、`$request_uri`。该 location 的 Nginx error log 写入 `/dev/null`，共享 429 内部跳转也使用同一类无 query 日志并关闭 error log，避免限流分支重新泄露原始请求行。回调请求体上限是 `128k`。

`/api/v1/integrations/metastudio/client-sessions` 使用独立精确 location，每 IP `1r/s`、`burst=3`、请求体上限 `4k`；应用层还执行匿名、登录和全局日配额。该路由只申请短时一次性 onceCode，不向客户端返回 AK/SK。

云端入口以 `--no-access-log` 关闭会包含原始 query 的 Uvicorn 默认访问日志；其他请求仍由 Nginx 常规日志覆盖。应用日志也不得记录 query、HMAC、App Key、AK/SK、onceCode、robotId、用户语音或完整提示词。回调失败只记录内部 request ID、结构化错误码和结果状态。

## 零付费 smoke

静态检查不会访问本地 API 或华为云：

```bash
sudo bash deploy/scripts/verify-metastudio-smoke.sh --skip-http
```

API 运行后可执行本地零付费检查：

```bash
sudo bash deploy/scripts/verify-metastudio-smoke.sh
```

它只验证：无 MSS_A 参数的回调在任何咨询/LLM/RAG/外呼前返回 400；无 Bearer 的动作交换返回 401；MetaStudio 关闭时 client-session 返回 503。脚本不打印响应体、Token、凭据或请求参数。

Nginx 切流后可显式验证伪造 query 没有进入专用 access log：

```bash
sudo bash deploy/scripts/verify-metastudio-smoke.sh \
  --base-url https://123.249.68.176 \
  --through-nginx
```

该模式只发送合成的错误 HMAC，必须在外呼前返回 400，并检查新增日志字节不含伪造值或 `time_stamp`。它不会申请 onceCode、启动数字人任务、调用 SIS、DeepSeek 或其他计费接口。MetaStudio 配置完整且已启用时，脚本刻意跳过 `client-sessions`，真实一次联调必须另行获得付费和数据处理授权。

`/health/ready` 不调用 IAM、MetaStudio 或 SIS，也不会为了探针申请 onceCode。MetaStudio 的就绪性采用“部署前静态硬门禁 + 上述零付费负向 smoke”；启用后的真实供应方连通性只能在取得计费、账号和数据处理授权后单独验收。因此既有 7/8 项 readiness 统计不会因可选 MetaStudio 增加一项付费探针。

## 视觉对话云端候选

视觉能力是独立、可选的数据通道，不改变 MetaStudio 对麦克风、SIS、RTC 与数字人播报的所有权。Android 只用 CameraX 显示预览和分析帧，不启用录制；摄像头默认关闭，用户首次主动开启时显示知情提示。首个 ASR partial 到 final 期间，CameraX 以不超过 2 FPS 持续评估场景变化，并保留约 1 秒、最多两张的纯内存前置帧。每轮最多选择 7 张普通候选和 1 张保留结束帧；JPEG 单张约不超过 96 KiB，重新编码会去除 EXIF。该上限与旧版 `3 × 256 KiB` 的最坏单轮网络量相同。

登录用户先以现有 JWT 调用：

```text
POST /api/v1/integrations/metastudio/vision-sessions
```

请求只包含现有 `client_session_id`。后端校验会话所有者、角色和令牌版本后返回 `vision_session_id`、固定 `vision_websocket_url`、60 秒单次使用的 `vision_token` 和过期时间。Android 必须确认返回地址与自身受信任 API Origin 派生出的固定 WSS 路径完全一致；原生 OkHttp 随即连接：

```text
WSS /api/v1/integrations/metastudio/vision/ws
Authorization: Bearer <vision_token>
```

令牌不放入 URL、WebView 或日志。客户端先发送 `vision.start`，每轮发送 `turn.start`、最多八张二进制帧和 `turn.end`。二进制帧为“4 字节无符号大端 JSON 头长度 + UTF-8 JSON 头 + JPEG”；JSON 头严格只允许 `v`、`type`、`turn_seq`、`frame_seq`、`captured_at_ms`、`width`、`height`、`camera`。服务端对接收或主动丢弃的每一张合法帧都返回带 `status` 的 `vision.ack`，客户端同一时间只保留一张未确认帧；最终帧使用独立保留槽，`turn.end` 排在其 ACK 之后。

原始 JPEG 只存在当前 API 进程的有界内存中，30 秒过期；完成分析、断线或异常后立即释放，不写 PostgreSQL、Redis、MinIO、临时目录、审计日志或公共缓存。Redis 只保存不可逆摘要索引的短期单次票据声明。

本地 Mock 调试配置为：

```dotenv
VISION_ENABLED=true
VISION_PROVIDER=mock
VISION_FAST_PROVIDER=mock
```

两个 `mock` 适配器都不发起任何外部请求。快通道可显式切换为 `VISION_FAST_PROVIDER=http`，调用单独部署的检测服务；其统一事件仅包含 `quality/object/track/action/ocr`，每个会话采用 latest-wins、全局最多两个并发任务。事件写入带 TTL 的结构化时间线，不含 JPEG；RT-DETR、PP-Tracking、动作识别与 OCR 可以在该服务内独立组合，任一模型失败都只缺少对应事实，不改变主问答路径。

慢通道由 `VISION_PROVIDER=dashscope` 和独立 root-only `vision_dashscope_api_key` 显式启用，对北京地域固定快照 `qwen3-vl-flash-2026-01-22` 每轮最多发起一次、5 秒超时、无重试的请求，并使用结构化 JSON 输出。它不再阻塞本轮正常回答：已完成的快事件可立即参与一次主模型调用，Qwen 迟到摘要只进入下一轮的短期视觉记忆。每会话只允许一个慢请求在途和一个最新待处理轮次，已开始的计费请求不会被新断句取消。Redis 以北京时间自然日执行全局 20 次原子限额；限额、超时、非法 JSON 或模型错误都不会生成固定失败回答，也不会额外调用所谓降级模型。

本机可由 `scripts/init-env.ps1` 从工作区外层、忽略提交的 `key-list.txt` 读取 `Qwen3-vl-flash key` 与 `Qwen3-vl-flash url`。脚本只把它们写入本机 `.env`，不回显密钥；URL 必须精确归一化为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，运行时代码也会再次拒绝任何其他主机或路径，避免视觉密钥被重定向。

事项匹配、MCP 和 RAG 只可使用经过二次过滤的物品、可见文字和政务检索关键词。人物、场景和身体信息只进入最终回答模型用于调整表达语气，不能进入公共缓存、操作意图、权限、资格、审核或业务状态。视觉轮次整体绕过公共回答缓存，持久化用户消息和所有操作意图始终以原始语音问题为准。

真机候选从首个 partial 到 final 持续筛选并上传每轮最多八张 JPEG，不上传完整视频；服务端只为慢模型保留有代表性的起始和最新尾帧，并让全部合格帧参与快事件分析。所有真实 Qwen 调用必须经过上述 Redis 日限额。原始帧仍不得落盘、入库、进入 Redis、对象存储或日志。

最终文本只生成一次。系统提示要求按问题意图和复杂度自动决定详略，不设置固定文字数上下限、不做二次改写；历史以真实用户/助手角色传入。登录用户的脱敏显示名、代码枚举角色和主体类型只用于自然称呼与语气，不作为资格、权限或政策事实，也不从人脸推断身份。

## 真机技术 PoC 与发布硬门禁

华为文档明确支持 Android 移动 Chrome，但没有承诺 Android System WebView。本项目按既定选择使用独立 WebView 且不伪造 Chrome UA、不回退 Custom Tab，所以必须在至少一台 Android 10 真机和一台 Android 12 或更高版本真机完成以下 PoC：

- `checkBrowserSupport`、WebRTC 建连、麦克风授权及关闭释放；
- SIS 实时识别、第三方大脑非流式/流式回答、数字人口型与播报；
- 五轮脱敏指代追问以及最终 `semanticRecognized.extendParam`；
- Android 按 `chatId + intent_id` 去重，交换意图并跳转原工作台确认，语音本身不改变业务状态。

测试网络持续下行至少 `4 Mbit/s`，并确认终端网络可访问华为 RTC 所需 TCP `443`、TCP `6447`、UDP `20000–20063`。任何一台目标真机的 WebView PoC 失败，都阻塞数字人 APK 的发布；不得用成功编译、模拟事件或桌面浏览器结果代替真机证据。
