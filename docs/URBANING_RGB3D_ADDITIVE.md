# Preserve LiDAR proposals and add non-overlapping RGB

Prepared 2026-11-07 after user-reported complementarity job21662623.
The pasted final per-class table sums to165 extra standalone RGB GT appearances
after depth fitting,129 gained after raw-score fusion and417 lost versus LiDAR.
Before depth fitting:162 extra RGB,136 gained,495 lost. These are user-reported
counts from the pasted table, not a locally inspected archive. The table alone
does not identify how many losses are NMS versus greedy GT reassignment.

## Fixed comparison

Use the existing completed21658632 primitive outcome ZIP:400 TRAIN and200
previously inspected development-validation frames. No image/LiDAR inference,
fitting, GT-dependent selection, score/overlap threshold search, crossing3 or
best-variant selection. Both fixed rules are evaluated for BOTH frozen RGB
variants (baseline and depth-adapted). This is an exploratory development
comparison motivated by already observed validation results, not a blind test.

### Additive geometry rule

1. Retain every original LiDAR proposal in its original order, including
   mutually overlapping LiDAR proposals. Do not apply a new LiDAR NMS.
2. Consider RGB proposals in stable descending original confidence order.
3. Reject an RGB proposal if it overlaps ANY original same-class LiDAR box at
   BEV IoU>.2. The threshold is the existing fusion NMS threshold, reused as a
   fixed duplicate control, not selected from these results.
4. Apply that same duplicate rejection among accepted RGB additions only.
   Different classes do not suppress each other.

The function receives only saved predicted boxes/confidences/classes. No GT,
image, LiDAR point cloud or acquisition metadata enters inference-time fusion.

### Two separately labeled score rules

- `additive_raw`: retain all raw source scores. This isolates the new geometry
  rule from score ranking changes.
- `additive_lidar_first`: same retained boxes; use LiDAR evaluation rank
  `.5+.5*s` and RGB rank `.49*s`. This deliberately places every LiDAR proposal
  above every RGB addition. It is a fixed source-priority rule, NOT learned
  calibration or an estimate of correctness. Raw confidence remains in the
  saved primitive arrays; these rank scores must not be interpreted using an
  ordinary shared probability threshold.

Physical retention of LiDAR boxes does not guarantee identical greedy GT
assignments or AP; the original NumPy tie/matching behavior is unchanged.
LiDAR-first intentionally protects ranking. Appending false positives below
all LiDAR predictions may leave VOC AP unchanged even while precision at the
saved proposal operating point drops. Therefore report added boxes and FP,
GT gains/losses and class AP beside mAP, rather than calling non-decreasing AP
alone evidence that RGB adds useful detections.

## Replay and guards

Verify source completion SHA when present, ZIP CRC/duplicate members, source
schema and exact400/200 inventory. Write the declared protocol BEFORE replay.
Require all five original baselines to reproduce ALL per-class AP@.3/.5/.7 and
macro AP in BOTH ordering modes. Assert every original LiDAR box is physically
retained (and raw scores unchanged for the raw control). Trace any remaining
lost GT identity as retained-prediction matching change, not NMS removal.

Re-read the written new outcome arrays and independently reproduce their AP
without calling fusion again. Verify the source ZIP remains unchanged. Keep
TRAIN/validation separate and report per-class, per-sequence and full per-frame
GT traces, raw source arrays, selected union indices and evaluation rank scores.
Counts are GT appearances per frame, not unique tracks or mAP. Keep all source
evaluation GT; do not drop classes where RGB is weak.

## Run

From a fresh additive-fusion checkout:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_rgb3d_additive.sbatch
```

Existing container Python only;4CPU/12GiB with a1h scheduler ceiling, not ETA.
Default source:
`phdsim/runs/urbaning-rgb3d-depth-21658632/urbaning-rgb3d-depth-controlled.zip`.
Default output: `phdsim/runs/urbaning-rgb3d-additive-JOBID`.
Logs: urbaning-rgb-add-JOBID.out/.err in the submitted checkout.

Output urbaning-rgb3d-additive.zip includes source report, fixed protocol,
summary, detailed report and600 new raw outcome NPZs for independent replay.
Use a fresh output directory; no source reports/weights/caches are overwritten.
An hour is only an allocation ceiling; the work is cached geometry and matching.

Six tests cover destructive RGB suppression, unchanged overlapping LiDAR,
empty inputs, same-class versus other-class duplicates, stable RGB ties,
score range/no GT inputs, unchanged sources, FP-induced AP loss versus ranking
protection, greedy assignment changes and end-to-end portable AP/checksum guards.
The new Ares additive experiment has not run; no accuracy improvement is claimed.
