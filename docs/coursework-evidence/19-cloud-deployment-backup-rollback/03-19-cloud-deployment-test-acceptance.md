# 云端发布测试与回滚验收报告

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

## 发布前门禁

发布前门禁包括干净的候选构建输入、完整备份、迁移兼容、容器健康、固定功能烟测和交付制品秘密扫描。

## 切换后核验

核验公网 live/ready、认证负向路径、SSE/WSS、核心只读 API、日志脱敏和容器重启次数。

## 回滚判定

任一关键门禁失败即恢复旧上游并验证旧服务；新加法迁移保留，避免在故障期间执行高风险 schema 降级。
