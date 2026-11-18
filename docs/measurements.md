# v57–v59 test notes

- v57 enabled UVC alongside the LCD from one composed frame. The published USB image is 320 × 240 MJPEG. Centered mode composes at 320 × 320 and writes directly to the LCD.
- v58 repaired the ear root to cheek contour at intermediate yaw. [Board captures](../media/ear-rim-ab.png)
- v59 replaced the five head views with 33 samples at 2° intervals, stored as 17 blocks with mirroring. The rig pack grew from 80,259 B to 118,757 B. The indexed textures went from 208 × 208 to 124 × 124 to fit device storage. This trades some static sharpness for smoother changes in angle.

## Rendering comparison

The ESP32-S31 Mosaico ran v58 and v59 on stock ESP-VISION 2026.11.14. The board processed the same 93 scripted landmark sets through the renderer with a fixed mouth expression. The host matched all 93 frames in each recording using on-frame index markers. In this run v59 visited 31 sampled angles. Mean absolute RGB channel difference was computed between adjacent avatar crops in each UVC recording. P95 fell from 26.65 to 7.49 and maximum from 29.67 to 8.87 (scale 0–255). Both independent eye closures and mouth opening produced distinct rendered frames in a separate fixed-pose check.

[Matched captures](../media/yaw-ab-keyframes.png) · [Replay source](../examples/pose_replay.py)

## Full camera pipeline

Both versions used the same public Eyeblink8 near-face input, an active camera and LCD, and a continuously subscribed UVC client. Each combination was measured across two runs. Each run used 20 frames with valid tracking after discarding four warm-up frames. Heap counters are the minimum values observed at fixed post-collection checkpoints.

| Mode | Version | FPS | Render time | Python free heap | Largest IDF free block |
| --- | --- | ---: | ---: | ---: | ---: |
| Centered | v58 | 3.79 | 16.85 ms | 228,240 B | 31,744 B |
| Centered | v59 | 3.13 | 65.19 ms | 144,400 B | 56,320 B |
| Camera overlay | v58 | 3.63 | 11.42 ms | 228,432 B | 31,744 B |
| Camera overlay | v59 | 2.97 | 65.79 ms | 144,384 B | 31,744 B |

The render cost includes loading and decoding the atlas as the pose changes. End-to-end optical latency and rapid human turns were outside this measurement.
