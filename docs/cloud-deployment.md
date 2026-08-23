# 云端演示部署与 APK 交付

本文描述 `compose.cloud.yaml` 与 `deploy/` 的实际 IP-only 部署顺序。目标是单机 Linux x86_64 演示服务器，当前公网入口固定为 `https://123.249.68.176`。API 只监听 `127.0.0.1:18000`，所有事项、账号、材料、支付和办理结果仍是合成演示数据。

## 部署门槛

- 至少 8 GiB 内存、20 GiB 可用磁盘，Docker Engine 与 Compose v2 可用。
- 安全组和主机防火墙必须持续允许 TCP 80、443。80 不是一次性端口：Let’s Encrypt `shortlived` IP 证书依赖 HTTP-01 无停机续期。
- 外部只暴露 Nginx 的 80/443；API 固定为回环地址 `127.0.0.1:18000`，PostgreSQL、Redis、Milvus、MinIO、MCP 和 Mock API 不映射公网端口。
- DeepSeek、DashScope 和内部凭据只放在 root 所有的文件或 Docker secrets 中，绝不写入命令行、日志、APK 或 Git。
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

此时 readiness 必须恰好为 7 项，迁移必须到 `0005_rag_corpus`。确认一次性 embedding 费用后才运行：

```bash
sudo deploy/scripts/import-rag.sh --confirm-paid-import
```

导入器先做 ZIP dry-run，再使用 PostgreSQL 检查点和 embedding cache 续传。完整成功后才切换 Milvus alias、原子持久化 `RAG_GROUP_ENABLED=true` 并重建 API。最终 readiness 必须恰好为 8 项，`rag_corpus` 核对 `team-2026-08-22-v1`、15,858 条正文和 1,012 条路由。

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

只回滚 Nginx 使用 `rollback-ip-nginx.sh --confirm-rollback`。Compose 应用镜像回滚使用 `rollback.sh --release <已保留release>`；它不会 downgrade 数据库，也不会删除持久卷。

## 6. Android APK

debug/release 的 `GOV_API_BASE` 默认都是 `https://123.249.68.176`，必须是无凭据、无路径、无查询和片段的 HTTPS origin：

```powershell
Set-Location .\android
D:\AndroidDev\gradle-8.14.5\bin\gradle.bat `
  :app:lintDebug :app:testDebugUnitTest :app:assembleDebug `
  -PgovApiBase=https://123.249.68.176
```

debug APK 位于 `android/app/build/outputs/apk/debug/app-debug.apk`。本项目只编译和运行 JVM/静态测试，不自动安装 APK、不启动 AVD、不做手机界面视觉调试。
