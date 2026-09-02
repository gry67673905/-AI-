# 发布资源与状态追踪矩阵

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“云端部署、备份与回滚”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `deploy/scripts/deploy.sh`
- `deploy/scripts/backup.sh`
- `deploy/scripts/rollback.sh`
- `compose.cloud.yaml`
- `deploy/nginx/smart-gov-ip-https.conf.template`

### 关联接口或符号

- `deploy/scripts/deploy-candidate.sh`
- `deploy/scripts/verify-public-cutover.sh`
- `deploy/scripts/health-check.sh`
- `deploy/scripts/stop-candidate.sh`
- `RELEASE_TAG`
- `127.0.0.1:18000 / 127.0.0.1:18001`

## 镜像与服务

文档关联 RELEASE_TAG、正式/候选 Compose 服务、镜像摘要、回环端口与健康端点，避免仅凭可变标签判断版本。

## 代理路由

Nginx 为普通 API、SSE 和视觉 WSS 使用明确路由；WSS 配置 Upgrade，SSE 关闭代理缓冲，日志不记录鉴权值。

## 状态与回滚

current-release 及备份元数据在健康通过后更新；回滚读取上一已验证版本，并在切换后再次执行公开健康检查。
