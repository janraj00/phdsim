# PSTNet reproduction and own RGB training

## Upstream identity and task

Source: [PST900 / PSTNet repository](https://github.com/ShreyasSkandanS/pst900_thermal_rgb/tree/47bbf0133b29e05c7a087b71fb27e8cd8c092ec8/pstnet).
Commit: `47bbf0133b29e05c7a087b71fb27e8cd8c092ec8`.
Paper: [PST900, ICRA 2020](https://arxiv.org/html/1909.10980).

The task is five-class pixel segmentation: background, fire extinguisher,
backpack, hand drill and Survivor. Whole-frame binary presence is a separate task.

## Current state

The upstream architecture, preprocessing and global IoU evaluator are implemented.
Tests compare RGB and fusion outputs bit for bit against unchanged upstream
implementations with identical random weights. That establishes operation parity,
not the published performance of trained models.

An own RGB pilot has completed; see [experiment status](EXPERIMENTS.md). It uses
ImageNet encoder initialization and our explicit optimizer settings. Own fusion
and segmentation acquisition have not yet been trained. Exact reproduction from
the authors' checkpoints remains pending their availability.

Official checkpoint sources checked on 2026-10-17:

- [Dropbox weights ZIP](https://www.dropbox.com/s/nregozp2anygdjw/weights.zip): HTML
  error page; the direct-download host returned HTTP 403.
- [Google Drive weights](https://drive.google.com/file/d/1frRfClQQP4th-cjxJwKmBuMXxBw2CYdF/view): HTTP 404.
- No checkpoints found in 18 public forks or the Hugging Face model search.

These are dated observations, not an automatically refreshed availability check.
The upstream repository contains inference code but no PSTNet training script.
Own retraining therefore does not guarantee the authors' exact result.

## Original RGB and fusion computation

1. Resize RGB from 1280 x 720 to 640 x 360, bilinearly, and divide by 255.
   Do not apply ImageNet normalization to the PSTNet inference input.
2. The ResNet18/UNet RGB stream produces five logit maps and an RGB mask.
3. Our gate receives RGB-derived features and transfer metadata.
4. Declining acquisition returns the RGB mask without opening the thermal file.
5. Acquiring delivers the existing paired thermal image. Resize it bilinearly,
   fill zero holes with OpenCV INPAINT_NS radius 10, and divide by 255.
6. Normalize the entire five-channel RGB logit volume with per-image min/max,
   exactly as upstream. This fusion input is not a softmax volume.
7. Concatenate five normalized logit channels, one thermal channel and three RGB
   channels. The original ERFNet-based fusion stream returns the final mask.

The RGB output is cached, so acquisition does not rerun the RGB network. Images
are already registered by the dataset authors. There is one acquisition direction
in this experiment: RGB requests thermal for the same frame, without movement.

## Own RGB pilot

```powershell
.\scripts\pstnet.ps1 -Action train-rgb `
  -TrainingConfig configs\pstnet\rgb_pilot.json `
  -Output runs\pstnet_rgb_pilot_v2 `
  -ModelDirectory D:\Doktorat\Platforma\models\pstnet_rgb_pilot_v2
```

The supplied pilot configuration specifies 48 training and 24 validation frames,
five epochs, batch size one, and six CPU threads. The entire RGB network is
fine-tuned. The encoder starts from torchvision ResNet18 ImageNet V1; the decoder
is initialized randomly with the recorded seed. AdamW, the two learning rates
and gradient clipping are explicit choices of this training run.

The loss weights use training pixels only: `w_c = 1 / ln(1.02 + frequency_c)`.
Mask resize is nearest-neighbor. No augmentation is used in this pilot. Every
class must occur in its training selection.

Validation holds out complete `bag1`, `bag7`, `bag11` recording families.
The 194 frames from `bag4`, `bag5`, `bag6`, `bag8`, `bag12`, `bag17` are reserved
for later acquisition. Original test frames are not loaded for this training or
validation. Frame selection uses names, family round-robin and a seed, never masks
or model scores. Suffix variants of a recording remain in the same family.

Select the highest global validation mIoU, including epoch zero. The report also
shows background-only performance, class IoU, weighted loss and fixed visual
examples. `training.json` is written after every epoch. `model_best.pth` and
`model_last.pth` are separate files; completed checkpoint identity and protocol
are recorded in `training_provenance.json`.

The trainer expects `resnet18-f37072fd.pth` in the default torch hub checkpoint
cache and verifies the full SHA256. Prepare the official initializer if absent:

```powershell
python -c "from torchvision.models import ResNet18_Weights; ResNet18_Weights.IMAGENET1K_V1.get_state_dict(progress=True, check_hash=True)"
```

Use the same Python environment as training. The expected SHA256 is
`f37072fd47e89c5e827621c5baffa7500819f7896bbacec160b1a16c560e07ec`.
Existing nonempty training output/model directories are protected. Resume is not
implemented; a new run requires new destinations. The selected epoch is not
necessarily the final epoch.

## Counterfactual cache, gate fitting and deployment

Paths and the predeclared cost grid are in `configs/pstnet/experiment.json`:

```powershell
.\scripts\pstnet.ps1 -Action status
.\scripts\pstnet.ps1 -Action prepare
.\scripts\pstnet.ps1 -Action cache
.\scripts\pstnet.ps1 -Action learn
.\scripts\pstnet.ps1 -Action run -Cost 0.005
```

`prepare` imports all 597 original train and 288 original test pairs and their
original masks, without the old presence-pilot quarantine. See [data contracts](DATA.md).

`cache` requires both configured `model_best.pth` files. The strict loader accepts
tensor state dictionaries only, normalizes DataParallel prefixes, checks all keys
and shapes, and verifies that embedded fusion RGB weights equal the RGB baseline.
SHA256 identities are stored. There is no fallback to random vision weights.

Offline caching computes both frozen outcomes for supervision. The gate target is
`per-frame five-class IoU(fusion) - per-frame five-class IoU(RGB)`, including
negative examples. Absent classes with zero union contribute zero. This per-frame
surrogate is distinct from the reported global metric.

Ridge inputs are 19 features available from RGB alone: entropy mean, standard
deviation and 95th percentile, predicted-foreground entropy, top-two class margin,
low-confidence fraction, five predicted class fractions, five mean probabilities,
and RGB brightness, contrast and dark fraction. Entropy is normalized by `ln(5)`.
The frozen gate requests thermal when expected gain exceeds the per-image utility
cost; this is not a threshold on RGB uncertainty alone.

The existing pretrained-checkpoint protocol selects Ridge regularization by
held-out recording family within original train. Such pretrained experts may
already have seen those original train images. For own training, preserve the
separate acquisition families and adapt the experiment protocol to that provenance
before using this path. Do not label in-sample expert outputs as held-out meta data.

`learn` compares RGB-only, full fusion, learned gain over the declared cost grid,
entropy thresholds, and seeded random selection at matching pull counts. It fits
no policy parameters on official test labels and chooses no winning cost on test.
The full test has 288 frames. `run` executes actual selective inference; it does
not look up the cache's fused test mask. Its manifest reader loads metadata only,
and checks each image hash when that image is delivered.

## Evaluation and timing

Accumulate pixel confusion over all frames first, compute each class IoU, then
average the five classes, including background. Do not average frame IoUs and
call that the published global mIoU.

Published [upstream log references](https://github.com/ShreyasSkandanS/pst900_thermal_rgb/blob/47bbf0133b29e05c7a087b71fb27e8cd8c092ec8/pstnet/README.md)
are RGB mIoU `0.6765786209506062` and full fusion `0.6836562966338`. The comparison
report records differences and whether both are within 0.001. These are references,
not measurements obtained by the own RGB pilot.

Cache comparisons provide no online latency measurement. Gated replay measures
local image reading, preprocessing, RGB, features, policy and selected fusion,
excluding network transport. Pull bytes refer to the actual delivered PNG. CPU
results are not directly comparable to the authors' 18/42 ms on AGX Xavier.

## Code ownership

Model definitions are under `perception/pstnet/` and `fusion/pstnet/`; policies
under `decision/pstnet/`; fitting under `learning/pstnet/`; execution under
`runtime/segmentation.py`; study orchestration under `experiments/pstnet/`.
The [architecture guide](ARCHITECTURE.md) maps the complete project.

The original source, GPL-3.0 license and exact reference hashes are documented in
[the upstream notice](../third_party/pst900/NOTICE.md).
