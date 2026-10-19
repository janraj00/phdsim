# PST900 / PSTNet upstream source

Source: https://github.com/ShreyasSkandanS/pst900_thermal_rgb
Commit: `47bbf0133b29e05c7a087b71fb27e8cd8c092ec8`
Authors: Shreyas S. Shivakumar, Neil Rodrigues, Alex Zhou, Ian D. Miller,
Vijay Kumar, Camillo J. Taylor (PST900, ICRA 2020).
License: GPL-3.0, reproduced in LICENSE in this directory.

Derived files:
- `src/phdsim/perception/pstnet/rgb.py`: original RGB Net, renamed PstRgb;
  torchvision weights=None API, omitted CUDA demonstration and commented debug code.
- `src/phdsim/fusion/pstnet/blocks.py`: original three ERFNet blocks.
- `src/phdsim/fusion/pstnet/model.py`: original fusion layers and operations;
  injected RGB model, explicit cached RGB output, vectorized per-image min/max;
  removed implicit checkpoint loading, sys.path mutation and forced CUDA.

Original inference uses bilinear resize to 360x640, RGB /255 (no ImageNet
normalization), thermal zeros filled with OpenCV INPAINT_NS radius 10 after
resize, and 5-class global pixel IoU. These semantics are retained.

`reference/` contains the two unmodified upstream model definitions and
Eduardo Romera's `eval_iou.py`, used only by numerical parity tests. Exact
source paths and SHA256 hashes are recorded in `reference/source.json`.
Random weights in those tests validate operations, not segmentation quality.

Published weights are NOT included. Both official links failed on 2026-10-17:
Dropbox returned an HTML error page; Google Drive returned HTTP 404.
No checkpoints found in 18 public GitHub forks or Hugging Face model search.
Numerical reproduction remains unverified until valid checkpoints are supplied.
