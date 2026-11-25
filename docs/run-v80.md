# 部署 v80 隐私 USB 摄像头候选

这是源码候选，尚未完成稳定性与真人准确率验收。固件保持官方 **ESP-VISION 2026.11.14**。实时运行需兼容且有授权的 PFLD-36-presence 和空间眼睑权重；公开包不分发这两份权重，不是完整开箱即用模型包。

[18 项清单](../runtime/v80/runtime-manifest.json)是部署依据：`required` 与 `shared_assets` 共 17 项，另有独立的 `autostart` 项。每项包括源文件、设备路径、大小及 SHA-256；先验证完整依赖和外供权重，再修改设备。三个模型及角色仍沿用既有设备共享目录。

1. 使用安装的 ESP-VISION 插件所带 `cli/device-cli.mjs`。明确选择有使用权的 Mosaico 串口稳定路径，先 inspect identity 核对板型、固件。不要按可能变化的 tty 编号盲连或抢占其他会话。
2. 备份当前入口和对应版本文件，显式 stop 并等待 CLI 清理。按清单创建目录，将每个文件上传到其 `device_path`；不能用同名历史模块或仅形状相似的权重替代。
3. stop 状态下核对设备文件大小与 SHA-256。先保留 main 不覆盖，显式启动 `/flash/mikan-v80-direct/start.py`，被动检查 LCD、真实相机及 UVC；启动响应只代表脚本已进入 runner。
4. 明确要求替换原入口且测试结果可接受后，再归档原 main，将 `autostart.source` 安装为 `/flash/main.py`。本项目设备已安装候选 main；这不等于完整断电自启通过，不写 boot.py。
5. 三模式、失跟保护、实际按键、真人表情、长时间稳定性及完整断电启动逐项验收。保存成功与失败的范围，当前 DVP 缓冲申请失败及 USB 断连仍未解决。

CLI 语法示例（先将变量设为实际安装路径及明确选定设备）：

```sh
node "$MIKAN_CLI" inspect --port "$MIKAN_PORT" --fields identity --json
node "$MIKAN_CLI" control --port "$MIKAN_PORT" --action stop --json
node "$MIKAN_CLI" python --port "$MIKAN_PORT"   --path /flash/mikan-v80-direct/start.py --completion start --json
```

运行中仅用被动 inspect/capture；files read/list 与 Python REPL 操作可能中断应用，先显式 stop。当前会话的 `scriptRunning` 不代表其他会话启动的应用是否在运行。reset 后截图可能残留旧帧，不据此宣称自启成功。

本机策略检查：

```sh
PYTHONPATH=runtime/v80 python3 tools/check_product_policy.py
```

[测试与限制](v80-direct-and-raw.md)区分固定输入的 116→81 ms、真实采样的 129 ms 和交付帧率。两个数来自不同场景，不能直接相减。所有临时图像与日志留在项目 `.tmp/`。

回滚需停止应用，并同时恢复旧版本模块及旧 main。公开仓库 `runtime/v78/` 与[旧清单](../runtime/v78/runtime-manifest.json)可用于恢复源文件；当前源码为 `runtime/v80/`，根目录旧演示不是实时入口。v79 未单独提交，保留的设备目录和本地 `.tmp/product-v80/base/` 仅作本机恢复材料，不能假设它们存在于公开包中。不要删除未知设备文件。
