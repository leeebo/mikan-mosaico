# Third-party models and runtime

- **YuNet.** OpenCV Zoo's face detector, converted to a 160 × 160 ESP-DL binary for ESP32-S31. The original MIT notice is included. [Source and version](models/yunet/source.json) · [MIT notice](models/yunet/LICENSE)
- **open-closed-eye-0001.** Intel / OpenVINO Open Model Zoo. The bundled ESP-DL export converts the original classifier to W16A16 and adds explicit softmax. [Source and modifications](models/eyes/source.json) · [Apache 2.0 license](models/eyes/LICENSE.original) · [Upstream model record](https://github.com/openvinotoolkit/open_model_zoo/blob/2c9b5c563ab3a202d085a42e2bbfc48f77961f4b/models/public/open-closed-eye-0001/model.yml)
- **PFLD.** The live mouth path uses a 20-point lip subset from a 106-point pretrained PFLD model. Redistribution rights for those pretrained weights have not been established, so the export is omitted. The runtime contract and source provenance are provided. [Model details](models/lips/source.json)
- **ESP-VISION.** The application runs on Espressif's firmware and uses its device APIs and ESP-DL runtime. Obtain these separately from Espressif. [ESP-VISION](https://github.com/espressif/esp-vision)

The listed third-party licenses apply to their respective components. This repository does not declare a project-wide license.
