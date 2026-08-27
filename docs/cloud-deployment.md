# 云端演示部署、MetaStudio 与 APK 交付

本文描述 `compose.cloud.yaml` 与 `deploy/` 的实际 IP-only 部署顺序。目标是单机 Linux x86_64 演示服务器，当前公网入口固定为 `https://123.249.68.176`。规范 API 只监听 `127.0.0.1:18000`；升级验收期间允许 `api-candidate` 并行监听 `127.0.0.1:18001`。所有事项、账号、材料、支付和办理结果仍是合成演示数据。

## 部署门槛

- 至少 8 GiB 内存、20 GiB 可用磁盘，Docker Engine 与 Compose v2 可用。
- 安全组和主机防火墙必须持续允许 TCP 80、443。80 不是一次性端口：Let’s Encrypt `shortlived` IP 证书依赖 HTTP-01 无停机续期。
- 外部只暴露 Nginx 的 80/443；API 固定为回环地址 `127.0.0.1:18000`，PostgreSQL、Redis、Milvus、MinIO、MCP 和 Mock API 不映射公网端口。
- DeepSeek、DashScope、MetaStudio App Key、华为云 IAM AK/SK 和内部凭据只放在 root 所有的文件或 Docker secrets 中，绝不写入命令行、日志、APK 或 Git。
- 云端只上传 `artifacts/rag/group-rag-sanitized-v1.zip`；禁止上传含废弃凭据和非业务文件的原始 RAG ZIP。

## 1. 预检、Docker 与 secrets

IP-only 预检不要求域名：

```bash
sudo deploy/scripts/preflight.sh \
  --public-ipv4 123.249.68.176 \
  --https-security-group-confirmed
```

需要安装 Docker 时，对同一组参数运行：

```bash
sudo deploy/scripts/install-docker.sh \
  --public-ipv4 123.249.68.176 \
  --https-security-group-confirmed
```

用权限为 `600` 的临时文件导入两项外部密钥：

```bash
sudo env \
  DEEPSEEK_API_KEY_FILE=/root/secure/deepseek.key \
  DASHSCOPE_API_KEY_FILE=/root/secure/dashscope.key \
  deploy/scripts/init-cloud-secrets.sh
```

脚本随机生成数据库、JWT、PII、MinIO、内部服务和演示账号凭据，不打印值。`deploy/secrets/`、`deploy/state/`、`deploy/releases/`、备份和 RAG 归档均忽略提交；DashScope secret 使用 root:root `0400`，其他 secret 使用 `0600`。

## 2. 首次发布与团队 RAG

首次启动保持 `RAG_GROUP_ENABLED=false`：

```bash
sudo deploy/scripts/deploy.sh \
  --public-ipv4 123.249.68.176 \
  --https-security-group-confirmed \
  --release 20260823-demo1
sudo deploy/scripts/health-check.sh --expect-rag disabled
```

此时 readiness 必须恰好为 7 项，迁移必须到当前 head `0008_material_documents`；MetaStudio 保持关闭不会触发供应方调用。确认一次性 embedding 费用后才运行：

```bash
sudo deploy/scripts/import-rag.sh --confirm-paid-import
```

导入器先做 ZIP dry-run，再使用 PostgreSQL 检查点和 embedding cache 续传。完整成功后才切换 Milvus alias、原子持久化 `RAG_GROUP_ENABLED=true` 并重建 API。最终 readiness 必须恰好为 8 项，`rag_corpus` 核对 `team-2026-08-22-v1`、15,858 条正文和 1,012 条路由。

## 2.1 可选 MetaStudio 智能交互

基础云栈始终从 `METASTUDIO_ENABLED=false` 开始，MetaStudio 与团队 RAG 的开关互不替代。需要数字人交互时，先按 [MetaStudio 接入说明](metastudio-integration.md) 放入经供应方校验的 Web SDK 5.0.6 完整资产，填写北京四的 App/Project/robotId 和精确 HTTPS 回调，再导入三项额外 secret。启用状态下 `cloud_compose` 自动合并 `compose.metastudio.yaml`。

部署前零网络静态检查：

```bash
sudo bash deploy/scripts/verify-metastudio-smoke.sh --skip-http
```

缺少 SDK 固定 ZIP/CMS 证据、精确 11 项资产/integrity、真实 robotId、App/Project、IAM AK/SK、App Key，使用占位值，使用非北京四 endpoint，或把密钥直接写入 `cloud.env`，`deploy.sh` 都会在构建和容器变更前失败。SIS 只在 MetaStudio 控制台选择并授权委托，后端不配置或直连 SIS。默认关闭时不会要求这些专有资产或凭据。

Nginx 为 LLM 回调、客户端会话、视觉会话和视觉 WSS 分别配置精确 location；普通 `/api/` 不转发 WebSocket Upgrade。回调与 WSS 都关闭缓冲并使用仅记录规范化 `$uri` 的专用日志，不记录 MSS_A query、Authorization 或完整请求行。切流后可运行以下零付费负向 smoke：

```bash
sudo bash deploy/scripts/verify-metastudio-smoke.sh \
  --base-url https://123.249.68.176 \
  --through-nginx
```

它只发送无凭据或合成错误凭据请求并验证 400/401/403/503、WSS Upgrade 和日志脱敏，不申请 onceCode、不启动数字人、不调用 SIS/DeepSeek。MetaStudio 启用时刻意不请求真实 `client-sessions`；首次真实联调必须另行确认华为云计费、授权和隐私告知。

## 2.2 并行候选 API

上传候选源码前必须运行 `backup.sh`，并额外保存当前 Nginx 配置和 `deploy/state/current-release`。随后安装独立视觉 secret，在 `cloud.env` 固定 `VISION_ENABLED=true`、`VISION_PROVIDER=dashscope`、`VISION_TURN_CLOSE_WAIT_MS=2000`、`VISION_ANALYSIS_GLOBAL_DAILY=20`，再启动候选：

```bash
sudo bash deploy/scripts/deploy-candidate.sh \
  --release 20260825-vision-nav-v3 \
  --public-ipv4 123.249.68.176 \
  --https-security-group-confirmed
```

脚本只构建和启动 `api-candidate` 与无公网端口的 `material-worker-candidate`，使用同一 Compose 项目、数据库、Redis、Milvus、MinIO 和 MCP，不重建或停止规范 API/Worker。候选在 `18001` 完成迁移、live/ready、Worker 心跳、模板导入、MetaStudio 负向签名检查、视觉 WSS Upgrade 和日志静态门禁后，才允许原子切换：

```bash
sudo bash deploy/scripts/activate-ip-nginx.sh \
  --public-ipv4 123.249.68.176 \
  --upstream-port 18001 \
  --confirm-cutover
```

失败时脚本自动恢复完整旧 Nginx；显式恢复可运行 `rollback-ip-nginx.sh --confirm-rollback`。候选不再需要时运行 `stop-candidate.sh`，该脚本只删除候选容器和 marker，不删除镜像、数据卷或规范 API。真机验收通过后，在 Nginx 仍指向 `18001` 时用 `deploy.sh` 发布同一 release 到 `18000`，再以 `--upstream-port 18000` 切回并停止候选。数据库迁移不降级。

## 2.3 材料 DOCX Worker

`cloud.env` 必须固定以下非秘密设置；上传材料、知识、模板源和生成文件四个 bucket 必须两两不同。`preflight.sh` 会在安装或发布前阻止缺失、复用或无全局日额度的配置：

```text
MATERIAL_DOCUMENTS_ENABLED=true
MATERIAL_TEMPLATE_PROVIDER=dashscope
MATERIAL_TEMPLATE_MODEL=qwen3-vl-flash-2026-01-22
MATERIAL_TEMPLATE_DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MATERIAL_TEMPLATE_MANIFEST_PATH=resources/material_templates/v1/manifest.json
MATERIALS_BUCKET=smart-gov-materials
KNOWLEDGE_BUCKET=smart-gov-knowledge
MATERIAL_TEMPLATES_BUCKET=smart-gov-material-templates
GENERATED_DOCUMENTS_BUCKET=smart-gov-generated-documents
MATERIAL_DOCUMENT_RETENTION_HOURS=24
MATERIAL_DOCUMENT_GLOBAL_DAILY_LIMIT=20
```

Worker 镜像包含固定模板包、LibreOffice Writer、Noto CJK 字体和 Poppler，不暴露端口。启用 MetaStudio 的当前部署复用 root-only `vision_dashscope_api_key` 文件作为同一 DashScope 账号凭据；入口脚本将它复制到 Worker 私有 `/tmp` 后降权运行，密钥不进入命令参数和环境快照。Worker 每 5 秒更新私有心跳，候选/规范健康检查均要求心跳新鲜。API 创建任务时写入当前 `RELEASE_TAG`，Worker 只租赁同一发布 lane；本地 Compose 固定使用 `local`，云端不得通过 `cloud.env` 单独覆盖 lane。

`backup.sh` 会镜像上传材料、知识和 `MATERIAL_TEMPLATES_BUCKET` 到备份目录，并在 manifest 中记录三类持久对象。`GENERATED_DOCUMENTS_BUCKET` 受 24 小时生命周期约束，是可重新生成的临时输出，明确不备份。

上线前至少完成一份真实合成材料的 `QUEUED → RUNNING → READY → 鉴权下载`，核对 DOCX MIME、SHA-256、演示页脚和 MinIO 非公开性。真实 Qwen 请求只允许一次；超时、非法 JSON 或供应方失败必须进入 `FAILED`，不得切换 Mock、重试或调用第二模型。完整业务和 Android 保存边界见 [材料 Word 模板生成](material-document-generation.md)。

## 3. 官方 lego 与 IP 证书

证书工具固定为官方 go-acme/lego v5.4.0，独立安装为 `/usr/local/bin/lego-v5`，不覆盖发行版同名包。安装器先验证官方 checksum manifest 的固定 SHA-256，再验证 tar 成员和二进制摘要：

```bash
sudo deploy/scripts/install-lego-v5.sh \
  --archive /opt/smart-gov-assistant/incoming/lego-v5.4.0/lego_v5.4.0_linux_amd64.tar.gz \
  --checksums /opt/smart-gov-assistant/incoming/lego-v5.4.0/lego_v5.4.0_checksums.txt
```

先用 staging CA 验证 raw-IP HTTP-01，再签 production：

```bash
sudo deploy/scripts/issue-ip-certificate.sh \
  --public-ipv4 123.249.68.176 \
  --http-security-group-confirmed \
  --staging

sudo deploy/scripts/issue-ip-certificate.sh \
  --public-ipv4 123.249.68.176 \
  --http-security-group-confirmed
```

脚本要求证书包含 IP SAN、总生命周期为 4–8 天、剩余时间大于 3 天且证书/私钥配对。挑战窗口只临时接管默认 80 vhost，非 challenge 请求继续转发旧 API；失败或中断会恢复原 Nginx。production 成功后安装 root-only 证书对，并启用 `smart-gov-ip-cert-renew.timer`。

续期每天检查两次。证书剩余超过 3 天时直接退出；到阈值后通过持续开放的 HTTP webroot 续期，deploy hook 成对备份/替换证书、执行 `nginx -t` 并 reload，全程不停止 Nginx。旧 `issue-certificate.sh`、`issue-certificate-tls.sh`、`renew-certificate-tls.sh`、Certbot 模板和域名 Nginx 模板仅为历史回退材料，本次 IP 部署禁止调用。

## 4. 一次付费验收与 HTTPS 切流

团队 RAG 完整启用后只执行一次真实 DeepSeek 验收：

```bash
sudo deploy/scripts/verify-cloud-smoke.sh --confirm-paid-chat
```

成功标记绑定当前 release、固定 dataset 和 `local_catalog,mcp,rag` 三类来源，不打印答案、响应体、Token 或凭据。不要为公网验证再调用一次模型。

切换 raw-IP HTTPS：

```bash
sudo deploy/scripts/activate-ip-nginx.sh \
  --public-ipv4 123.249.68.176 \
  --confirm-cutover
```

切流门禁会重新核对 8 个运行镜像的完整 ID、当前 release、RAG marker、唯一付费 smoke、IP SAN、证书/私钥、续期 timer 和内部 8 项 readiness。Nginx reload 后还会核对无 SNI 实际提供的证书指纹，并通过公网 `https://123.249.68.176` 验证 live、ready 8 项、目录、角色登录、确定性歧义 SSE 与结构化 429。SSE 使用本地澄清分支，标记固定 `additional_paid_calls=0`。任何失败或 INT/TERM 都恢复完整旧 Nginx 状态。

## 5. 旧服务备份、退役与恢复

公网验收通过后才可退役旧 API 和后台 timer：

```bash
sudo deploy/scripts/retire-legacy.sh \
  --public-ipv4 123.249.68.176 \
  --confirm-stop-legacy
```

脚本先在线备份旧 SQLite 并执行 `quick_check`，再备份 `.env`、Nginx、unit fragment、代码和 unit 的 active/enabled 状态，且在停止任何 unit 前执行 `sha256sum -c`。停止/禁用、最终 inactive/disabled、公网 HTTPS 8 项或镜像复核任一步失败，trap 都会恢复旧 unit 和旧 Nginx。旧目录与数据不会删除。

显式恢复使用备份目录：

```bash
sudo deploy/scripts/restore-legacy.sh \
  --backup /var/backups/ai-companion-legacy/<UTC时间> \
  --confirm-restore
```

只回滚 Nginx 使用 `rollback-ip-nginx.sh --confirm-rollback`。Compose 应用镜像回滚使用 `rollback.sh --release <已保留release>`；每个 release 会连同当时启用的 MetaStudio 覆盖文件和非密钥环境快照一起恢复。脚本把目标 compose/env 显式传入子健康检查；目标关闭 MetaStudio 时不会因当前版本缺少 MetaStudio secret 而阻塞。目标启动或健康检查失败时，会用原活动环境和原 release 镜像尽力恢复此前运行态并保留失败退出码。回滚不会 downgrade 数据库，也不会删除持久卷。

## 6. Android APK

debug/release 的 `GOV_API_BASE` 默认都是 `https://123.249.68.176`，必须是无凭据、无路径、无查询和片段的 HTTPS origin：

```powershell
Set-Location .\android
D:\AndroidDev\gradle-8.14.5\bin\gradle.bat `
  :app:lintDebug :app:testDebugUnitTest :app:assembleDebug `
  -PgovApiBase=https://123.249.68.176
```

debug APK 位于 `android/app/build/outputs/apk/debug/app-debug.apk`。默认流水线只编译和运行 JVM/静态测试；不启动 AVD，也不执行自动化界面视觉调试。

本轮云端真机候选固定为 `versionCode=3`、`versionName=0.2.1-cloud-test`。只有在用户明确进入真机阶段、确认 USB 设备签名一致后，才使用 `adb install -r`；签名不一致时停止，不卸载、不清除数据。

若构建 MetaStudio 版本，Android 构建还会核对 `assets/metastudio/sdk/` 内的官方 5.0.6 固定 ZIP/CMS 证据、完整 11 项相对资产和 `sdk-integrity.json`。`serverAddress`、robotId 与一次性 onceCode 只能由 `/api/v1/integrations/metastudio/client-sessions` 返回，禁止写入 BuildConfig、WebView 查询串或静态资产。启用数字人意味着华为 SDK 可能把音频/交互直接发送到华为云，必须在界面中先取得用户明确同意；Android 10 与 Android 12+ 真机 PoC 未通过前不得发布数字人 APK。
