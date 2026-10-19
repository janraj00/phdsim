# Historical Survivor-presence workflow

This retained baseline asks whether a complete frame contains Survivor, rather
than assigning a class to every pixel. Its accuracy is not comparable to PSTNet mIoU.

## Data and perception

The initial 400-pair pool is retained. A reviewed version, `pool_cnn_v1`, contains
399 pairs: one frame with a single Survivor pixel was quarantined without relabeling.
The full segmentation benchmark retains that original mask.

Two independent ResNet18 classifiers process RGB and thermal. Images are fitted
to 384 x 216 with ImageNet normalization; thermal is repeated into three channels.
The stem, layers 1-3 and BatchNorm statistics stay frozen; layer 4 and the classifier
are fine-tuned. Each model returns the probability of whole-frame Survivor presence.

The earlier CNN protocol used 191 training, 48 validation and 160 test pairs.
The learned-acquisition protocol uses 121 CNN-training, 48 CNN-validation,
70 meta-training and 160 test pairs, separated by recording family. These two
model populations must not be compared as if they were identical classifiers.

## Fusion and acquisition

Probability fusion methods include independent evidence, arithmetic mean, and
regularized logistic fusion. Learned fusion uses RGB and thermal logits, their
product, and their absolute difference. It runs after acquiring the second image.

Directional Ridge policies predict expected gain from local confidence and optional
local image-quality features. Their regression targets retain harmful acquisitions:

- `brier`: Brier loss before acquisition minus Brier loss after fusion.
- `classification_error`: +1 for correcting an error, -1 for introducing an error,
  and 0 for unchanged correctness at the fixed 0.5 decision threshold.

Nested recording-family validation generates fusion outcomes and selects gain
regularization. Models and policy settings are frozen before replay. The controls
include no acquisition, always acquire, entropy thresholds and seeded random pulls.
Policies see no neighbor image or prediction before requesting its original image.

## Commands

Configuration lives in `configs/presence/`; the launcher is `scripts/presence.ps1`.

```powershell
.\scripts\presence.ps1 -Action inspect
.\scripts\presence.ps1 -Action fetch
.\scripts\presence.ps1 -Action prepare
.\scripts\presence.ps1 -Action cnn -Output runs\presence_cnn_new
.\scripts\presence.ps1 -Action learn -Output runs\presence_learning_new
```

Compare acquisition objectives with the same perception and fusion:

```powershell
.\scripts\presence.ps1 -Action learn `
  -LearningConfig configs\presence\learning_accuracy.json `
  -Output runs\presence_accuracy_new `
  -ReferenceRun runs\pst900_learning
```

The reference guard checks CNN identities, data roles, fusion weights and all
non-objective settings. Existing outputs require a new destination. The older
`scripts/run.ps1` forwards to this launcher, and the earlier flat Python CLI
commands still route to `phdsim presence`.

## Artifacts and limitations

The original image data and CNN bundles live under `D:\Doktorat\Platforma`.
Local results remain in `runs/pst900*`. Configurations, frozen model identities,
per-agent predictions, costs and optional JSONL traces are retained. Physical
network traffic, movement, energy and online policy updates are not simulated.

The old test subset was inspected during development. The objective change was
motivated by earlier results. Treat these comparisons as diagnostics. The original
long-form README and source layout are preserved in the organization snapshot
under `archive/`.
