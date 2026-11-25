# Mikan · a private USB cat camera for Mosaico

[![Powered by ESP-VISION](https://img.shields.io/badge/Powered%20by-ESP--VISION-b71927?style=flat-square)](https://github.com/espressif/esp-vision)
[简体中文](README.zh-CN.md)

Mikan starts with a ginger cat instead of showing the person and room. Capture, inference, rendering, LCD and USB UVC run on **ESP32-S31 Mosaico**, using official **ESP-VISION 2026.11.14**, without personal calibration.

The current public source candidate is **v80**, published 2026-11-25 with board evidence from 2026-11-24. It removes coupled eye rules and adds a RAW path without inference or overlays. **Startup/camera allocation and USB disconnect failures remain unresolved. Compatible authorized PFLD and custom eyelid weights must be supplied separately. This is not a complete ready-to-run model bundle or a fully accepted stable release.** [Model contracts](runtime/v80/models/README.md)

[Setup](docs/run-v80.md) · [18-file manifest](runtime/v80/runtime-manifest.json) · [Implementation and evidence](docs/v80-direct-and-raw.md) · [Handoff](HANDOFF.md) · [Documentation](docs/README.md)

## Controls and output

| AI button | Action |
| --- | --- |
| Short press | Cat → camera overlay → RAW → cat |
| Hold at least 650ms, then release | Return to cat |

Live mode is not persisted. An observed USB stream transition returns to cat; a reopen faster than the application observation interval is not guaranteed. Overlay tracking loss temporarily selects the private cat. RAW deliberately exposes the camera and does not depend on tracking. Cat mode still captures images locally for inference; it does not disable the sensor. An overlay is not a guarantee of anonymity. The application adds no recording or network transmission.

Each eye independently maps the current valid gap `<= .096` to closed, otherwise open/neutral. There are no votes, coupled conditions, candidates or holds. Model mistakes therefore appear directly. The existing mouth-first, usually post-display eye scheduling remains. The firmware, weights, eye measurements and mouth geometry are unchanged from v78.

RAW writes the source directly to the LCD, skips tracking, expression inference, labels, guidance and scene composition, and only adapts dimensions for USB when required. Encoding and LCD transfer still cost time. The default shared pixel buffer returns to 204800 B, saving 152704 B from the larger experiment; notification text returns to the softer v78 scaled rendering.

## Verified scope and open failures

| Check | Result |
| --- | --- |
| Portable policy checks | 29 host and MicroPython checks passed |
| v78/current-eye fixed-input comparison | 105 frames each; mouth, tracking, crop and raw eye measurements agree; direct mapping matches |
| RAW fixed-input comparison | 120 observations each; 119 RAW frames preserve source pixels; steady median 116→81 ms, about 30% less |
| Mode and control regressions | 84 mode/guard frames and 90 software-button/actual host UVC reconnect frames passed |
| Physical sensor smoke test | 80 frames, UVC 80/80; 20 RAW frames median 129 ms; no valid face tracking |
| Deployment identity | 18 original file byte counts and SHA256 verified |

Fixed-input tests replace camera samples. Software buttons do not count as physical button acceptance. Controlled timing excludes fixture decoding/hashing/logging. The physical sensor smoke test uses a software mode sequence without replacing camera pixels. It does not establish facial accuracy or optical latency. Neither timing figure is delivered camera FPS. Negotiated USB is 320×240 MJPEG at 10 Hz.

A larger canvas disconnected USB in three model/video runs. Restoring the v78 buffer passed bounded checks, but after the successful physical sensor run a later production relaunch failed to allocate the camera DVP backup buffer and USB disconnected again. A requested hard reset and explicit main launch recovered the cat view. **The smaller buffer does not solve all startup/stability failures.** [Failure record](evidence/v80-direct/startup-stability.json) · [All measured scope](evidence/v80-direct/README.md)

Natural eye/mouth behavior, physical buttons, long-duration camera operation, resource peaks and complete physical power-cycle autostart remain unaccepted. Large-mouth underestimation, pressed-lip false opening, glasses and near-range recovery remain open. [Next work](HANDOFF.md)

## Source and deployment

Current modules are under `runtime/v80/`; the manifest includes 17 runtime dependencies and a separate candidate `main.py` entry. Source byte hashes match the recorded development checkpoint; only manifest paths and publication metadata differ. Upload each supplied or externally provisioned file to its explicit manifest device path, verify it, and start the independent v80 entry before considering main replacement. Root `app.py` and root `runtime-manifest.json` remain historical v59 entries.

The v78/v77 snapshots and model-free scripted rendering demo are preserved. The demo renders preset landmarks and does not recognize camera expressions. Public history is separate from local research history. Personal images, raw logs, dataset crops, experimental caches and the two external model weights are omitted. [Third-party notices](THIRD_PARTY_NOTICES.md)

## How the cat turns

One six-bone rig drives the head, jaw, eyelids, muzzle, and nose. Artwork is projected offline onto an approximate depth surface. The v59 atlas samples yaw every 2° and stores only one side, with the opposite side mirrored around a shared frontal view. Each angle has one outer contour, and the jaw's position and lip line follow the current view. The board decodes only the current head and eyelids.

<p align="center">
  <img src="media/yaw-ab.gif" width="490" alt="Synchronized turn from actual Mosaico output: five-angle v58 on the left and finer-angle v59 on the right">
  <br><em>Same 93-frame scripted turn on the board. Left: v58. Right: v59. Enlarged UVC crops, paced for comparison.</em>
</p>

[View keyframes](media/yaw-ab-keyframes.png) · [View the earlier ear-to-cheek contour fix](media/ear-rim-ab.png)

Powered by [ESP-VISION](https://github.com/espressif/esp-vision).
