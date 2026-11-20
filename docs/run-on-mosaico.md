# Run Mikan on Mosaico

> Historical v59 material. For the current source snapshot see [v77 setup](run-v77.md) and [current status](current-v77.md).

The reference device is an **ESP32-S31 Mosaico** running stock **ESP-VISION 2026.11.14**. Use the Device CLI bundled with your installed ESP-VISION plugin. Set the shell variables `CLI` to the installed `cli/device-cli.mjs` path and `PORT` to your board's serial port. Run these commands from the root of the Mikan checkout. [ESP-VISION project](https://github.com/espressif/esp-vision)

```sh
node "$CLI" inspect --port "$PORT" --fields identity --json
```

Confirm the device and firmware before uploading. If a previous Mikan instance is running on the selected board, stop it first with `node "$CLI" control --action stop --port "$PORT"`. The examples upload to `/flash/memoji-camera` and start explicitly. They do not replace `main.py`.

## Play the model-free demo

Upload the renderer and its atlas.

```sh
node "$CLI" files mkdir /flash/memoji-camera --recursive --port "$PORT"
node "$CLI" files write /flash/memoji-camera/kitten_rig.py --file kitten_rig.py --port "$PORT"
node "$CLI" files write /flash/memoji-camera/kitten-rig.pack --file assets/kitten-rig/kitten-rig.pack --port "$PORT"
node "$CLI" files write /flash/memoji-camera/kitten-rig.json --file assets/kitten-rig/kitten-rig.json --port "$PORT"
node "$CLI" python --file examples/pose_replay.py --completion wait --timeout 46000 --port "$PORT"
```

When the console prints `REPLAY_ARMED`, start viewing the Mosaico USB camera within 12 seconds. Select 320 × 240 MJPEG if your viewer offers a format selector. Mikan sweeps left and right on the LCD and webcam, with frame indices along the lower edge for matching captures. The console first checks that both single-eye closures and an open mouth produce distinct images, then reports `REPLAY_PASS 93` after the sweep.

## Run the live camera

The model interface and exact tested files are listed in [runtime-manifest.json](../runtime-manifest.json). The bundled YuNet and Open Model Zoo exports are ready to upload. Supply your authorized ESP-DL lip model at `models/lips/pfld-lips-mixed-minmax.espdl`. It must accept a 112 × 112 face crop, with BGR channels divided by 255, and return 20 normalized x/y lip landmark pairs in PFLD indices 52–71 order. The tested export uses an INT8 backbone and an INT16 final layer for ESP32-S31. A different export needs its own board validation. [PFLD provenance](../models/lips/source.json)

The following Bash commands verify that every input exists before starting uploads.

```bash
(
  set -e
  files=$(python3 - <<'PY'
from hashlib import sha256
from pathlib import Path
import json

manifest = json.loads(Path("runtime-manifest.json").read_text())
for item in manifest["required"]:
    path = Path(item["source"])
    if not path.is_file():
        raise SystemExit(f"Missing {path}")
    if item.get("provision") != "user-supplied":
        if sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise SystemExit(f"Hash mismatch: {path}")
    print(item["device_path"], path, sep="\t")
PY
  )
  node "$CLI" files mkdir /flash/memoji-camera --recursive --port "$PORT"
  while IFS=$'\t' read -r device_path source; do
    node "$CLI" files write "$device_path" --file "$source" --port "$PORT"
  done <<< "$files"
  node "$CLI" python --path /flash/memoji-camera/app.py --completion start --port "$PORT"
)
```

The LCD starts in centered mode. A short press of the **AI** key toggles the camera overlay. Open the board's USB webcam on a host to view the same composition. The host acts as a viewer. The Mosaico runs all tracking and rendering.

## Rebuild the yaw atlas

This optional offline step needs Python with NumPy, SciPy, and Pillow. The committed atlas is ready to use. The build inputs include the original artwork and the v58 rig metadata and jaw texture used for v59.

```sh
python3 tools/bake_kitten_yaw.py --base tools/bake-input --output build/yaw --size 124 --step 2
```
