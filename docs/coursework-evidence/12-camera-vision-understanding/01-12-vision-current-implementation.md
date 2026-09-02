# 摄像头视觉链路当前实现说明

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

## 补录与目标

本文以当前仓库为证据说明视觉能力：本地持续预览、按回合筛选关键帧、短期上传并融合回答，而不是保存或上传完整视频。

## 客户端实现

`CameraXVisionController` 管理预览和分析，帧选择与 JPEG 编码组件控制变化、尺寸和字节数，`VisionWebSocketGateway` 负责带 ACK 的受控传输。

## 服务端实现

`VisionCoordinator` 管理会话、临时帧与模型分析；票据和帧均有时限，原始图片不进入数据库、对象存储或公共缓存。
