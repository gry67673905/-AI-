# 成都政务消息远端基线与缺口说明

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“成都政务消息”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `README.md`
- `backend/app/boundaries/http.py`
- `backend/app/infrastructure/records.py`
- `android/app/src/main/assets/index.html`
- `android/app/src/main/assets/portal-app-v2.js`

### 关联接口或符号

- `build_business_router`
- `PortalJsBoundary`
- `GET /api/v1/services`
- `GET /api/v1/consultations`
- government-news routes absent at frozen main

## 补录说明

本文核对冻结 main 的 README、路由、数据模型和 Android 门户；该快照没有成都政务消息实现，本文不把本地未提交代码或抓取时间伪造成 Git 历史。

## 现有基线

冻结 main 只提供合成演示目录和咨询等能力，明确不连接真实政务平台；当前不存在来源注册表、抓取 worker 或消息记录表。

## 缺口边界

当前不存在 government-news 公共 API、Android 消息页或官方原文命令；这些内容只作为后续任务，不计为已交付功能。
