# Current application snapshot: v77

Updated 2026-11-20. [Runtime source and manifest](../runtime/v77/runtime-manifest.json) · [Live setup](run-v77.md) · [Next verification](validation-next.md)

The v77 source is copied byte-for-byte from the locally tested checkpoint `2357bb8`. That identifier describes the private development checkpoint; this publication has its own public history. The first-round mouth report was added after that checkpoint. Public evidence contains numerical summaries only.

## Runtime and interaction

- Color QVGA camera, all inference and composition on ESP32-S31 Mosaico, stock ESP-VISION 2026.11.14.
- YuNet seeds initial acquisition and unreliable-crop recovery. Stable faces use PFLD each frame, with controlled translation and scale updates.
- Twenty lip points produce continuous current-frame mouth opening. The production path has no image-brightness compensation that can reverse the opening curve.
- PFLD anchors two 48 × 32 eye crops. One small spatial model is reused for both eyes. Median visible lid gaps feed independent two-of-three valid-observation votes. A stale eye eventually returns to neutral.
- A confirmed face may survive one unreliable eye patch when current face presence, geometry, visible mouth and the other eye remain reliable. Full loss and half faces retain rejection guards.
- The single rig and yaw atlas render the cat. Centered mode is default, short AI press switches the camera overlay, and a hold of at least 650 ms toggles the landmark view. Pitch and eyebrow effects are disabled.
- The composed image feeds both LCD and UVC. Eye patches are captured before composition; current-eye inference normally runs after LCD/UVC submission, so eyes and mouth can have different observation ages.

## Measurements and limits

The v77 joint replay retained tracking and mouth in 8/8 frames for each single-eye synthetic-glare sequence; the previous right-eye sequence retained 0/8. Removing one eye's local quality evidence preserved mouth and the other eye in 16/16 frames. Both-eye failure was rejected in 4/4 frames. Normal joint sequences matched the previous version in 60/60 frames. These are controlled replay checks, not a natural-blink recall estimate. [Details](v77-joint-stability.md) · [Numbers](../evidence/v77-joint/measurements.json)

The latest preceding complete paired performance run was v75/v76, not a new v77 performance benchmark:

| v76 controlled replay, UVC enabled | Centered | Overlay |
| --- | ---: | ---: |
| Processing FPS | 6.33 | 3.85 |
| LCD submission P50 / P95, ms | 89 / 158 | 154 / 155 |

Overlay minimum Python free heap was 277,376 B; IDF total free / largest block was 139,767 / 31,744 B. Repeated static frames let centered mode reuse composition. Replay timings start after fixture unpacking, exclude camera acquisition, and do not establish live camera or optical latency. [Paired measurements](../evidence/v76-eye/measurements.json)

Remaining problems include near-view safety margins and recovery thresholds, underpredicted wide-mouth gaps, pressed-lip false openings and glasses-related eye errors. Increasing sensor resolution alone did not fix lip bias; the current full color VGA production path failed a contiguous 614,400 B camera-buffer allocation. [Near-range diagnosis](v77-near-range-resolution.md)

The [new same-input mouth investigation](mouth-validation-round1.md) narrows the mouth problem to landmark prediction and crop sensitivity on its tested cases. Independent-person validation and a local lip-model comparison are still pending. End-of-test restoration checked 12 runtime file hashes, eye-vote logic, the LCD cat and 32 decoded UVC frames. Firmware was unchanged.
