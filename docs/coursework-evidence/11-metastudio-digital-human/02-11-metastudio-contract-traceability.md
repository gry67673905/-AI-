# 数字人协议与代码追踪矩阵

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

## 接口追踪

记录 `/integrations/metastudio/llm`、`/client-sessions` 与 `/action-intents/{intent_id}/exchange` 的调用者、校验器、协调器和响应职责。

## 流式语义

SSE 响应使用 `data:{...}` 增量帧并以 `data:[DONE]` 结束；最终扩展参数与最后一段真实文本一起返回，避免制造额外播报内容。

## Android 边界

包装页消息经过固定策略解析，原生只接受已知事件与意图；WebView 网络、权限和页面跳转均由专用宿主约束。
