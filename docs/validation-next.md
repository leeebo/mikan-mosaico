# Verification status and next experiments

Updated 2026-11-20. All production inference runs on Mosaico with stock ESP-VISION 2026.11.14. PC use is limited to offline preparation and reference calculations. There is no personal calibration.

## Completed first round

[The first mouth investigation](mouth-validation-round1.md) replayed 13 public Talking Face pictures through the board, with nine independent crop variants each (117 inferences). Nineteen actual native 112 × 112 RGB565 inputs were returned and byte/hash-checked before FP32 comparison. All pictures are of one public subject, so this is a bounded diagnosis rather than a multi-person accuracy claim.

Lower inner lips remained inside all 90 labelled crops. A large opening measured 21.29 source pixels manually, 11.92 on the board and 11.78 in FP32. A near-view opening measured 32.41, 11.41 and 10.18 respectively. Some errors came primarily from the upper edge; others pulled both edges inward. Changing only the normalization denominator did not separate pressed lips from genuine slight opening. No fixed crop perturbation improved the batch without regressions.

## Next experiments, not yet completed

1. Add independently held-out public subjects with closed, slightly open, half-open, wide-open and pressed lips, plus teeth, tongue, glasses and occlusions. Establish dataset, pretrained-weight and resulting-model redistribution rights separately.
2. Compare a local upper/lower inner-lip structure model against current PFLD on identical board-captured RGB565 crops. Check teacher pseudo-label errors before training and measure both lip edges, visibility and contact. Keep development examples separate from the held-out evaluation.
3. Measure the complete critical path and source-frame age: camera capture, detector, PFLD, eye patches/inference/voting, renderer, LCD, JPEG, UVC and collection. Separate submission times from physical end-to-end latency. An 8 Hz target is a budget, not a demonstrated result.
4. Test near-range acquisition, steady tracking and reacquisition separately, including true half faces and eye/mouth visibility. Lowering a whole-face coverage threshold alone does not address both safety margins and mouth-point bias.
5. Run joint dynamic sequences with both eyes, mouth, tracking state and timestamps recorded together. Preserve the current two-of-three valid-observation eye rule and verify that mouth updates do not regress.

No new lip model, near-range relaxation, asynchronous LCD API or firmware change was deployed by this investigation.
