# 运行 v78

适用 ESP32-S31 Mosaico，已验证固件为官方 **ESP-VISION 2026.11.14**。以下操作使用已安装 ESP-VISION 插件随附的 Device CLI。本轮不升级固件，不覆盖设备 `main.py`，不自动安装断电自启。

## 1. 准备与核对

从安装插件的位置找到 `cli/device-cli.mjs`，将它的绝对路径设为 `ESP_VISION_CLI`。选择属于 Mosaico 的串口路径，设为 `MOSAICO_PORT`；多板环境优先使用稳定的 USB by-id 路径。共享设备先检查工作区使用权记录，不能抢占其他项目。

```sh
node "$ESP_VISION_CLI" inspect --port "$MOSAICO_PORT" --fields identity,storage --json
```

以 [runtime-manifest-v78.json](../runtime/v78/runtime-manifest.json) 为唯一部署清单：`required` 加 `shared_assets` 共 **15 项**，每项列出公开仓库源文件、设备路径、字节数和 SHA-256。先核对全部文件；模型或素材缺失时，不用其他历史版本的同名文件替代。

公开包附带YuNet-near，PFLD-36-presence与空间眼睑权重需要自行供应兼容且有授权的版本；详见[外供模型接口](../runtime/v78/models/README.md)。未供应这两项前，实时源代码快照不能完整启动。三个运行权重为 PFLD-36-presence、空间眼睑模型及 YuNet-near。它们与形状相同的其他权重不一定具有相同行为。开发检查点与公开仓库的模型分发范围不同；公开快照可能需要单独供应有授权的 PFLD、眼睑权重。参见[模型来源](../models/lips/source.json)及[模型接口与供应范围](../runtime/v78/models/README.md)。

## 2. 上传到独立目录

先明确停止当前应用，等待命令连接清理完成：

```sh
node "$ESP_VISION_CLI" control --action stop --port "$MOSAICO_PORT" --json
```

本版使用三个设备目录：

| 路径 | 内容 |
| --- | --- |
| `/flash/mikan-v78-ui` | 新入口、应用、跟踪、UI模块和品牌素材包，共5项 |
| `/flash/mikan-v60` | 既有四个公共模块及 PFLD、眼睑权重；路径名属于历史沿用 |
| `/flash/memoji-camera` | YuNet权重、角色包/元数据、UVC预热图 |

如目录不存在，用 CLI `files mkdir <设备目录> --recursive` 创建。然后按清单逐项上传；例如：

```sh
node "$ESP_VISION_CLI" files write /flash/mikan-v78-ui/start.py \
  --file runtime/v78/start_v78.py --port "$MOSAICO_PORT" --json
node "$ESP_VISION_CLI" files write /flash/mikan-v78-ui/mikan-ui.pack \
  --file assets/brand/mikan-ui.pack --port "$MOSAICO_PORT" --json
```

这两条只是示例，不能代替完整15项清单。已有共享文件与清单一致时可复用；五个新文件放在独立候选目录，保留原v77回滚。不要为了腾空间删除不明文件。完整回滚依赖包括旧版应用和跟踪模块；v78清单不包含这两份旧代码的重新部署步骤。

## 3. 启动和观察

上传并核对全部依赖后，显式启动：

```sh
node "$ESP_VISION_CLI" python --path /flash/mikan-v78-ui/start.py \
  --completion start --port "$MOSAICO_PORT" --json
```

启动确认只表示进入脚本执行器，不代表模型加载成功。等待品牌动画切到实时猫头，再观察嘴眼、模式切换及UVC。被动截图不会要求程序重新采集或校准：

```sh
node "$ESP_VISION_CLI" capture screen --output .tmp/current-lcd.jpg \
  --port "$MOSAICO_PORT" --json
```

先在项目内创建 `.tmp/` 临时目录，截图保存于其中。最初可能返回 `DISPLAY_NOT_READY`，可等初始化后再作一次被动截图；不要把首次未就绪当作固件崩溃并反复重启。运行中不要穿插 REPL、设备目录列举或文件读取，它们可能打断程序。停止后再取需要的进度文件。

USB UVC可在支持MJPEG的查看器中查看。已验证的输出模式是320×240 / 10Hz，不能将10Hz传输设置当作10FPS推理能力。

## 4. 操作、回滚与限制

短按AI键切换居中／叠加；按住至少650ms切换关键点页，关键点页短按退出。不需要校准。提示仅根据已有观测给出通用或边界引导，不区分“无人”和“太近”。

v78保留了旧设备目录。若需回滚，先停止应用并清理VM模块缓存，再按原v77部署记录从 `/flash/mikan-v60/pfld_app.py` 启动；不要仅修改新入口的路径而混用两版模块。旧版安装文件可从本地检查点 `2357bb8` 核对恢复。

当前引导页为复用320²缓冲而缩放，文字发虚仍待修复；正常跟随画布保持320原生像素。启动动画只作用于Mikan应用，不改变固件先于应用显示的画面。详见[v78实现与实测](v78-startup-and-guidance.md)。
