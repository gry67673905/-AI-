# 云端部署、备份与回滚当前实现说明

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

## 补录说明

本文依据仓库现有部署脚本与 Compose 文件整理，不执行任何线上操作，也不包含服务器地址之外的凭据。

## 候选发布

新镜像先在回环候选端口启动并完成健康及功能烟测，成功后才原子切换 Nginx；正式端口在切换前保持服务。

## 备份与回滚

发布前备份数据库、对象存储和配置状态，保留上一镜像与上游信息；失败回切应用版本，不执行破坏性数据库降级。
