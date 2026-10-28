# Experiment index

**Current research focus: UrbanIng-V2X LiDAR cooperative detection and selective
acquisition.** The earlier PST900 work is retained as a separate study.

| Study | Dataset and model | Task / metric | Completed work | Detailed status |
|---|---|---|---|---|
| UrbanIng stage 1 | UrbanIng-V2X; authors' frozen CoBEVT | 3D object detection, evaluated with BEV AP/mAP | Two ten-frame CPU smoke windows; full held-out evaluation pending | [UrbanIng experiments](URBANING_EXPERIMENTS.md) |
| PSTNet segmentation | PST900; own PSTNet RGB training | Five-class pixel segmentation; global mIoU | Small RGB pilot; own fusion and acquisition experiments pending | [PSTNet experiments](PSTNET_EXPERIMENTS.md) |
| Historical presence baseline | PST900; separate classifiers and acquisition methods | Whole-frame binary Survivor presence | Earlier diagnostic experiments | [Presence baseline](PRESENCE_BASELINE.md) |

These are separate tasks, models, data splits and evaluation protocols.
PSTNet is a model for the PST900 study, not part of the UrbanIng CoBEVT pipeline.
Segmentation mIoU and detection mAP are not interchangeable.

Each detailed status page distinguishes completed pilot measurements from
published reference results, implemented components and pending experiments.
Run directories and their provenance are listed with the corresponding study.

## Implementation guides

- [UrbanIng CoBEVT stage 1 protocol and commands](URBANING_STAGE1.md)
- [PSTNet reproduction and own training](PSTNET_REPRODUCTION.md)
- [Project context and agreed research direction](CONTEXT.md)
