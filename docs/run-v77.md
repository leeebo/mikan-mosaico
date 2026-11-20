# Run the current v77 source

Use ESP32-S31 Mosaico with stock ESP-VISION 2026.11.14 and the installed plugin's Device CLI. This source snapshot needs externally supplied compatible PFLD and spatial-eyelid weights. [Model interfaces and publication scope](../runtime/v77/models/README.md)

Set `CLI` to your installed `cli/device-cli.mjs`, and `PORT` to your specific board's stable serial path. Inspect the board before using it. Run the commands from the public repository root. They deliberately retain the tested v77 device paths `/flash/mikan-v60` and `/flash/memoji-camera`. Those names are historical; they do not select the algorithm version. Check that those application paths belong to this project on your board.

```sh
node "$CLI" inspect --port "$PORT" --fields identity --json
```

The following Bash block verifies all twelve files, including supplied weights, before opening the device for uploads. A different model needs independent board validation. If Mikan is already running, stop that instance before upload. No firmware installation or `main.py` replacement is performed.

```bash
(
  set -e
  files=$(python3 - <<'PYCODE'
from hashlib import sha256
from pathlib import Path
import json
m = json.loads(Path("runtime/v77/runtime-manifest.json").read_text())
for item in m["required"] + m["shared_assets"]:
    p = Path(item["source"])
    if not p.is_file():
        raise SystemExit(f"Missing model or runtime file: {p}")
    b = p.read_bytes()
    if len(b) != item["bytes"] or sha256(b).hexdigest() != item["sha256"]:
        raise SystemExit(f"Tested file mismatch: {p}")
    print(item["device_path"], p, sep="	")
PYCODE
  )
  node "$CLI" control --action stop --port "$PORT"
  node "$CLI" files mkdir /flash/mikan-v60 --recursive --port "$PORT"
  node "$CLI" files mkdir /flash/memoji-camera --recursive --port "$PORT"
  while IFS=$'\t' read -r device_path source; do
    node "$CLI" files write "$device_path" --file "$source" --port "$PORT"
  done <<< "$files"
  node "$CLI" python --path /flash/mikan-v60/pfld_app.py --completion start --port "$PORT"
)
```

Default is a centered cat. Short AI press switches to face-following overlay; hold at least 650 ms for the landmark page, then short press to leave it. There is no calibration. Pitch is disabled. An optional UVC client displays the board's composition; it runs no perception model.

For a rendering-only example that needs no external weights, the [legacy pose replay](run-on-mosaico.md#play-the-model-free-demo) still uses root-level v59 files. It animates scripted landmarks and does not track the camera. The root `app.py` and `runtime-manifest.json` also remain the historical v59 live setup. Use the v77 files above for current development.
