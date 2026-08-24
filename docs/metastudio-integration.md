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

## 真机技术 PoC 与发布硬门禁

华为文档明确支持 Android 移动 Chrome，但没有承诺 Android System WebView。本项目按既定选择使用独立 WebView 且不伪造 Chrome UA、不回退 Custom Tab，所以必须在至少一台 Android 10 真机和一台 Android 12 或更高版本真机完成以下 PoC：

- `checkBrowserSupport`、WebRTC 建连、麦克风授权及关闭释放；
- SIS 实时识别、第三方大脑非流式/流式回答、数字人口型与播报；
- 五轮脱敏指代追问以及最终 `semanticRecognized.extendParam`；
- Android 按 `chatId + intent_id` 去重，交换意图并跳转原工作台确认，语音本身不改变业务状态。

测试网络持续下行至少 `4 Mbit/s`，并确认终端网络可访问华为 RTC 所需 TCP `443`、TCP `6447`、UDP `20000–20063`。任何一台目标真机的 WebView PoC 失败，都阻塞数字人 APK 的发布；不得用成功编译、模拟事件或桌面浏览器结果代替真机证据。
