# 视觉帧协议与融合追踪矩阵

> 课程验收补录 / retrospective evidence：内容依据仓库在 GitHub 实际创建时的代码、接口、文档与测试整理；它不倒填历史日期、不伪造原开发过程，完成与未完成状态均按证据如实标注。

## 证据边界

本文件针对“摄像头与视觉理解”整理当前仓库可核查事实；它不是原开发日期的伪造记录。

### 关联路径

- `backend/app/application/vision.py`
- `backend/app/infrastructure/vision.py`
- `android/app/src/main/java/com/example/aicompanion/metastudio/vision/CameraXVisionController.java`
- `android/app/src/main/java/com/example/aicompanion/metastudio/vision/VisionWebSocketGateway.java`
- `backend/tests/test_vision.py`

### 关联接口或符号

- `POST /api/v1/integrations/metastudio/vision-sessions`
- `WSS /api/v1/integrations/metastudio/vision/ws`
- `VisionCoordinator`
- `CameraXVisionController`
- `VisionFrameSelector`
- `DocumentJpegEncoder`

## 会话与鉴权

登录客户端先通过 `/vision-sessions` 获取短期会话和票据，再以 Authorization 请求头连接固定 WSS 路径；票据不进入 URL 或 WebView。

## 帧与事件

二进制消息由大端头长度、UTF-8 JSON 元数据和 JPEG 组成；服务端逐帧 ACK，并用回合和文档序号隔离异步结果。

## 融合边界

语音问题、可见物品、OCR 文本和政务关键词可进入回答或检索；人物外观不能决定权限、资格、审核或业务状态。
