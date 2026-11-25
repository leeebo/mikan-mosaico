# Mikan project handoff · v80 public source candidate

Published2026-11-25 from development checkpoint `3455116bfaa65ae51f85a16636ff790559ce1fc2`. Most recent device evidence is 2026-11-24. This closeout publishes source and evidence without reconnecting hardware. It does not establish current device availability or resolve the recorded failures.

## Start here

- [Setup and rollback](docs/run-v80.md) · [18-file manifest](runtime/v80/runtime-manifest.json)
- [Runtime modules](runtime/v80/pfld_app.py) · [External model contracts](runtime/v80/models/README.md)
- [Implementation and timing scope](docs/v80-direct-and-raw.md) · [Numerical evidence](evidence/v80-direct/README.md)
- [Startup failure](evidence/v80-direct/startup-stability.json) · [Third-party notices](THIRD_PARTY_NOTICES.md)

## Final behavior

Default CAT protects the person/background. AI short press cycles CAT/OVERLAY/RAW; hold at least 650ms returns to CAT. Observed host stream transitions return to CAT, without clearing still-active tracking except when leaving paused RAW inference. Overlay falls back to private CAT while tracking is unreliable. Modes are not persisted. Physical power-cycle startup is not accepted.

The latest instruction supersedes v78/v79 eye history: current valid gap <=.096 independently maps each eye to closed; otherwise open/neutral. No temporal votes, candidates, hold or bilateral conditions remain. The measurement model and parameters are unchanged. Mouth-first scheduling remains, so no zero-latency claim is made.

RAW avoids inference, labels, rig/pose updates, guidance and scene composition. It preserves the source, writes directly to LCD and only adapts USB dimensions as needed. Native encoding is preferred with a cached fallback after failure. Models remain resident. Firmware stays official2026.11.14; weights, mouth geometry and eye measurement stay unchanged; pitch and eyebrow effects remain disabled.

## Evidence and unresolved work

29 policy checks,105 fixed-input comparison frames,120 RAW observations per version,84 mode frames and90 control/reconnect frames passed. There were119 actual RAW observations after the initial safety CAT frame. Steady controlled RAW processing median116→81ms. Independent physical sensor80-frame smoke test completed UVC80/80, with20 RAW frames median129ms, no valid face tracking. The raw figures are different scenes/protocols, not paired live FPS. [Evidence scope](evidence/v80-direct/README.md)

Three large-canvas runs disconnected USB without manual user operations. The default returns to204800B, saving152704B, and bounded checks passed. However a subsequent production relaunch on the smaller default failed DVP backup allocation and disconnected USB. Hard-reset recovery and an active private CAT LCD were last observed; the full root cause remains unresolved.

Next work: isolate cold/warm startup, camera contiguous-memory and model/UI lifecycle costs; measure real new-frame delivery; validate physical buttons, full power cycles, long-duration operation and joint natural eye/mouth actions. Do not describe the stage closeout as a stable product acceptance. Mouth geometry and near-range limitations persist. [Mouth analysis](docs/mouth-validation-round1.md) · [Near-range evidence](docs/v77-near-range-resolution.md)

## Preservation and publication boundaries

Compatible authorized PFLD and custom eyelid weights must be supplied separately. Their interface shapes alone do not establish equivalent behavior. YuNet and the existing project-created cat artwork retain their prior distribution scope.

The v78/v77 runtime snapshots and historical v59 root rendering demo remain. Restore a historical version only with its matching files and manifest; do not apply its manifest to current modules. Local v79 backups mentioned in the implementation report are not distributed rollback bundles.

Use the installed ESP-VISION plugin/CLI and exact-version official Knowledge, explicit selected endpoints and serialized ownership. Preserve unrelated device files. Temporary images/logs remain project-local. Publication excludes local research history, learning notes, original faces, raw video, dataset crops and two external weights.
