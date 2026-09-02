# MetaStudio 数字人当前实现与边界说明

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

## 补录说明

本文依据仓库当前状态整理，是课程验收用的 retrospective evidence，不声称对应 Issue 在原始开发前创建。

## 当前实现证据

`MetaStudioHttpBoundary` 提供第三方大脑回调、客户端会话和操作意图交换；`MetaStudioCoordinator` 负责编排上下文与回答；`DigitalHumanActivity` 将华为页面、权限及生命周期限制在独立宿主内。

## 安全边界

数字人 WebView 不接收业务 JWT、云厂商密钥或任意 Intent。模型输出只能携带白名单化的短期意图，真正业务写入仍由原工作台确认。
