# v78 external model contracts

The expression models are unchanged from the v77 snapshot. The v78 release adds startup branding and display guidance, not new inference weights.

Live v78 needs two externally supplied, authorized weight files. They are not bundled in this public release. The tested filenames, byte counts and SHA-256 values are in [the manifest](../runtime-manifest.json). Matching shapes alone does not establish equivalent behavior.

## PFLD

Place `pfld-36-presence.espdl` under `runtime/v78/models/lips/`. It takes a 112 × 112 RGB565 face image through ESP-DL preprocessing with BGR channels divided by 255. Output is 73 INT16 values with the tensor exponent: 36 normalized x/y pairs, then a presence score. Points 0–19 are the original lip subset, and points 20–35 cover both eyes. The exact ordering and guards are implemented in [pfld_tracking.py](../pfld_tracking.py).

The pretrained backbone source is [zhaoyk1986/pfld_106_face_landmarks](https://github.com/zhaoyk1986/pfld_106_face_landmarks), commit `b928b7d259a81178c4290142616e4e7ba9cf0e2e`, `output/lite.onnx`. The v78 export adds eye coordinates and a presence output to the lips path. Its pretrained-weight redistribution scope has not been established. The legacy [lip provenance](../../../models/lips/source.json) describes the older 20-point export, which cannot replace this 73-value interface.

## Shared spatial eyelid model

Place `eyelid-spatial-v71-s31.espdl` under `runtime/v78/models/eyes/`. This is an experimental custom model, not the legacy Open Model Zoo classifier. Its ESP-DL interface is a 48 × 32 eye image, BGR/255 preprocessing, and an INT8 tensor of shape 1 × 1152. The logical layout is 16 × 24 × 3 in upper-edge, lower-edge, visibility order. See [eyelid_contours.py](../eyelid_contours.py) for decoding and sampled columns.

Training used public eye imagery and synthetic occlusions. Public accessibility does not by itself establish redistribution rights for the data or resulting weights. The training corpus and this custom export are omitted pending a separate provenance and redistribution review. This release contains its runtime interface and measured results, not a complete training/reproduction package.

The source-only live snapshot cannot start until both compatible model files are provided. The existing [scripted board-rendering demo](../../../docs/run-on-mosaico.md#play-the-model-free-demo) remains available without inference models.
