# Mikan · Mosaico 单机小猫相机

[![Powered by ESP-VISION](https://img.shields.io/badge/Powered%20by-ESP--VISION-b71927?style=flat-square)](https://github.com/espressif/esp-vision)
[English](README.md)

Mikan 在 ESP32-S31 Mosaico 上捕捉转头、抬头低头、张嘴和左右眼闭合，实时驱动一只橘猫。采集、模型推理、角色合成和显示均在板上运行，无需个人校准。

![板上居中模式的真实 UVC 截图](media/mikan-live-uvc.png)

开机运行应用后默认居中显示猫头。短按实体 **AI** 键切换到相机叠加，跟随脸部位置。两种模式共用嘴眼和单骨架。同一张合成帧送到 LCD 和 USB 摄像头。

## 同一段转头，板上前后对照

![同一段转头在 Mosaico 的前后对照，左侧 v58，右侧 v59](media/yaw-ab.gif)

左侧 v58 每到一个角度就切换整张贴图，右侧 v59 以 2° 间隔预烘焙头部和眼睑素材。两侧共用对称正脸，每个角度只保留一条外轮廓，嘴的位置和倾角随当前角度插值。[静帧对照](media/yaw-ab-keyframes.png) · [耳根与脸颊修复](media/ear-rim-ab.png)

同一段 93 帧转头回放中，相邻画面的平均 RGB 差值 P95 从 **26.65 降到 7.49**。UVC 同时开启时，居中由 3.79 降到 3.13 FPS，叠加由 3.63 降到 2.97 FPS。v59 测得 Python 最低空闲约 144 KB。[帧率与内存测量方法](docs/measurements.md)

## 在板上运行

- [无模型板上回放](docs/run-on-mosaico.md#play-the-model-free-demo) 使用预设关键点，查看转头、单眼和开口渲染。
- [实时人脸跟随](docs/run-on-mosaico.md#run-the-live-camera) 包含 YuNet 和眼态模型。嘴部 PFLD 权重需要另外提供具备使用授权的兼容文件。

Powered by [ESP-VISION](https://github.com/espressif/esp-vision)。实测固件为官方 2026.11.14。
