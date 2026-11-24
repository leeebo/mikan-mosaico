# v78 UI evidence

Board: ESP32_S31_MOSAICO, official ESP-VISION 2026.11.14; 2026-11-23.

`startup-uvc-*.jpg` are actual board UVC JPEGs, byte identical to the three packaged startup frames. `runtime-uvc-guidance.jpg` is a manually checked runtime UVC frame. Native LCD captures are separate 480×480 files. No user camera photographs are included.

`paired-summary.json` records 12 fixed public RGB565 inputs and 260 observations per version. Baseline used one 260-frame run; final candidate used two bounded runs of 114 and 146 frames, each after a hard reset with native UVC active. A previous long candidate run was host-terminated at frame 205; it is excluded from completed results. See final-execution.json. Processing FPS excludes fixture decoding and guard-stage deliberate dwell; it includes snapshot, tracking, drawing, LCD, JPEG/UVC, and scheduled eye inference. Repeated static samples benefit from center composition caching. This is neither a live-camera FPS guarantee nor an optical expression-latency measurement.

All 70 graded-mouth, 35 eye, and 9 diagnostics observations match status, expression, raw geometry, eye observations, and used crop exactly. Recovery-stage differences are retained explicitly: the wall-clock detection cooldown meets different display/replay timing, so the entire 260-frame sequence is not identical. All 132 observations tracking in both versions have identical expression and measurement fields.

Raw logs/video and fixed test images remain in the project-local temporary evidence directory; no private face data is added here.
