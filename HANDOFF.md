# Mikan project handoff · v78 public snapshot

Published 2026-11-24 from the verified local checkpoint `e7feab2`. This document describes that snapshot, not the current physical state of a device or later uncommitted development.

## Start here

- [Setup](docs/run-v78.md) · [15-file deployment manifest](runtime/v78/runtime-manifest.json)
- [Runtime source](runtime/v78/pfld_app.py) · [v78 implementation and measurements](docs/v78-startup-and-guidance.md)
- [Model contracts](runtime/v78/models/README.md) · [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Selected evidence](evidence/v78-ui/README.md) · [Documentation index](docs/README.md)

## Preserved behavior

All camera capture, detection, expression inference, single-rig rendering, LCD and UVC output run on Mosaico with ESP-VISION 2026.11.14. There is no personal calibration. Mouth opening is continuous and prioritized for the current frame. Eyelids use independent two-of-three valid-observation votes. Centered cat is default; a short AI press switches overlay, a hold of at least 650ms toggles landmarks. Pitch and eyebrow effects are disabled.

The expression models are unchanged from v77. v78 adds the Mikan brand screen, preset eye/mouth startup patches and evidence-based bottom guidance. It keeps the firmware and original main.py untouched; automatic power-cycle startup is not configured by this snapshot.

## Verified scope

The final candidate completed two bounded public-input runs: 114 expression/landmark observations and 146 recovery/guidance observations. All 114 stable outputs match v77, and the 132 observations tracking in both versions have identical expression measurements. Recovery has 13 state differences under the wall-clock detection cooldown. UVC submissions were 260/260. Centered/overlay processing throughput was 6.300/3.954 FPS. These are controlled replay figures, not a live-camera accuracy or optical-latency guarantee. A previous continuous run was host-terminated at 205 frames and is excluded from completed results.

Native 480 LCD captures show the complete startup brand and the cat with a bottom notice. The startup worker, real-camera 24-frame smoke test, sprite decoding and exact deployment hashes passed. [Full evidence and caveats](docs/v78-startup-and-guidance.md)

## Open challenges and next work

1. **Guidance clarity:** reusing the 320-square buffer avoids full-screen memory pressure, but the guidance page is scaled and its text is visibly soft. Improve the notification without shrinking the cat or regressing the normal native 320 rendering.
2. **Mouth geometry:** large-opening underestimation and pressed-lip false opening also occur in FP32 on exact RGB565 inputs. Increasing animation gain or changing a denominator alone is insufficient. [Same-input investigation](docs/mouth-validation-round1.md)
3. **Eye reliability and near range:** glasses, light closure, single-eye actions and boundary rejection still need held-out and joint dynamic validation. [Algorithm plan](docs/validation-next.md) · [Near-range evidence](docs/v77-near-range-resolution.md)
4. **Reproducibility:** compatible authorized PFLD and custom eyelid weights must be supplied separately. Shapes alone do not establish equivalence. The public package is not a complete ready-to-run live bundle.

Keep device ownership serialized, application paths distinct and temporary captures project-local. Check actual board identity before hardware access. Preserve mouth/eye behavior and qualify measurements by their tested scope. The public branch keeps a separate release history; do not push local research history or personal captures as a shortcut to updating it.
