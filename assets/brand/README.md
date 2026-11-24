# Mikan 品牌与通知素材

本目录用于v78应用启动页和运行取景通知，不改变角色模型或嘴眼算法。用户已确认原圆润Mikan字标、无启动通知栏，以及品牌组围绕480×480屏幕中心统一放大20%。

| 内容 | 用途 |
| --- | --- |
| `mikan-ui.pack` | 板上读取的MKUI1素材包，77,113 B |
| `mikan-ui.json` | 包大小、SHA-256、坐标及资源预算 |
| `source/startup-*.png` | 已批准的三个设计姿态；猫Logo为生成式图像素材，非相机人像 |
| `source/approved-wordmark-reference.png` | 用户明确选定的光栅字标参考，直接沿用字形，不声称获得同名字体文件 |
| `source/composed-*.png` | 静态中性底图叠加实际眼嘴贴片后的UVC编码源 |
| `source/notifications.png` | 两条通知栏的母版 |
| `source/*.html` | 设计预览辅助；打包以PNG为准 |

包内有8个独立RGB565区域及3张预编码320×240 JPEG。RGB565为小端，每区独立zlib压缩，历史窗口1KiB。板上只保留紧凑品牌合成图、四块眼嘴贴片及三份JPEG；不将三张完整设计图同时常驻内存。

使用Python、NumPy和Pillow在仓库根目录离线重建，不需要设备：

```sh
python tools/bake_brand_ui.py --source assets/brand/source \
  --output assets/brand/mikan-ui.pack
```

重建前保存已验证包；不同Pillow/JPEG或zlib版本可能产生不同压缩字节。若包内容改变，重新核对元数据、运行清单和板上解码，不能直接沿用旧哈希或验证结论。不要把设计PNG当作板上截图；实际截图位于 [v78证据](../../evidence/v78-ui/README.md)。

资源与一次合成写屏的原因见 [v78设计与验证](../../docs/v78-startup-and-guidance.md)。
