# 智慧政务助手全栈骨架

这是一个面向架构联调的智慧政务助手样例。它使用演示数据跑通 Android、FastAPI、LangChain、MCP、PostgreSQL、Redis、Milvus 和 DeepSeek；不代表真实政务政策或办理结果。

## 组件

- `android/`：复用 HMS Android 工程壳的 WebView + ViewModel + Repository 客户端。
- `backend/`：Uvicorn/FastAPI、LangChain 编排、数据库、缓存和 RAG。
- `mcp-server/`：Node MCP Streamable HTTP 服务，包装政务工具。
- `mock-gov-api/`：可被真实政务 REST API 替换的本地模拟服务。
- `compose.yaml`：PostgreSQL、Redis、Milvus、etcd、MinIO 与三个应用服务。
- `scripts/`：密钥初始化、启动、停止、日志和端到端 smoke。

详细调用关系见 `docs/architecture.md`。

## 前置条件

1. Windows 11 启用 WSL2，并安装、启动 Docker Desktop 的 Linux 容器后端。
2. Docker Desktop 建议至少分配 8GB 可用内存；当前 C 盘空间较少，建议把 Docker 磁盘映像放在 D 盘。
3. Android 构建使用现有 SDK 和 Gradle；不需要启动模拟器或连接真机。

当前机器若尚未安装 WSL2/Docker，源码测试和 Android 编译仍可执行，但完整 Compose 验收必须等 Docker 可用。

## 首次启动

在 PowerShell 中进入本目录：

```powershell
.\scripts\init-env.ps1
.\scripts\dev-up.ps1
.\scripts\smoke.ps1
```

`init-env.ps1` 兼容 Windows PowerShell 5.1 与 PowerShell 7；它从项目外层 `key-list.txt` 的 `deepseeek-key` 条目读取 DeepSeek 密钥，生成随机数据库密码、MinIO 凭据和内部 Token，并写入被忽略的 `.env`。脚本不会输出任何密钥值；已有 `.env` 时会保留现有值，并只补齐旧配置中缺失的随机 MinIO 凭据。不要直接轮换 `.env` 中的 PostgreSQL 密码，因为已有数据卷中的数据库密码不会自动同步。

查看状态和日志：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/ready | ConvertTo-Json -Depth 10
.\scripts\logs.ps1
```

停止服务但保留数据卷：

```powershell
.\scripts\dev-down.ps1
```

不启动 Docker 的源码级测试：

```powershell
.\scripts\test-all.ps1
```

首次需要安装 Python/Node 依赖时使用 `-InstallDependencies`；该脚本只编译 Android，不启动模拟器或安装 APK。

## API

### 存活检查

```http
GET /health/live
```

### 全栈就绪检查

```http
GET /health/ready
```

只有 PostgreSQL、Redis、Milvus、MCP 和模拟政务 API 全部健康时才返回就绪。

### 政务问答

```http
POST /api/v1/chat
Content-Type: application/json

{
  "session_id": "可选 UUID",
  "message": "办理社会保障卡需要哪些材料？"
}
```

响应包含 `request_id`、`session_id`、`answer`、`sources`、`tool_calls`、`cache_hit` 和 `warnings`。MCP 或 Milvus 单项不可用时允许降级，并通过 `warnings` 明示；DeepSeek 失败不会被模板答案掩盖。

## 本地端口

| 服务 | 地址 | 说明 |
| --- | --- | --- |
| FastAPI | `127.0.0.1:8000` | Android 模拟器对应 `10.0.2.2:8000` |
| PostgreSQL | `127.0.0.1:15432` | 避开本机旧 PostgreSQL 的 5432 |

Redis、Milvus、MCP、模拟政务 API、etcd 与 MinIO 默认仅在 Compose 内网开放；通过 FastAPI 的就绪检查和 smoke 脚本验证其连通性。

## Android 构建

APK 只做编译与接口层测试，不做界面可视化调试：

```powershell
Set-Location .\android
D:\AndroidDev\gradle-8.14.5\bin\gradle.bat :app:testDebugUnitTest :app:assembleDebug
```

debug 后端默认地址是 `http://10.0.2.2:8000`，可在构建时覆盖：

```powershell
D:\AndroidDev\gradle-8.14.5\bin\gradle.bat :app:assembleDebug -PgovApiBase=http://192.168.1.10:8000
```

仅 debug 变体允许为本地联调使用明文 HTTP；主源码中的 release 网络策略默认拒绝明文流量。

沿用的 `agconnect-services.json` 属于 `com.example.aicompanion`；此 APK 会被 Android 视作旧应用的同一包，当前阶段不安装验证。

## 安全边界

- DeepSeek、数据库和内部服务密钥只存在于 `.env`/容器环境，不进入 APK、日志或 API 响应。
- Huawei MaaS key 与 cloud-server key 未被使用，也不会注入任何容器。
- WebView 只加载本地可信资产并限制导航；所有后端请求由原生 Repository 发起。
- 模拟政务数据均带 `is_demo=true`，答案必须保留演示性质提示。
- 上云前必须增加 HTTPS、正式身份认证、用户数据隔离、云端 Secret Manager 和真实 embedding。

## 数据清理

普通停止不会删除数据。若确实需要清空本地数据库和向量数据，请在确认目标项目无误后手动执行：

```powershell
docker compose down --volumes
```

该命令不可恢复，自动化脚本不会默认执行它。
