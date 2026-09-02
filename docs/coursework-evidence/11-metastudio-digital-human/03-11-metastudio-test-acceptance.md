# 数字人测试与演示验收报告

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“MetaStudio 智能交互数字人”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/boundaries/metastudio.py`
- `backend/app/application/metastudio.py`
- `android/app/src/main/java/com/example/aicompanion/DigitalHumanActivity.java`
- `android/app/src/main/assets/metastudio/app.js`
- `backend/tests/test_metastudio.py`

### 关联接口或符号

- `POST /api/v1/integrations/metastudio/llm`
- `POST /api/v1/integrations/metastudio/client-sessions`
- `POST /api/v1/integrations/metastudio/action-intents/{intent_id}/exchange`
- `MetaStudioCoordinator`
- `DigitalHumanActivity`
- `DigitalHumanWebViewHost`

## 自动化证据

后端测试覆盖签名、过期、防重放、SSE 与会话；Android 测试覆盖网关、Manifest、协调器和消息策略。

## 人工验收路径

真机验收需依次检查 SDK 加载、一次点击连续对话、字幕、播报打断、意图确认及退出后的媒体释放。

## 结论限制

文档只汇总已有证据；云端配额、华为控制台状态与设备网络仍是运行时外部条件，不在补录中伪造成永久可用。
