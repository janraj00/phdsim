# RGB / LiDAR complementarity audit

Prepared 2026-11-07 after user-reported completed Ares21658632 (58m57s).
Primary validation200 BEV mAP@.5: LiDAR21.5380%, frozen outdoor RGB3.1569%,
depth-adapted RGB3.2419%, original late fusion16.7683%, adapted late fusion
16.6003%. These are log values; the new native-depth archive has not yet been
read locally. No recovery count for this run is known until this audit runs.

## Question

Does saved RGB detect GT object appearances missed by LiDAR, and what happens
to these and the original LiDAR matches under the actual fixed fusion rule?

Use all400 TRAIN and200 development-validation saved primitive NPZs from
`urbaning-rgb3d-depth-21658632/urbaning-rgb3d-depth-controlled.zip`. No image
encoder, LiDAR backbone, new training, scoring threshold search or acquisition.
No crossing3. The saved detector operating points stay unchanged.

## Definitions

Match separately for LiDAR, RGB and fusion, with the original same-class greedy
confidence order, float32 BEV IoU>=.5 and existing corner-radius filter. Preserve
the original per-frame GT index. Counts are object appearances per frame, not
unique physical objects/tracks, and are not mAP. Duplicate predictions are FP.

- Extra RGB GT: matched by RGB alone and missed by LiDAR alone.
- Both: matched separately by both detectors.
- Neither: matched by neither detector.
- Fusion gained/lost: GT identities gained/lost after actual union/NMS relative
  to LiDAR alone. Greedy reassignment means gains need not be identical to the
  extra standalone RGB set.
- Extra RGB retained/lost: which extra RGB identities remain matched after fusion.

For every lost GT, follow its originally matched LiDAR prediction. If NMS drops
it, identify the actual first earlier retained same-class blocker in stable
score order and record its source, confidence, box center and IoU with both the
LiDAR box and GT. Distinguish RGB suppression, LiDAR suppression, and a retained
LiDAR prediction whose GT assignment changes. A source attribution is a trace
of this fixed algorithm, not a claim that suppression alone explains all AP.

Store each extra RGB and gained fusion GT identity with scores/IoU/coordinates.
Retain every per-frame trace, class totals and sequence totals, separately for
baseline and adapted RGB and separately for TRAIN and validation.

## Guards and interpretation

Check ZIP CRC/duplicate member names, the completed source ZIP checksum when
available, schema and exact400/200 inventory. Reconstruct all five variants.
ALL per-class AP@.3/.5/.7 and macro AP must exactly reproduce the source report
in BOTH ordering modes before accepting any count. Record source/code hashes
and NumPy version; verify the source archive remains unchanged. A fresh output
directory prevents overwriting previous results.

Accounting identities include fusionTP=LiDAR_TP+gained-lost and all lost GTs
classified into exactly one trace reason. The union of separately matched GT
sets is diagnostic coverage, not a deployable GT-based selector or fusion.
Low-score extra detections need not improve AP. Development-validation is one
previously inspected recording; no statistical generalization claim follows.

## Run

Submit from the complementarity checkout:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_rgb3d_complementarity.sbatch
```

Reuse the existing container Python (NumPy1.26.4). No compiled RGB runtime is
needed. Default input is the completed21658632 ZIP. Output is
`phdsim/runs/urbaning-rgb3d-complementarity-JOBID`, containing report.json,
summary.md, a source report copy and urbaning-rgb3d-complementarity.zip.
Logs: urbaning-rgb-audit-JOBID.out/.err in the submitted checkout.4CPU/12GiB,
30-minute scheduler ceiling, not ETA. Only cached geometry/matching is computed.

Five tests cover complementary detections plus destructive suppression, stable
ties, empty RGB, radius/class filters, threshold precision, retained-prediction
GT reassignment and a portable archive workflow with source-AP/checksum failure
guards. Identity matching also reproduces the existing evaluator. No empirical
21658632 complementarity result is claimed before execution.

An additional real-data regression check on the earlier general-checkpoint
TRAIN8 archive21653482 exactly reproduces both source AP orders and its known
five gained/four lost GT appearances, all four losses traced to RGB NMS.
This verifies the audit implementation on historical data; it is not evidence
for the new outdoor/depth600-frame run or a held-out performance result.
