# 智慧政务“一网通办”AI 助手（演示环境）

本仓库是一套可运行的全栈业务演示：群众（个人/企业）、工作人员和管理员可在 Android 本地资产门户中完成事项查询、资格预检、材料与表单、办件审核、预约、模拟核验/缴费/邮寄、咨询转人工、知识维护和审计。后端采用 FastAPI 模块化单体，MCP 作为独立只读服务，PostgreSQL 是事项与办件的权威数据源。

> 所有账号、身份、企业、材料、政策、审核、缴费和邮寄结果均为合成演示数据。本项目没有接入真实政务、短信、支付、人脸、银行或快递平台，不能作为真实办事依据。

## 仓库组成

| 目录 | 作用 |
| --- | --- |
| `backend/` | FastAPI、边界/协调者/领域/基础设施分层、Alembic、JWT、MinIO、RAG 与受控咨询编排 |
| `android/` | `com.example.aicompanion` 本地 WebView 门户、原生边界、协调者、网关与 HMS 地图入口 |
| `mcp-server/` | Node Streamable HTTP MCP，只读调用模拟政务目录 |
| `mock-gov-api/` | 六个演示事项及材料、流程、窗口 REST 数据 |
| `compose.yaml` | PostgreSQL 16、Redis 7、Milvus、etcd、MinIO、API、MCP 与 Mock API |
| `compose.cloud.yaml`、`compose.metastudio.yaml`、`deploy/` | 云端演示 Compose、可选 MetaStudio 覆盖、Docker secrets、HTTPS、备份/回滚和显式付费 RAG 导入脚本 |
| `scripts/` | 环境初始化、启动、迁移、业务验收、AI 验收、日志、测试和非破坏性停止 |

设计说明见 [架构文档](docs/architecture.md)、[业务与领域设计](docs/business-design.md)、[角色权限矩阵](docs/role-permissions.md)、[API 示例](docs/api-examples.md)、[材料 Word 模板生成](docs/material-document-generation.md)、[MetaStudio 接入说明](docs/metastudio-integration.md)、[Navi Kit 导航说明](docs/navigation-integration.md) 和 [云端部署手册](docs/cloud-deployment.md)。

## 前置条件

- Windows 11、WSL2 与 Docker Desktop（Linux 容器后端）。Milvus 建议为 Docker Desktop 预留至少 8 GB 内存和 15 GB 磁盘。
- PowerShell 5.1 或 7；Android 构建还需要 Android SDK/Gradle。
- 外层 `key-list.txt` 中存在拼写为 `deepseeek-key` 的本地 DeepSeek 测试密钥。

本阶段不启动 AVD、不安装 APK，也不做手机界面可视化调试。

## 初始化与启动

在本目录运行：

```powershell
.\scripts\init-env.ps1
.\scripts\dev-up.ps1
```

`init-env.ps1` 将 DeepSeek 密钥安全映射为 `DEEPSEEK_API_KEY`，并随机生成数据库、JWT、MinIO 与内部服务凭据。脚本不会打印密钥；`.env` 已忽略提交。已有 `.env` 只补齐缺项，避免改动现有 PostgreSQL 数据卷对应的密码。

检查服务：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready | ConvertTo-Json -Depth 10
.\scripts\logs.ps1
```

API 文档在本地栈启动后可访问 `http://127.0.0.1:8000/docs`；当前 OpenAPI 共 83 个操作、76 个路径。默认本地栈未启用团队 RAG，`/health/ready` 检查 PostgreSQL、Redis、Milvus、MCP、Mock API、MinIO 和业务种子共 7 项。云端启用固定团队数据集后新增 `rag_corpus`，共 8 项，并校验激活别名准确指向 15,858 条内容向量和 1,012 条文档路由向量。PostgreSQL 宿主调试端口为 `127.0.0.1:15432`，其他本地依赖默认仅在 Compose 网络中可达。

## 演示账号

管理员和工作人员由启动种子幂等创建，群众账号通过注册接口创建。只有在需要人工输入账号时才显式运行：

```powershell
.\scripts\show-demo-accounts.ps1
```

该命令会在当前终端显示本地管理员/工作人员凭据；不要截图、复制到日志或用于云端。`business-smoke.ps1` 会从 `.env` 读取凭据并仅输出状态汇总，不打印密码、Token、材料哈希或表单内容。

角色与申请人类型是两个维度：权限角色为 `CITIZEN/STAFF/ADMIN`；个人和企业群众分别使用 `INDIVIDUAL/ENTERPRISE`，企业不是管理员角色。

## 演示目录与业务

种子目录包含六个已发布演示事项：社会保障卡申领、居民身份证丢失补领、个体工商户设立登记、企业社会保险登记、劳动合同备案、单位住房公积金缴存登记与演示缴付。它们覆盖：

- 受限 JSON 规则资格预检和 JSON Schema 动态表单；
- 必需、条件必需、可选材料，PDF/JPEG/PNG 单文件不超过 10 MB；
- 办件级可填写 DOCX 异步生成：模型只提取白名单字段，正文与 OOXML 由受控渲染器生成，私有文件 24 小时过期；
- MinIO 私有材料、SHA-256 完整性、`NOT_SCANNED_DEMO` 明示状态；
- 乐观锁版本与 `Idempotency-Key`；
- 部门内工作人员认领、补正、驳回、批准和办结；
- 本地模拟预约、身份核验、缴费失败/重试/取消与邮寄推进/取消；
- 公开事项 AI 咨询、持久化多轮会话、SSE 消息气泡、受控材料模板卡、反馈与转人工取消/解决；`local_catalog + MCP + RAG` 三类溯源中 MCP 始终只读，RAG 可融合本地知识与经净化、版本化导入的团队语料；
- 事项—网点多对多目录、UTF-8 CSV 预校验/原子导入，以及仅在手机内使用当前位置排序的 Navi Kit 步行/驾车本地 PoC；
- 管理员部门/窗口/人员、事项版本生命周期、知识索引恢复/重试/归档、审计和指标。

LLM 只解释和建议，不能直接更改办件、审批、缴费、账号或事项状态。私人身份、表单、材料和办件数据不会进入公共 Redis 检索缓存或 LLM 上下文。

## 验收与测试

不调用 DeepSeek 的完整业务 smoke：

```powershell
.\scripts\business-smoke.ps1
```

脚本注册一次随机合成群众账号，完成“社会保障卡申领”的资格预检、两份合成 PDF 上传、提交、工作人员两阶段认领/审批/办结、群众时间线和管理员指标检查；随后只对本轮创建的数据验证模拟邮寄取消、转人工取消，以及合成知识上传后归档。全程不调用 DeepSeek，不删除既有数据库或对象存储数据。

仅在最后需要付费验收时运行 AI smoke：

```powershell
.\scripts\smoke.ps1
```

默认先从公开目录精确选择 `DEMO-SS-CARD-001`，再携带其内部 `service_id` 发起一次真实 DeepSeek 调用；响应必须同时包含 PostgreSQL `local_catalog`、MCP 和 RAG 三类来源。脚本按 `规范化问题 + 外部事项 ID + dataset 版本` 精确检查 Redis `smart-gov:retrieval:v3:*` 键；本地未启用团队 RAG 时 dataset 为 `none`。脚本不输出答案、会话、密钥或 Token。只有显式传入 `-SecondPaidCall` 才会发起第二次模型调用并验证 `cache_hit`。

源码级测试：

```powershell
.\scripts\test-all.ps1
# 首次安装本地依赖：
.\scripts\test-all.ps1 -InstallDependencies
```

测试包含全部 PowerShell AST 校验、Python 单元测试、Mock/MCP Node 检查和测试，以及 Android `lintDebug`、JVM 测试和 `assembleDebug`。不会启动模拟器、安装 APK 或截图。若只检查非 Android 代码，可使用 `-SkipAndroid`。

迁移状态与非破坏升级：

```powershell
.\scripts\migrate.ps1 -StatusOnly
.\scripts\migrate.ps1
```

启动时 API 也会执行 `alembic upgrade head`。当前 head 为 `0009_consultation_materials`：`0005_rag_corpus` 增加版本化团队语料，`0006_metastudio` 增加短期数字人动作意图，`0007_navigation_catalog` 增加导航目录，`0008_material_documents` 增加材料模板目录、异步任务、租约与 24 小时到期索引，`0009_consultation_materials` 增加会话模板意图和不绑定办件的空白模板任务；迁移保留 `0001_initial` 的匿名聊天，脚本不会 downgrade、删表或删除数据卷。

## 主要 API

| 分组 | 说明 | 认证 |
| --- | --- | --- |
| `GET /health/live`、`GET /health/ready` | 进程存活与全栈依赖就绪 | 否 |
| `POST /api/v1/chat`、`POST /api/v1/chat/stream` | 普通/SSE 多轮咨询；流完成事件可返回受控材料卡，可带 `service_id`，私人办件查询还可带 `application_id` | 公开事项可匿名 |
| `GET /api/v1/services/{service_id}/navigation-options` | 已发布事项的活动 GCJ02 网点与线上/线下状态；不接收用户位置 | 匿名 |
| `/api/v1/auth/*` | 演示验证码、个人/企业注册、登录、刷新、登出、当前账号 | 按接口 |
| `/api/v1/services/*` | 事项、资格、材料、流程、表单、窗口 | 公开 |
| `/api/v1/applications/*` | 草稿、表单、材料、提交、补正、撤回、丢弃、时间线、邮寄 | 群众；授权人员可读 |
| `/api/v1/applications/{id}/material-template-options`、`/material-documents` | 办件可生成模板、异步生成、状态与私有 DOCX 下载 | 办件所属群众 |
| `/api/v1/consultations/*` | 历史、消息恢复、材料意图确认、反馈、转人工和发起人取消 | 登录 |
| `/api/v1/staff/*` | 待办、认领、审核、办结和人工咨询 | 工作人员 |
| `/api/v1/admin/*` | 组织、人员、账号、事项版本、知识上传/重试/归档、审计、指标 | 管理员 |
| `POST /api/v1/admin/navigation-catalog/import` | UTF-8 CSV 导航目录 dry-run 与整文件原子导入 | 管理员 |
| `/api/v1/appointments/*`、`/payments/*`、`/verifications/*`、`/deliveries/*` | 预约与本地模拟能力；群众可取消未终结支付/邮寄，到场和配送由所属部门人员推进 | 按操作 |

所有提交、审核、预约、缴费等写操作都使用唯一 `Idempotency-Key`；并发编辑以响应中的 `version` 为准，版本或状态冲突返回 409。统一错误语义和请求示例见 [API 示例](docs/api-examples.md)。

## Android 构建与安全边界

```powershell
Set-Location .\android
D:\AndroidDev\gradle-8.14.5\bin\gradle.bat :app:lintDebug :app:testDebugUnitTest :app:assembleDebug
```

当前 debug/release 构建都默认连接 `https://123.249.68.176`，且网络安全配置拒绝明文 HTTP。可用 `-PgovApiBase=https://<域名或IP>` 覆盖，但必须是无用户名、路径、查询和片段的 HTTPS origin，否则构建立即失败。debug APK 生成于 `android/app/build/outputs/apk/debug/app-debug.apk`；本项目只编译和测试，不自动安装 APK、不启动 AVD。

WebView 只加载受信任的本地资产。JS Bridge 仅暴露校验后的命令封包、材料选择、语音开始/停止、`openServiceNavigation(service_id)` 和 `saveGeneratedDocument(generation_id)`；HTTP、Token、DOCX 下载和完整性校验均由原生网关处理。Token 使用 Android Keystore 加密存储，不进入 WebView、日志或明文 SharedPreferences。原生页重新获取活动网点；WebView、数字人和模型都不能传入坐标、URL、包名或任意 Intent。Location Kit 只在用户点击后于前台运行，当前位置不上传项目后端。

Navi Kit `6.13.0.300` 仅在用户点击路线预览后延迟初始化，默认步行并可切换驾车；路线成功后才允许启动应用内逐向 TTS 导航。当前目录和 APK 均为本地 PoC，真机完成算路、语音、偏航重算、匿名确认跳转与权限验收前不得发布。详见 [Navi Kit 导航说明](docs/navigation-integration.md)。

沿用的 AG Connect 身份和包名为 `com.example.aicompanion`，因此 APK 会被 Android 视作旧应用的同一包，本阶段只验证构建。

## 停止、数据与云端边界

```powershell
.\scripts\dev-down.ps1
```

普通停止保留所有命名卷。`docker compose down --volumes` 会不可恢复地删除 PostgreSQL、Redis、Milvus 和 MinIO 数据，自动化脚本不会执行它。

仓库已提供 Linux x86_64 云端演示部署文件：API 仅绑定 `127.0.0.1:18000`，公网由 Nginx 与官方 lego v5.4.0 管理的 Let’s Encrypt `shortlived` IP 证书提供 `https://123.249.68.176`；TCP 80 必须持续开放给无停机 HTTP-01 续期，密钥通过 `deploy/secrets/` 只读挂载。首次部署保持 `RAG_GROUP_ENABLED=false` 并通过 7 项 readiness；确认 DashScope 一次性 embedding 费用后，才可显式运行 `deploy/scripts/import-rag.sh --confirm-paid-import` 导入固定数据集 `team-2026-08-22-v1`，成功后必须通过含 `rag_corpus` 的 8 项 readiness。原始 `RAG_DATABASE .zip` 含废弃凭据及非业务文件，禁止上传；云端只使用忽略提交的净化归档。

完整的 IP 证书、部署、RAG 导入、一次付费 smoke、零额外付费公网验收、流量切换、旧服务备份/恢复和 APK 构建顺序见 [云端部署手册](docs/cloud-deployment.md)。旧 Certbot、域名 TLS-ALPN 脚本仅为历史回退材料，本次 IP 部署禁止调用。这仍是演示环境：Mock API 和 Demo Provider 不是正式政务能力；正式上线前还必须完成真实身份/租户隔离、密钥托管、病毒扫描、授权审计、隐私和合规评估。

MetaStudio 智能交互默认关闭，固定使用方案二“第三方大脑回调”。启用时云端会叠加 `compose.metastudio.yaml`，并在启动前强制核验官方 Web SDK 5.0.6 的固定 ZIP/CMS 证据和完整 11 项资产、robotId、北京四项目/App 配置以及文件化 IAM/App secrets；任一缺失都不会降级启动。SIS 只由 MetaStudio 委托调用，后端没有 SIS endpoint 或凭据。唯一 LLM 回调为 `/api/v1/integrations/metastudio/llm`，普通响应与 SSE 共用此路径，Nginx 关闭缓冲且包括 429 分支在内的专用日志都不记录 MSS_A query。Android 10 与 Android 12+ 真机 WebView/RTC/SIS PoC 未全部通过前，数字人 APK 不得发布。详细控制台参数、隐私边界和零付费 smoke 见 [MetaStudio 接入说明](docs/metastudio-integration.md)。
