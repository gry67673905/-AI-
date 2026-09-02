# 视觉测试与失败场景验收报告

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

## 自动化覆盖

后端覆盖票据、帧上限、乱序、尺寸、ACK、过期和清理；Android 覆盖帧选择、预滚、亮度签名、JPEG 策略和 WebSocket 封装。

## 演示场景

演示应分别验证普通物品问答、文档居中拍照、前后摄像头切换、视觉关闭和模型超时，不使用真实身份证件或个人材料。

## 失败结论

识别失败必须明确告知本轮未得到可靠画面结果；不得把超时、空帧或无效 JSON 表述成已经看见具体内容。
