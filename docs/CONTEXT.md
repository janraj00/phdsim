# PHDSIM research handoff

Updated: **2026-11-09**. This document summarizes the latest decisions in the
project conversation. Earlier explanations in the
[conversation archive](CHAT_HISTORY_2026-10-19.md) include superseded assumptions.

## Thermal pilot: local projection audit (2026-11-08)

User chose thermal as the next modality after the corrected RGB-head job
21687491 completed. Its validation200 mAP@.5 was LiDAR21.5380%, RGB head1.5916%,
initialized additive raw20.1284%, fine-tuned additive raw21.2219%, initialized
LiDAR-first21.8953%, and fine-tuned LiDAR-first21.6007%. RGB head fitting is not
a reliable path to a useful standalone detector; raw additive improves versus
its initializer but remains below LiDAR, and LiDAR-first is effectively tied
with LiDAR. This is development validation, not an independent test.

A quick read-only audit of the locally available sequence
`20241126_0017_crossing1_00` projected timestamped 3D annotations into all six
rectified infrastructure thermal cameras. It found 1,200 associated thermal
views (200 anchors x 6 cameras), annotations at all 200 anchors, and camera
capture offsets from +8 to +41 ms (median +20 ms). With the RGB-head pilot's
12-pixel minimum and >=50% in-image rule, positive projected box support was
`[21395, 959, 306, 2591]` for Vehicle/Heavy_Vehicle/2Wheeler/Pedestrian. These
are per-camera object appearances, with the same object counted in multiple
views; they are not unique objects. Near-plane straddles flagged for ignore
were `[3365, 8, 33, 786]` in class order. No thermal detector was trained.

This audit covers only the locally available crossing1 TRAIN recording. It
does not establish proposal recall, detection accuracy, or transfer to crossing2.
Read-only SSH lookup from the desktop could not resolve the Ares host, so remote
data availability is not confirmed and no Ares job was submitted. Prepared a
cheap frozen-RPN gate at `scripts/urbaning_thermal_rpn_gate.py` and
`scripts/slurm/urbaning_thermal_rpn_gate.sbatch`: twelve uniform anchors from
the confirmed crossing1 TRAIN sequence, all associated thermal cameras (up to72
views), with frozen official outdoor RPN and projected box recall. It requires
at least five sampled positive GT boxes per class, then macro recall >=.25 for
IoU.3 and >=.10 for IoU.5. It does no fitting and does not read validation. It
auto-detects a data root containing the crossing1 extraction, or accepts
`URBANING_DATA_ROOT`. Uses four CPUs/12GiB, one-hour
scheduler ceiling. On pass, continue with a one-epoch head pilot; on poor recall,
stop before training. Keep native capture offsets, per-object near-plane ignores,
report class AP and GT/FP counts, and make no held-out claim. See
[thermal plan](URBANING_THERMAL_PLAN.md).

First gate submission21694006 failed after10s before data access because its
entry point did not add this checkout's `src/` to `sys.path`; the runtime found
an older installed `phdsim` package without the RGB fine-tuning reader. Fixed
the entry point to prioritize its checkout source and corrected the Slurm
progress line to describe twelve anchors from the single confirmed crossing1
sequence. Retry with the follow-up commit and a fresh output/job ID. No thermal
data/model processing occurred in21694006.

Retry21694226 found the Ares data root and read the immutable source records,
then failed after3m06s at `ModuleNotFoundError: detectron2`. The entrypoint had
not activated the verified private CPU runtime used by the RGB job. Fixed it to
call the existing read-only `reuse()` bootstrap before model import, passing
runtime21649159 from the Slurm script. No thermal image inference occurred.
Retry with another fresh commit/worktree/output; no installs or runtime writes.

Retry21694349 activated runtime21649159 and found the data root, then failed
before thermal image inference on a missing local NumPy import in the
vehicle/LiDAR transform helper. Added the import. Runtime activation is now
confirmed in the job log; retry with a new worktree and output.

## Thermal frozen-RPN results (2026-11-09)

Gate21694685 completed its diagnostic and deliberately returned exit2 for
`STOP` (not a code crash). On sampled crossing1 thermal views, frozen
RGB-pretrained RPN macro recall was14.17% at IoU.3,4.48% at.5,0.78% at.7,
below gates25%/10%. Per-class recall at IoU.5: Vehicle4.13% (25/605),
Heavy_Vehicle12.20% (5/41),2Wheeler0% (0/5; small sample), Pedestrian1.59%
(1/63). This shows the frozen RGB proposal generator does not transfer well to
thermal. Do not train ROI heads while keeping the RPN frozen: they cannot
recover objects absent from proposals. It does not show thermal itself is
useless. The same script now performs a read-only proposal-budget sweep on
these same sampled views: configured default, post-NMS 2,000 and 4,000, with
pre-NMS increased as needed. It changes no weights, does not read validation,
and writes `rpn-budget-sweep.json`. If recall stays low even at 4,000, a separate
trainable-RPN pilot needs recording-level thermal validation and a native RPN
loss/gradient gate.

Budget sweep21694751 confirmed more test proposals recover additional thermal
GT: macro recall rose from14.17/4.48/0.78% at IoU.3/.5/.7 configured default
to22.05/9.47/2.89% with post-NMS4000. It remains just below the original stop
thresholds. At post4000, IoU.5 per-class recall is Vehicle7.27% (44/605),
Heavy_Vehicle19.51% (8/41), Pedestrian11.11% (7/63), and 2Wheeler0/5. This is
still weak localization; no model was fitted. Recommended next: expand the
uniform TRAIN-only sample at fixed4000 proposals to better measure class
coverage, and verify a separate thermal recording is available for evaluation.
Prepared the expanded gate on48 uniform TRAIN anchors with only configured and
post-NMS4000 settings; it also records which extracted sequences are present.
If proposal recall remains low or no separate thermal eval recording exists,
pause rather than train heads/RPN without a sound pilot.

## RGB geometry filter invalidated fine-tuning run (2026-11-08)

User queried final run21685167 `train-inventory.json`: 2,400 Car1 camera views,
2,341 skipped by near-plane geometry (97.5%), six had zero positive labels.
Positive support was `[609,44,4,83]` for Vehicle/Heavy_Vehicle/2Wheeler/Pedestrian.
The near-plane code dropped an entire camera view when ANY ground-truth cuboid
crossed the camera plane and intersected the image. Only59 views trained per
epoch; results are not a meaningful comparison and must not support a claim
that RGB head fine-tuning failed. The previous four-class initialization also
reduced RGB mAP before fitting, so this result contains TWO confounds.

The focused correction clips that cuboid to the camera plane, marks its image
region ignored, and retains other valid objects in the same camera. Inventory
now records per-view ignored near-plane boxes and positive examples; camera
frames are not discarded for this reason. A corrected run must rebuild from
the original outdoor/depth checkpoint on fresh output, pass the native gate,
and confirm zero near-plane-skipped views plus substantially broader class
support before accuracy results are interpreted. Do not reuse old checkpoints.

Corrected job21687441 passed the revised gate and began epoch1, then stopped
after300 updates because an ignore-only camera had every RPN proposal covered
by projected near-plane boxes. The empty-target sampler correctly refused to
mislabel these proposals as background, but aborting all training was overly
strict. The follow-up skips that camera's optimizer update and logs the
key/camera/reason in `skipped-updates.jsonl`. Other frames continue; classifier
labels are not weakened. Retry with a fresh worktree/output. This is a second
issue discovered during the corrected run; no useful four-epoch model exists.

## RGB native gate naming failure fixed (2026-11-08)

User reported Ares21668971 FAILED after9m59s during the disposable native gate,
before the four training epochs. The gate incorrectly required bare loss_cls;
pinned Cube R-CNN returns BoxHead/loss_cls and Cube/loss_z. Toy tests had used
the wrong classifier name too. Require the exact upstream names before any
optimizer update, exercise official names throughout synthetic tests, and log
gate progress plus actual returned loss values. Missing names produce an error
listing all returned keys and a failed-gate diagnostic JSON for positive checks.

Eight focused tests and syntax checks pass, including a synthetic400/200 pipeline
with official loss names and rejection of missing depth loss before mutation.
Native full startup/empty-image/save-load gate remains to be completed on Ares;
do not claim training success or change accuracy settings to bypass the guard.
Preserve failed21668971 output; retry with a new checkout/output/job ID, reusing
the same existing source runtime/weights/cache. No actual RGB fit result yet.

## Additive result received; broader RGB head fitting prepared (2026-11-08)

User pasted DONE from additive21667369. Validation200: LiDAR21.5380% mAP@.5;
baseline/depth additive raw18.5275/18.1581%, LiDAR-first22.0671/21.9834%.
Both retain all old GT matches;110/102 extra GT appearances. Added21943/21926
RGB boxes; FP increases7027 ->27986/28060. Priority ranking protects AP but
does not remove FP. No good-precision or held-out improvement claim. Supplied
ZIP hash d865ee5984c3d9f4189c571ac9a5e2677273225d0bac3ba19c0b4dbe1868c6f0,
33781801bytes; archive not independently downloaded/read in this session.

User authorized further RGB adaptation and asked to consider thermal. Prepared
native four-coarse-class ROI-head training: frozen outdoor backbone/FPN/RPN,
train2D feature/classifier/box and full3D shared/readout/uncertainty heads.
Fixed mean initialization from existing fine categories; evaluate the untrained
four-class initializer as an explicit control. Native foreground/background and
cuboid losses, projected3D GT as weak2D supervision with ignores and near-plane
skips. Four fixed TRAIN400 epochs, SGD1e-4, seed0; final frozen before loading
development-validation200. No crossing3 or validation parameter selection.

Native positive/empty-label gradient and save/load checks precede actual fitting;
gate changes are discarded. Seven local tests use PyTorch with a toy detector,
including synthetic400/200 pipeline/AP replay; compiled native Cube losses are
NOT yet verified. Native Ares training remains pending. Reuse existing runtime,
outdoor model and source depth ZIP read-only;8CPU/24GiB/24h scheduler ceiling,
not ETA; substantially more CPU work than depth-only fitting. Fresh output;
epoch checkpoints are saved but automatic resume is not implemented.
See [RGB head fine-tuning](URBANING_RGB3D_FINETUNE.md).

Thermal is infrastructure evidence, not a pixel-aligned vehicle-RGB channel.
Proposed follow-up: thermal2D detections with infrastructure-LiDAR localization,
controlled against the SAME infrastructure LiDAR without thermal. Distinguish
hybrid from thermal-only3D; retain native times/calibration and account for peer
payloads later. Thermal code/training is not implemented/submitted here. See
[thermal design](URBANING_THERMAL_PLAN.md).

## LiDAR-preserving additive RGB fusion prepared (2026-11-07)

User supplied completed complementarity job21662623 final per-class tables.
For depth-adapted RGB these sum to165 extra standalone RGB GT appearances,
129 gained after original fusion and417 lost versus LiDAR; baseline RGB
162/136/495. These are pasted log counts, not a locally read archive. Do not
attribute all losses to RGB NMS without the detailed trace. Counts are GT
appearances, not unique tracks or mAP.

User authorized a LiDAR-preserving fusion test. Implemented a GT-free additive
rule keeping ALL original LiDAR boxes, including overlapping LiDAR proposals.
Reject same-class RGB overlap at the unchanged existing .2 BEV NMS threshold;
suppress duplicates only among RGB additions. Run both frozen RGB variants
with two separately labeled score rules: unchanged raw confidence, and explicit
LiDAR-first priority ranks (.5+.5*s for LiDAR, .49*s for RGB). No fitting or
threshold search, no selection of the best variant. This is exploratory
development comparison after observed validation results, not a blind test.

Physical box retention does not guarantee unchanged greedy GT matches.
LiDAR-first deliberately protects ranking; false positives appended after
LiDAR may leave VOC AP unchanged. Report raw FP/TP and added boxes beside
class mAP and GT gains/losses; never present rank scores as calibrated
probabilities or non-decreasing AP alone as useful multimodal improvement.

Use completed21658632 primitive ZIP, TRAIN400 / validation200 separately.
All5 original baselines must exactly reproduce class AP@.3/.5/.7 and macro
in BOTH orders. New written outcome arrays are independently re-read for AP
parity; source hashes/CRC/inventory and LiDAR preservation checked. Source
models/caches remain read-only; no CNN, LiDAR, training or crossing3 calls.

Six focused tests and Python/Bash syntax checks pass, including destructive
suppression, empty/same-class/tied inputs, unchanged overlapping LiDAR,
priority versus FP-induced AP loss, greedy reassignment and portable replay/
checksum/AP guards. New Ares additive result remains pending.
Entry point scripts/slurm/urbaning_rgb3d_additive.sbatch uses4CPU/12GiB with
1h ceiling (not ETA). See [additive fusion](URBANING_RGB3D_ADDITIVE.md).

## Completed depth run; cached RGB complementarity audit prepared (2026-11-07)

User-reported Ares21658632 COMPLETED in58m57s. TRAIN400 / development-validation200
BEV mAP@.5: LiDAR24.2799/21.5380%, original outdoor RGB3.2687/3.1569%,
depth-adapted RGB4.5177/3.2419%, original late fusion19.8647/16.7683%,
adapted fusion21.0608/16.6003%. Depth-only fitting produced little validation
RGB AP gain and fusion remained below LiDAR. The new ZIP has not been read
locally; no21658632 object-recovery count is known from these log values.

User asked to count RGB detections missed by LiDAR and LiDAR detections lost
after fusion. Implemented a cached-outcome audit for the completed600 primitive
frames, with separate TRAIN/validation, class and sequence totals. Preserve GT
identity under the original greedy class/float32-IoU/radius rules; report
standalone RGB-only matches, retained extras, fusion gains/losses and FP.
Trace lost LiDAR TP predictions to the actual earlier retained RGB/LiDAR NMS
blocker or to retained-prediction GT reassignment. These are per-frame GT
appearances, not unique tracks, mAP or a deployable GT-based fusion policy.

The audit must exactly reproduce all5 source class AP/mAP at.3/.5/.7 in BOTH
orders, check source completion checksum/CRC/inventory and keep the source
unchanged. No detector/fitting/threshold tuning/crossing3. Five focused tests
pass, including destructive RGB suppression, stable ties, empty RGB, class/
radius/threshold behavior, reassignment and corrupt/checksum/AP guards.
The same tool also reproduced BOTH source AP orders on the earlier general
TRAIN8 archive21653482 and recovered its known5 gained/4 lost GT appearances,
all4 losses due to RGB NMS. This historical check is NOT21658632 evidence.

Entry point scripts/slurm/urbaning_rgb3d_complementarity.sbatch uses existing
container Python only,4CPU/12GiB/30min scheduler ceiling. Default source is
21658632 ZIP. Output report/summary/ZIP includes full object-identity traces.
See [complementarity audit](URBANING_RGB3D_COMPLEMENTARITY.md). Native600-frame
complementarity results remain pending until the user submits this audit.

## Outdoor RGB result received; native depth-layer adaptation prepared (2026-11-07)

User-reported Ares21655505 completed in2m50s: same TRAIN8 official outdoor
RGB6.935736%, late fusion27.024288%, original LiDAR/NMS control29.149123%.
General checkpoint values were4.097309% and29.228132%, respectively. Outdoor
improves standalone RGB on this tiny sample but worsens raw-score late fusion.
Its ZIP has NOT been read locally yet; no per-class outdoor claim is verified.

Implemented the next controlled CPU experiment: freeze the outdoor Cube R-CNN
except its EXISTING1024-to-11 native depth linear readout. Fixed weighted ridge
around pretrained weights uses projected-GT-associated RGB features from400
TRAIN frames only; fold normalization back into the original layer. Categories
with fewer than32 TRAIN positives keep original parameters. Freeze/checksum
before loading200 development-validation records. No validation selection,
crossing3, new LiDAR inference, learned fusion or RGB score changes. This is
partial supervised native RGB adaptation, not a new BEV adapter or full-detector
fine-tuning. Primary metric stays globally sorted BEV mAP@.5; both AP orders,
class AP, TRAIN/validation and matched depth MAE are reported separately.

Reuse the completed private runtime21649159 and outdoor model/pilot21655505
read-only; no installation or compilation. An8-TRAIN native gate precedes full
feature extraction: source AP/camera/GT bindings, exact captured native depth,
and real detector versus modified-head replay. Verify the actual fitted state
against native forward before validation too. Verified camera caches support
resume; source hashes and frozen model must remain unchanged. Download excludes
large feature tensors but includes all600 primitive AP outcome records.

Checks:12 focused/regression tests pass, including a synthetic400/200 end-to-end
pipeline proving fit-before-validation and corruption rejection. Real official
outdoor CPU forward passes captured-feature/virtual-depth checks and replay of
a nontrivial fitted ORIGINAL layer (synthetic targets only). Syntax checks pass.
The controlled UrbanIng depth experiment has NOT run; no accuracy gain is
claimed. Entry point: scripts/slurm/urbaning_rgb3d_depth.sbatch,8CPU/24GiB,
4h scheduler ceiling, not ETA. See [native depth protocol](URBANING_RGB3D_DEPTH.md).

## RGB3D baseline reviewed; paired outdoor checkpoint check prepared (2026-11-07)

User asked to improve RGB itself after the weak zero-shot result. Completed
Ares21653482 ZIP has been locally CRC/hash checked and all4 variants' class AP
at.3/.5/.7 independently replayed in both orders. All48 raw-camera conversions,
six-camera NMS and late fusion reproduce stored arrays exactly. Primary mAP
original LiDAR/NMS control29.1491%, RGB4.0973%, fusion29.2281%. Fusion gains5
GT appearances but loses4 old matches through suppression of original LiDAR
boxes. Representative RGB/BEV images reviewed.48 calibration determinants=-1
within~1.6e-15. This supersedes the earlier pending-native notes below.

Offline GT-dependent geometry-factor controls (194 projected-image-matched
camera-object observations, all original GT retained) indicate depth/position
is the main bottleneck: replacing only optical depth gives15.2056% versus
4.0973% unchanged; dimensions4.6712%, yaw4.0973%, BEV center19.7628%.
These are error-isolation diagnostics, NEVER deployable/trained gains or
guaranteed achievable performance. No new fitting has taken place.

Prepared paired evaluation of the authors' official outdoor-only DLA34 weights
against the frozen general Omni3D reference21653482. New config/metadata/model
hashes checked; private runtime21649159 reused read-only without installation.
Require identical8 keys, GT/LiDAR arrays and48 image/calibration/time bindings;
replay all old AP before inference. Same class mapping, thresholds and fusion
rule; no validation/crossing3, fitting or score calibration. Eight focused tests,
real official outdoor CPU forward and empty-image path passed. Native outdoor
UrbanIng results remain pending. See [outdoor comparison](URBANING_RGB3D_OUTDOOR.md).

Further native-depth-head adaptation on400 TRAIN/200 development-validation is
a proposed following step, not implemented or run by this small checkpoint test.

## Independent RGB3D late-fusion pilot prepared (2026-11-07)

Ares21649159 verified the private Cube R-CNN CPU model, then failed after the
first RGB prediction at the extrinsic determinant guard. Code review of pinned
upstream d5766e7 shows corrected E=cTg*gTl*R3*R1, with an explicit handedness
reflection. Initial det+1-only validation was wrong for this basis. Corrected
to orthogonal det+/-1 without changing any calibration, scaling, thresholds or
class mapping; reject scale/shear and export all48 calibration diagnostics
before model creation. Native matrix values remain to be read on retry.
Seven focused tests plus a49-official-cuboid reflected-center roundtrip pass.
Added read-only completed-runtime reuse for21649159: preserve failed output,
create new job-ID output, no compilation/install/download or source runtime
writes. Plot caches stay in new output, Python bytecode writes disabled on
reuse. Native corrected pilot has not run.

User questioned the feature adapter and selected independent RGB detection plus
late fusion. Prepared a separate frozen official Cube R-CNN DLA34/Omni3D CPU
pilot:8 fixed TRAIN frames, six Car1 cameras each; no fitting, validation,
crossing3, new LiDAR inference or acquisition. Use actual K and reviewed camera
extrinsics, export raw optical cuboids, derive explicitly upright Car1 boxes
from predicted center/dimensions/length-axis yaw. Class mapping is documented;
retain all GT even for categories with no exact RGB counterpart. Union detections
and fixed classwise BEV NMS .2, with original LiDAR and LiDAR-NMS-only controls.
Raw scores are not cross-model calibrated. Export48 projection images/eight BEV
comparisons/raw predictions and class AP in both original ordering modes.

Private CPU runtime builds pinned Detectron2/PyTorch3D and adds torchvision,
without mutating the shared venv; official model/config/category hashes checked.
Eight TRAIN frames are a technical diagnostic, not a held-out modality ranking.
Four focused tests passed, including synthetic48-camera/eight-frame export.
Actual official-weight Cube R-CNN CPU inference on an upstream demo image
returned49 finite3D detections; that is a startup check, not native UrbanIng
accuracy or an Ares ETA. Native Ares execution has not run. See
[RGB3D late-fusion pilot](URBANING_RGB3D_LATE.md).

The completed frozen adapter TRAIN-eval ZIP has now been read locally and CRC
checked. Three-seed means: original/LiDAR-adapter/RGB-adapter TRAIN400
24.3129/31.5907/34.0658%; validation200 21.6500/18.0014/17.6987%.
RGB-minus-LiDAR validation deltas -.6918/-.7340/+.5175pp, not negative in all
seeds. Most LiDAR-adapter macro loss is Heavy_Vehicle; RGB recovers some of it
but worsens2Wheeler on average. TRAIN gains occur on both original recordings;
this supports a generalization gap, not a unique causal explanation. Historical
partial progress notes below are superseded by this completed result.

## Frozen final-model TRAIN/validation diagnosis prepared (2026-11-07)

User supplied validation200 results for completed seeds0/1 of controlled run:
original LiDAR21.6500% both; LiDAR adapter18.1889%/19.4775%; aligned RGB
adapter17.4971%/18.7434%; shuffled-training control18.7901%/18.3470%; shuffled-
evaluation RGB15.1754%/16.4852%. RGB-minus-LiDAR-adapter was reported as
-0.6918/-0.7340pp. This is a negative development result in both supplied seeds;
the third seed and final ZIP have not been read here. Do not claim validation
gain or uniquely diagnose overfitting from these numbers alone.

User authorized evaluation of the same fixed final models on TRAIN400, beside
existing validation200. Prepared separate `urbaning_cobevt_rgb_train_eval` and
submitter. No optimizer/backward, fitting, target regeneration, normalization,
checkpoint selection, CNN/LiDAR backbone inference, source writes or crossing3.
Require completed canonical source ZIP; if its collector21599633 is still active,
automatically wait via afterok. Preserve original controlled checkout/output.

Bind source protocol/code/normalizers/models/receipts to archive checksums, verify
existing features and complete final32-epoch histories. Compute TRAIN original
LiDAR once; evaluate three adapters aligned, plus a separately labeled shuffled-
training-control as-trained input diagnostic, for every seed (5200 frames total).
Reuse the already independently replayed original validation reports without
rerunning validation inference/matching. Stream cached features, freeze all
parameters and check original source hashes afterward. New output:
`phdsim/runs/urbaning-cobevt-rgb-train-eval-001`, own logs/ and resumable per-frame
prediction receipts. Independent TRAIN AP replay before final ZIP.

Report changes vs original LiDAR WITHIN each split, pooled and per-original-
recording TRAIN AP, class/seed AP, paired RGB-minus-LiDAR changes, frozen TRAIN
anchor losses and original optimization curves. Distinguish shifted-input
control diagnostics from aligned TRAIN/validation comparison. Six focused new
tests plus28 earlier checks pass; no native diagnostic run submitted here.
See [frozen TRAIN evaluation](URBANING_COBEVT_RGB_TRAIN_EVAL.md).

## Controlled Car1 adapter development run, user-reported progress (2026-11-07)

Submitted original chain21599628 inventory,21599629 startup gate,21599630 feature
array,21599631 normalization,21599632 seed array,21599633 collector. User logs
showed all600 feature frames and normalization completed successfully; native
startup gate passed. Seeds0/1 completed TRAIN and validation; their supplied
numbers are above. Current seed2/collector status is not directly known here.

### Original prepared protocol (2026-11-06)

User requested a strong controlled test after successful TRAIN8. Prepared
`submit_urbaning_cobevt_rgb_controlled.sh`:400 TRAIN (existing0001 crossing2 and
0017 crossing1),200 separate development-validation (0004 crossing2), seeds0/1/2,
32 fixed final-only epochs. Primary comparison is aligned RGB adapter minus
same-capacity/train-order/initialization LiDAR adapter. Include original LiDAR,
a far-shuffled TRAIN-RGB control evaluated on ALIGNED validation RGB, and a
separate shuffled-evaluation diagnostic using the aligned-trained adapter.
No validation search, F1 switch, crossing3, RGB-only or acquisition experiment.

One submitter creates inventory -> disposable two-TRAIN-frame native startup
gate ->3 sequence cache tasks (%2) ->TRAIN-only normalizers ->3 seed workers
(%2) ->independent raw-prediction AP replay/report. Reuse8 reviewed native BEVs,
extract remaining592 once, keep original frozen heads/decoder/GT, fit original
anchor loss. Stream at most2 decoded frames, checkpoint each100 updates and
epoch; do not retain400 contexts in RAM. All3 models in a seed are frozen before
that fitting worker loads validation. Engineering source/parity checks may read
validation GT but never fit/select by it. Output has own logs/, final9 models,
per-seed/class AP/both orders, paired deltas, raw predictions/GT and receipts.

Nine controlled tests plus13 trainer/6 preflight tests pass (28). Native-size
channels-last CPU updates with actual pinned PointPillarLoss also checked.
Native user-reported progress and partial results are above. Existing
private RGB bootstrap retains3 child-process checks and actual encoder startup
coverage. User runs the command on Ares. See
[controlled adapter protocol](URBANING_COBEVT_RGB_CONTROLLED.md).

This validation is one previously inspected recording, not a blind test; the
official frozen checkpoint may have seen development clips. Seed SD is
optimization variability, not independent-recording uncertainty. All primary
comparisons use this experiment's shared reloaded-feature baseline: per-key
native voxel sampling can differ from historical full-run order. About30GB
new cache;8CPU/24GiB per worker;115200 total updates across9 fixed32-epoch
models. Scheduler ceilings are not ETAs; startup gate prevents expensive work
after numerical/runtime failure. Preserve previous artifacts/worktrees.

## Frozen-CoBEVT TRAIN8 adapter completed, user-reported (2026-11-06)

User posted DONE from Ares21599501, output train8-002: same8 TRAIN fit/evaluation,
original LiDAR30.7838%, LiDAR adapter29.0995%, aligned RGB adapter38.0268%,
frozen RGB adapter with shuffled inputs22.8586% BEV mAP@.5. RGB-minus-trained-
LiDAR is+8.9273pp on TRAIN only; not validation/generalization evidence.
Archive has not been independently reviewed in this session. Frozen heads,
zero validation/test and peer requests remain the declared TRAIN8 protocol.

Ares21599373 FAILED before any optimization at the original absolute-only
1e-6 native logit guard: maximum6.67572e-6 discrepancy, 32830/819200 elements.
Locally reproduced same-value native-size CPU convolution differences after
channels-last/contiguous layout changes and NPZ round trip. This is a plausible
cause, not an independently verified explanation for the Ares caches. Corrected
guard preserves all input/model hashes, requires float32 allclose at1e-5/1e-5,
AND identical native decoded counts/classes/order, coordinates within1mm,
scores within5e-6, exact GT matching and exact AP in BOTH ordering modes.
Saves native-parity.json even on failure. Ares21599465 passed ALL8 native
logit/decode/GT matching and both-AP checks, then stopped before optimization:
the entrypoint hash-seed re-exec had discarded the bootstrapped private
torchvision path. Bootstrap now restarts BEFORE imports; verifies the private
module location and prints versions/path/hash seed. Three child-process tests
reproduce the old failure and check corrected startup across unset/nonzero/zero
seeds. Actual local pinned torch/torchvision + SpatialEncoder/weights in a child
process produced6x48x24x40 RGB maps. Corrected launch21599501 subsequently
completed as reported above. Preserve train8-001/train8-002; controlled test
uses a fresh urbaning-cobevt-rgb-controlled-001 output.
Thirteen trainer tests plus6 earlier adapter checks cover the corrected gate.

User authorized preparation of actual adapter training after native preflight.
Implemented `urbaning_cobevt_rgb_train.sbatch`: reuse all8 verified preflight
BEV caches, reload original frozen32/56 output heads only, no LiDAR backbone/
transformer inference. Frozen ImageNet MobileNet stride16/48-channel RGB maps,
no random compression/PCA, calibrated4-height pull onto original100x256 metric
grid. Fit TRAIN-only normalization; missing views remain zero.

Compare original LiDAR with two same-capacity zero-start residual adapters:
LiDAR-only context and LiDAR+RGB, identical initialization/order/schedule.
Fixed64epochs x8 frames each, AdamW.001, clip1, raw-residual penalty.0001;
corrections bounded to one train channel standard deviation. Use actual upstream
anchor target generator/detection loss and unchanged original decoder. Final
four-class BEV mAP@.5/global sort remains primary; class support and missing
class macro=N/A explicit, no F1 replacement. Export raw predictions/GT, losses,
models and plots; fixed within-recording RGB-shuffle diagnostic, no refitting.

This is fitting/evaluation on the SAME8 TRAIN frames, no validation/test or
crossing3, and not an RGB-only detector. User-reported TRAIN result is above.
Eight trainer checks plus6 earlier adapter checks passed; actual pinned upstream
loss at native tensor size supports CPU backward/updates with frozen heads
(~.29s/step locally on4threads, not an Ares ETA). Source/API review and471
existing GT corner/center geometry checks also passed. Native TRAIN8 completed;
full-development fitting/validation remains pending.

Worker8CPU/24GiB/2h upper limit; private torchvision target, existing weights,
epoch checkpoints/resume and output lock. Output defaults to
`phdsim/runs/urbaning-cobevt-rgb-adapter-train8-002` (corrected parity guard).
See [TRAIN8 adapter protocol](URBANING_COBEVT_RGB_TRAIN.md).
Jobs21599373/21599465 stopped before optimization;21599501 completed TRAIN8.

## Native CoBEVT RGB preflight completed and reviewed (2026-11-06)

Ares job21597293 completed9m13s, exit0. Supplied ZIP SHA256
`8608d07b6862e3288718b0e4469ccb1e983439973c5a96e845cb2263048b9429`,
6,121,251bytes; CRC passed. Exactly8 unique TRAIN keys,4 per existing recording,
48 bound camera entries, zero validation frames and expected official model
identity. Each row reports BEV[1,256,100,256] and exactly zero cls/reg head-replay
error. Raw BEV/logit NPZs stay on Ares, so local review checks report consistency,
not an independent tensor replay. Full scheduler553s, internal loop355.42s and
sum of per-frame timers169.31s cover different portions; do not conflate them.

Reviewed all8 six-camera mosaics, including detailed first-frame views at both
sites. GT boxes visibly align with selected cars/pedestrian and point projections
are plausible; no obvious gross axis reversal/rotation was seen. This is visual
QA, not calibrated reprojection-error measurement, depth/occlusion validation or
an exhaustive per-object check. Native Car1 camera offsets in this sample span
-1..+44ms. Dark crossing1 and daylight crossing2 appearances are both present.

The feature/head boundary now has a completed native check. RGB image-to-BEV
encoder, adapter optimization and RGB accuracy evaluation remain unimplemented.
Next: align RGB features to the original metric BEV grid, freeze CoBEVT, run a
tiny native TRAIN memorization check plus LiDAR-only adapter control before
expanding. No new job submitted and no fusion gain claimed.
See [RGB preflight review](URBANING_COBEVT_RGB_ADAPTER.md).

## CoBEVT RGB adapter scaffold and native preflight ready (2026-11-06)

Prepared `urbaning_cobevt_rgb_preflight.sbatch`:8CPU/24GiB/1h upper limit,
8 fixed TRAIN frames only, official frozen Car1 CoBEVT forward, final BEV
capture and exact replay through original cls/reg heads. Exports native
six-camera point/GT projection mosaics, payload hashes, feature shapes/timing.
No training, RGB accuracy result, new downloads or crossing3. Existing
validation provenance headers are checked, not validation images/predictions.

Residual RGB adapter starts at exactly zero and preserves LiDAR features.
Its metric-aligned RGB BEV encoder and detection-loss training remain future
work. First inspect native geometry; then a tiny TRAIN memorization check
before larger development training. RGB-only needs separate adaptation.
Six focused checks including complete synthetic8-frame export passed; native
Ares execution has not run. See [RGB adaptation plan](URBANING_COBEVT_RGB_ADAPTER.md).

A supervisor brief separately summarizes existing1400-frame LiDAR acquisition:
ALWAYS33.7102%/2033; predeclared geometry/top10 cost.5 32.6966%/1448
(28.78% fewer,1.0136pp loss); post-hoc cost0 33.6741%/1813
(10.82% fewer,.0361pp loss). Equal1448 random31.0770%;
equal1813 random32.7412%, strong Infra-priority random33.1509%.
Do not mix these with the failed small standalone RGB/BEV prototype.

## CPU standalone BEV run completed and audited (2026-11-06)

Ares job21594614 produced a completed export: ZIP SHA256
`698dd3e9619d10daf2c6c426650cda2eac51143604e888742bce2913d8c28152`,
11,205,878bytes. Archive CRC and three recorded source hashes checked. Audit
replayed all600 validation prediction files:200 per modality, identical frame
keys/GT, all class AP and macro AP at.3/.5/.7 in both ordering modes reproduced
exactly with NumPy1.26.4. CoBEVT raw predictions are not in this ZIP, so its
reference AP is carried from the report rather than independently replayed here.

Primary validation200 BEV mAP@.5: RGB0.5490%, LiDAR2.7615%, fusion1.5882%;
separately trained CoBEVT reference21.5380%. Reported train40 diagnostic:
RGB2.8140%, LiDAR16.8878%, fusion16.1355%. Training predictions/features are
not exported, so train AP and native feature alignment were not independently
verified. Train40 and validation200 are different samples, not an epoch curve.

Offline GT target/decode checks on the same200 validation frames: original
top40/NMS.2 gives88.9273% mAP; relaxing cap to500 and NMS to1 gives98.0422%.
These are GT-assisted representation diagnostics, NEVER detector results or
new tuned validation methods. Original vehicle recall63.5406%; relaxed100%.
Pedestrian recall92.1687% in both, consistent with169 same-class cell collisions;
all14937 GT retained. Decoder limits matter but do not explain model AP near0–3%.

LiDAR validation TP@IoU.5: Vehicle1972/12241, Heavy0/249,2Wheeler13/289,
Pedestrian22/2158. Many false predictions and center errors remain; a simple
global box-size correction cannot be inferred as the fix. Lower train loss
and a train/validation gap do not establish the cause. Input projection,
feature informativeness, optimization and generalization remain open.

No new training job submitted. Next diagnostic should use a tiny fixed set of
native TRAIN frames, check point/image/GT alignment, and measure ability to
memorize those exact frames before changing scale or claiming fusion gains.
Preserve this8-epoch result; no crossing3 or validation parameter selection.
See [CPU BEV results/audit](URBANING_BEV_CPU.md).

## CPU standalone BEV triplet prepared (2026-11-05)

User wants to continue CPU work while a GPU grant would take time. Updated
hpc-grants: CPU25000h granted/406.21h consumed; storage500GB; **no GPU allocation**.
Visible GPU partitions are not authorization to run them. Full BEVFusion remains
separate GPU/adaptation work; current choice is a small CPU prototype that creates
new box centers/sizes/orientations, not another proposal scorer or2D metric switch.

Prepared `urbaning_bev_cpu.sbatch`:8CPU/24GiB/6h upper limit, same400 train/200
validation. Three independently trained, identical small heads with strict input
masks:RGB-only, Car1 point-grid LiDAR-only, RGB+LiDAR. Old pretrained CoBEVT is
only an external reference (different training, possibly saw development clips).
Frozen ImageNet MobileNet spatial maps,16-channel fixed compression, calibrated
voxel pull at4 heights,200x200 grid/1.1m cells; train-only ground/box priors.
No reproduction of Simple-BEV/BEVFusion or universal modality claim. Coarse
representation/depth ambiguity/frozen encoder limit expected accuracy.

Important correction: **26 was correct LiDAR two-wheeler proposals**, not all
train annotations. Full train GT is Vehicle18196,Heavy1258,2Wheeler389,Ped2920
frame instances. New heads train on all GT, including LiDAR misses. Same primary
four-class BEV mAP@.5, global sort, original0–100m radius filter; fresh matching,
class AP and raw predictions/GT exported. No GT removed for target-cell collisions.
Fixed8 epochs, final epoch only, same initialization/order/optimizer; no validation
search, no crossing3. Native associations remain offline. Runtime RGB-only input
never receives LiDAR values/proposals/scores and vice versa.

Feature/model checkpoint resume, isolated old CPU runtime, no source rewriting.
Eleven focused tests and actual full-size synthetic RGB/CPU training smoke passed;
local rates~.49s for6-view encode/lift and~.067s per head update on4 threads,
not an Ares estimate. **No native Ares run, job ID or AP result yet.** See
[CPU standalone BEV protocol](URBANING_BEV_CPU.md).

## Car1 RGB full400/200 completed and checked (2026-11-05)

Ares21594528 completed13m41s, exit0. ZIP SHA256
`886a4fe190a8fd065bb5fcfee7e3ae90b171d9354dc9bf38fdcc2fe09e34efd6`,
134,604bytes. Uploaded archive hash/CRC, all macro arithmetic,400/200 unique
native keys, unchanged extractor and source/model identities checked. Original
Car1 AP/GT support matches separate historical AP-export validation ego exactly.
No detector inference, no crossing3; these are still the same3 development
recordings, not the whole dataset or new independent validation.

Primary BEV mAP@.5 global: raw21.5380%, learned LiDAR22.9784%, RGB22.6447%,
shuffle20.2564%. **RGB adds-.3337pp versus learned LiDAR**, so pilot+.2147pp
increment did not persist. Total+1.1067pp over raw is not solely RGB benefit.
Class RGB-minus-learned changes:Vehicle+.8764pp,Heavy-.1515,2Wheeler-2.4627,
Pedestrian+.4031. The two-wheeler fall contributes-.6157pp to macro; others
jointly offset+.2820pp. Full train target positives/negatives:Vehicle10424/5769,
Heavy566/777,2Wheeler**26/332**,Pedestrian812/2677. These are frame-proposal
instances, not unique objects. Sparse positives motivate an overfitting/crop
coverage diagnostic; cause is not established. Secondary RGB deltas@.3+1.0497pp,
@.7-.8006pp; keep primary@.5.

The smaller full ZIP has no QA JPGs: first train/validation frames reused pilot
features, and cached return skips QA export. Only earlier pilot two-frame visual
inspection exists; no full-run alignment proof. This is an export limitation,
not evidence RGB features were absent. Prior pilot images remain preserved.
Next useful work is class-specific train/validation score diagnostics and
inspection of scarce correct two-wheeler crops using existing caches before
new training. **No further job prepared/submitted.** See
[RGB results](URBANING_RGB_PILOT.md).

## Car1 RGB CPU pilot completed; full cached development run prepared (2026-11-05)

Ares21593944 completed6m01s, exit0. Uploaded ZIP SHA256
`01a846a25d7a760505423a5fd6163a9d07fd4a6bab70c48ff0f644fe2a244455`,
6,974,819bytes; hash/CRC/report counts/arithmetic checked.120 train/60 validation.
Primary global BEV mAP@.5: original22.3192%; learned LiDAR23.2347%;
LiDAR+RGB23.4494%; fixed shuffle21.3288%. RGB adds **.2147pp over learned
LiDAR**, not the entire1.1302pp versus original. Versus learned LiDAR, class
changes:Vehicle+.8943pp,Heavy+1.4289,2Wheeler-1.8762,Pedestrian+.4119.
2Wheeler train head has only7 positive/101 negative proposals, not unique
objects. RGB geometric crop availability is98.62% train/99.11% validation;
this is not visibility or alignment proof. Offsets-1..+45ms remain offline.

Inspected selected first-train/validation overlays/crop: plausible projections
onto cars/pedestrian, plus background/occluded predictions; no obvious gross
axis issue in those views. Only2 native frames have exported QA; not exhaustive.
RGB@.3 improves but@.7 falls versus learned LiDAR; keep primary@.5 and class
tradeoffs explicit. No blind/generalization/full-BEV claim.

Prepared same-settings run on all existing400 train/200 validation frames in
these same3 development recordings, no crossing3 or detector. Script now accepts
positive frame caps and optional completed feature-cache seed. Keep extractor
code unchanged for verified180-frame reuse; refit PCA/heads on train400 only.
No class bypass or hyperparameter selection from inspected validation. New
output `runs/urbaning-rgb-full-001`; existing pilot is preserved. **Not submitted
from this session and no full400/200 result yet.** Details in
[RGB pilot protocol/results](URBANING_RGB_PILOT.md).

## Car1 RGB late-fusion CPU pilot prepared (2026-11-05)

Agreed roadmap: A=Car1 LiDAR, C=multi-agent LiDAR (authors plus our acquisition);
now B=Car1 LiDAR+RGB, later D=multimodal multi-agent, then source/modality selection.
User explicitly chose the quick CPU late-fusion pilot: fixed existing LiDAR
proposals, frozen RGB features and a learned scorer, no new3D boxes.

Prepared `scripts/slurm/urbaning_rgb_pilot.sbatch`:8CPU/24GiB/3h upper bound,
reuse existing converted RGB/YAML/predictions and input packet in place; no new
upload or detector. Predeclared uniform sampling:120 train (60 per original
recording),60 validation from crossing2; no crossing3. Compare original LiDAR,
learned LiDAR-only control with the same projection metadata, learned LiDAR+RGB,
and fixed seed0 RGB shuffle diagnostic. Primary BEV mAP@0.5, global sort,
per-class AP and secondary frame-order AP. Always re-match after score changes;
pairwise IoU reused for speed. Never compare sampled AP to historical1400 AP.

Frozen ImageNet MobileNetV3-small576 features; train-only PCA16 and two fixed
ridge0.1 residual logistic heads. No validation parameter search; GT only
offline supervision/evaluation. Use pinned converted camera axes and preserve
native associations/timing offsets. Save projection overlays/crops, feature
checkpoints, model and compact result ZIP. Isolated torchvision0.21.0+cpu;
no shared venv edits. Existing torch2.6+cpu / NumPy1.26.4 required.

Seven focused tests passed, including synthetic end-to-end source bindings,
export and resume. Raw/reversed matching parity passed on5 real cached frames.
Actual pinned CPU MobileNet weights/import/batch feature extraction checked.
**No Ares job or real RGB result yet; native alignment still needs the exported
visual QA.** This is proposal reranking, not full trainable BEV fusion. Details:
[RGB pilot](URBANING_RGB_PILOT.md).

## Zero-cost controls/classes/recordings completed (2026-11-04)

Ares **21587032** completed in7m19s, exit0. Output ZIP SHA256
`f014f2fa71da358961d90e9f5c4d9459fa9b233a8b3cc26d065fa6b058dfc9a3`,
2,486,881 bytes. CRC/member/code hashes verified; all10 policy AP results
replayed across full1400,7 sequences,5 recording groups in both modes. Both
100-seed schedules/costs and all summary arithmetic verified; control AP sampled
at seeds0/99 across all scopes and both modes. No fitting or detector.

Cost0 remains **33.6741% mAP /1813 queries**, ALWAYS **33.7102%/2033**:
220 saved (**10.82%**) at **.0361pp** observed mAP loss. Uniform exact1813
random mean **32.7412%** (+.9329pp policy); strong Infra-priority/fallback plus
random Car2 extras mean **33.1509%** (+.5232pp policy). Above all100 draws of
both controls, but not a recording-level significance test. Pure p=.9 remains
32.8147%/1829.68. Thus selection adds observed value beyond simple Infra
priority at equal global cost. This cost0 follow-up is **post-hoc after test
inspection**, not newly validation-selected or blind/generalization evidence.

Class AP versus ALWAYS: Vehicle **-.2502pp**, Heavy_Vehicle **+.9117pp**,
2Wheeler **-.2721pp**, Pedestrian **-.5337pp** (5.4957→4.9620%). Near-equal
macro mAP hides class tradeoffs, not statistical equivalence. Across5 original
groups:0009 +1.4521pp/114 queries saved;0010 -.1035pp/28 saved;0011 -.5344pp/27
saved;0012 unchanged/no saving;0024 -.1247pp/51 saved. Model beats strong
random mean in4/5 groups, but subgroup budgets differ; equal cost is global
only. Full AP is not the arithmetic mean of group AP. Preserve earlier cost.5
32.6966%/1448 (28.78% saving,1.0136pp loss) separately. Best model uses geometry,
not current Car1 evidence; no ROI, causal visibility, bytes/latency or available-
peer abstention claim. See [completed follow-up](URBANING_ZERO_COST.md).

## Zero-cost randomized/group/class follow-up prepared (2026-11-04)

User authorized an Ares job for the inspected cost0 point. Prepared
`urbaning_zero_cost.sbatch`: reuse existing21586593 spatial score ZIP and21578375
portable outcomes in place. No new upload, training, model/detector inference,
new cost selection, installs or shared environment change. Verify original
cost.5 choices and old-policy AP; reproduce observed cost0 total1813.

Two100-seed exact1813-query controls: uniform feasible query events, and strong
secondary Infra-priority/Car2-fallback plus502 random Car2 extras among722
both-available frames. Neither receives model timing/GT. Primary mAP@.5,
requests/savings/loss; class AP and all7 sequences/5 original recording groups,
both AP modes. Equal cost is global only; subgroup queries are reported. Pure
independent random remains visible. Seed spread is not recording-level confidence.
This is post-hoc after inspecting cost0, not a new blind/validation-selected test.

Three focused tests and shell syntax passed; real-input two-seed end-to-end
smoke covers exact1813, controls, class/group outputs and identical resume.
**Full100-seed follow-up has not run/submitted from this session.** No random,
class or group result is claimed yet. See [zero-cost follow-up](URBANING_ZERO_COST.md).

## User-requested zero-cost full diagnostic (2026-11-04)

The user asked about not subtracting query costs. Read-only replay from frozen
full spatial score checkpoints and original portable1400 outcomes, no fitting,
detector or cost search: geometry/top10 **cost0 =33.6741% mAP /1813 queries**,
versus ALWAYS33.7102%/2033. Saves220 (**10.82%**) at **.0361pp** observed mAP
loss. Original predeclared cost.5 point remains32.6966%/1448 (28.78%,1.0136pp).
This new cost0 point is **post-hoc, requested after inspecting full results**,
not a newly validation-selected or blind test result. No saved default changed.

Zero cost chooses Car2/Infra/both/none on62/747/502/89 frames; both-available
subsets18/202/502. It still skips220 queries because the joint head predicts
no extra benefit/harm versus a singleton, not because of a penalty. Compared
to cost.5,365 frames add a second partner. Default-order AP24.5426% is separate.
The tiny global average mAP gap does not establish statistical equivalence or
uniform class performance. On200 validation frames geometry/geometry and
local/local cost0 equal ALWAYS37.6015%/334; mixed local/geometry36.2489%/319.
Keep200/1400 scopes separate. See [zero-cost diagnostic](URBANING_GAP_FULL.md).

## Hybrid stage validation completed — no improvement (2026-11-04)

Ares **21586927** completed in50s, exit0. ZIP SHA256
`f7ea1bdce81ac9a98df07367c2b60fb3e107b171e693be5daaa667461b4a7677`,
2,426,684 bytes. CRC/member/model/deployment/code hashes passed. All40 candidate
AP results and8000 decisions reproduced; all12 selections match the declared
validation rule. Random controls independently checked at seeds0/99. Scope:
**same200 crossing2 development frames**, not1400 crossing3, no refitting.

Proposed local-gap/geometry-benefit composition did not help. At fixed cost.5:
**32.1397%/242** versus geometry/geometry **36.0361%/271**; different counts.
Under original cap300, selecting original cost-grid points yields local/geometry
**34.1327%/288**, dominated by geometry/geometry **36.0361%/271** (1.9035pp lower
mAP,17 more queries). Reverse geometry/local **34.7960%/277** also dominated.
These two mixed points are below exact-total random means35.6541%/35.1287%.
Local/local at cost.5 **37.6039%/333** is practically ALWAYS37.6015%/334;
.0024pp at one saved query is not a substantial acquisition gain. Under cap300
local/local remains35.4918%/283. No hybrid1400 evaluation has been performed.

Gap localization and partner-recoverable utility are different targets. Their
mismatch is a hypothesis to investigate, not a proven causal explanation or
proof current Car1 evidence cannot help. No further target/model training has
been performed. Preserve the existing full geometry32.6966%/1448 result; do not
mix datasets or claim this pilot improved it. See [hybrid results](URBANING_GAP_HYBRID.md).

## Hybrid gap/partner-stage validation prepared (2026-11-04)

User asked to incorporate current Car1 evidence into the geometry-only selection.
Prepared `urbaning_gap_hybrid.sbatch` for200 crossing2 development-validation
frames: frozen local gap head selects10/all400 fields, frozen geometric subset
benefit heads score them, one whole-frame action after cost. Fixed2x2 comparison
also includes geometry/geometry, local/local and reverse geometry/local. No new
training, detector, installs, crossing3 access or file upload. Existing Ares input
packet and validation21586379 result provide all verified sources.

Primary comparison uses common cost.5; actual query counts can differ. Secondary
same old cost-grid/caps select12 configurations on development mAP, then freeze
all settings and original weights before random controls. Pure independent random
is reused; exact-total controls stay secondary. Both homogeneous pairs must
reproduce old choices/AP at every cost. Report global-sort mAP@.5/requests/savings/
loss, both AP modes and class AP; never use F1 as primary. No new blind-test claim
for previously inspected development or crossing3 data.

All16 gap-related tests and shell syntax passed; real-input reduced-grid/two-seed
smoke covers four pairings, old-control parity, report/deployment ZIP integrity
and identical resume. **Full hybrid experiment not yet run/submitted from this
session**. No improvement claimed. See [hybrid protocol](URBANING_GAP_HYBRID.md).

## Full crossing3 spatial replay completed (2026-11-04)

Ares **21586593** completed in8m16s, exit0. ZIP SHA256
`82227530fb755da55bc516cc495ebeb70aaa9323a3e6adf892b13af3ee814869`,
14,679,451 bytes. CRC/all25 member hashes/code hashes passed. All18 frozen
policy AP results reproduced in both modes and25,200 decisions reproduced
from spatial checkpoints. Exact-total random checked at seeds0/99. No fitting,
new cost selection or detector; same1400 previously inspected crossing3 frames.

Predeclared geometry/top10/cost.5: **32.6966% mAP /1448 queries**, ALWAYS
**33.7102% /2033**:585 saved (**28.78%**),1.0136pp loss. Old tree32.5766%/1488:
new point +.1200pp and40 fewer requests. Old regional32.3282%/1401 has47 fewer
queries but lower mAP. Pure random p=.75:31.4119%/1523.43; p=.9:32.8147%/1829.68.
New exact-total random at1448 mean31.0770% (+1.6196pp policy advantage), above
all100 draws but not a recording-level significance test. This control samples
uniform query events; older histogram/schedule controls have different constraints.

Primary actions: Car2/Infra/both/none =71/1103/137/89. All89 no-query frames
have no available peer; no learned abstention is shown. Of722 both-available
frames, Car2 alone27, Infra alone558, both137. Geometry-only success does not
establish local detection-evidence-conditioned gap recognition. Vs old tree,
sequence mAP improves3/ties1/drops3;2Wheeler AP drops, other classes increase
slightly or substantially; pedestrians still below Infra-only. No new blind-test,
ROI communication, bytes/latency or uniform class improvement claim. See
[full result table and limits](URBANING_GAP_FULL.md).

## Full crossing3 spatial replay prepared (2026-11-04)

User authorized a job for the new policies on the **same 1400 crossing3 frames**
as older results. Prepared `scripts/slurm/urbaning_gap_full.sbatch`: reads the
existing Ares validation output21586379 and full portable outcome ZIP21578375
in place, verifies exact hashes, keeps all18 frozen costs/weights and declares
geometry/top10/cost.5 as the primary transfer point. No new upload is needed.
Historic validation caps are labels, not constraints enforced on crossing3.
No refitting, tuning, detector, installs or shared venv changes. No new blind-test
claim for previously inspected crossing3. Main global-sort mAP@.5 and requests;
pure independent random plus secondary fixed-total random, both AP orders,
class/sequence results and old-policy comparisons. Atomic spatial/AP checkpoints.

Local checks: four focused fixture/boundary tests plus the existing gap tests,
shell syntax, real frozen model/config loading, and all eight historical policy
AP results reproduced on the exact portable1400 outcomes in both orders.
Raw Car1/pose inputs are only on Ares; **the new full spatial replay has not run
and no job has been submitted from this session**. Worker upper limit4h,
4CPUs/12GB; actual duration unknown. See [full replay guide](URBANING_GAP_FULL.md).

## Gap acquisition validation completed (2026-11-04)

Ares job **21586379** completed; supplied ZIP SHA256
`78c2e20d12acb3334931d0ca763e0cf4d414f2ba7779ef0c67e95869416e8786`,
3,345,608 bytes. CRC/member/model/implementation hashes passed. All 60 candidate
AP results reproduced in both ordering modes; all 18 selections match the fixed
cost/budget rule. Pure and exact-total random controls checked at seeds 0/99.
No detector, refitting or crossing3 access. Scope remains the **same inspected
200-frame crossing2 development validation**, where costs were selected.

Best selected mAP under cap 300: **geometry / ten gap-selected cells**,
cost .5, **36.0361% mAP / 271 requests**, versus ALWAYS **37.6015% / 334**:
63 requests saved (18.86%), 1.5654pp mAP lost. Same-total random mean **34.8337%**,
a +1.2024pp policy advantage; above all 100 draws, not a recording-level p-value.
Pure independent random p=.75: **33.9805% / 250.65**; p=.9: **36.1704% / 300.48**.
Policy chooses Car1+Car2 / Car1+Infra / both on 75/54/71 frames, never NO here.
This is a transfer candidate, not independent generalization evidence.

Local/top10: 35.4918% / 283; combined/top10: 34.4460% / 252. All400 pooling:
geometry 31.5265% / 235, local 34.7184% / 260, combined 33.0712% / 244.
These use different actual query counts and are not equal-cost ablations.
Combined/top10 at cap200 is worse than constant Car1+Car2 at equal 200 queries.
Heavy_Vehicle AP improves in geometry/top10 versus ALWAYS; other three class
APs drop. No stronger Infra-priority control at cost271 was measured. Full
selected settings/model packet are frozen for subsequent unchanged replay;
previously inspected crossing3 cannot become a newly blind test.
See [complete validation tables](URBANING_GAP_ACQUISITION.md).

## Gap acquisition replay prepared for Ares (2026-11-04)

After a conversation interruption, the user requested moving computation to Ares.
Prepared a resumable CPU job to turn the unchanged three spatial profiles into
one whole-frame action, compare top10 gap-selected cells versus all400 pooling,
and select fixed cost-grid points under .5/1/1.5 requests/frame on the existing
200-frame development validation. Primary global-sort BEV mAP@.5 plus requests,
pure independent random prominent, exact-total offline random secondary.
No refitting, detector, crossing3 payloads, installs or shared venv changes.
Input ZIP SHA256 `c1e72f33bdbd61edab2773bac81d2f582b88ed4d625e9743c35ac194d8bb50ee`,
13,257,571 bytes. Five focused tests, shell syntax and real-input AP/frame-binding/
checkpoint smoke checks passed. **The full replay has not run; no job submitted
from this session and no new final policy mAP/query result exists.** See
[submission and resume guide](URBANING_GAP_ACQUISITION.md).

## Gap/source pilot trained and reviewed (2026-11-04)

User authorized the next pilot. Completed locally on existing export: 400 train
frames (two recordings), 200 validation (one inspected recording), no crossing3
payload access or detector calls. Three fixed-capacity ExtraTrees profiles:
geometry 20 features, local Car1 26, combined 46. Each has one gap classifier
and three separately supervised signed local FP+FN reduction heads. No tuning
or validation-selected winner. Frozen portable JSON weights match sklearn.

Correct gap regions among top10: pure random **.672**, geometry **3.585**,
local **4.660**, combined **4.485**. Empty-only top10: random **.386**,
geometry **2.815**, local **1.490**, combined **2.355**. Combining features does
not uniformly improve localization; geometry is best for empty-only regions.

Read-only review couples predicted gap top10 with predicted best feasible
subset. A success requires >=1 recovered Car1 miss AND positive local FP+FN
reduction. Successes per10: geometry **2.460**, local **2.045**, combined
**2.220**, pure random **.276**. Same-region random-source expectations are
2.198 / 1.750 / 1.940. These are region/source ranking diagnostics, **not new
detection mAP, query savings or ROI transmission performance**. No costs yet;
the 'both' source subset is feasible. Whole-frame outcomes cannot be mixed
across cells and treated as detector output.

Review ZIP SHA256 `f269aec67685dfa6aed1fa194facdcfb984a0dab9e0bc518101ce8faea739f2d`,
4,986,101 bytes, preserves original frozen weights/results and stricter review.
See [gap pilot](URBANING_GAP_PILOT.md). Next: define whole-frame aggregation and
costs on development data before common mAP replay and future unseen recordings.

## Conditional gap diagnostic completed (2026-11-04)

No fitting or crossing3 payload access. A post-hoc Car2 near (<40m)/far split,
overlap-weighted within GT-class / Car1-distance / empty-low-high-score strata,
retains the recovery association in both training recordings and validation:
70.91% vs 29.37%, 68.89% vs 14.97%, and 50.78% vs 13.75%, respectively.
GT class is an offline diagnostic variable, never a runtime feature of a missed
object. These are coarse descriptive adjustments, not causal estimates or
confidence intervals. Validation common support covers 6698/8086 misses.

Only 2741/71196 **empty detection cells (3.85%)** contain a missed GT, despite
those cells holding **50.63% of all missed appearances**. This distinguishes
gap-localization risk from source recoverability conditional on a miss. Next
proposed pilot separates those questions, using GT for targets only, and checks
geometry-only/local-only/nonlinear-combined variants on development data.
No new spatial learner has been fitted or validated.

## Descriptive gap analysis completed (2026-11-04)

User requested characterizing recoverable missing information and a complete
mAP/request/savings/loss table. Full-1400 results are now consolidated, including
an offline replay of the historical one-random-peer rule (100 seeds):
**31.7038% mAP / 1311 requests**. Entropy subsets .5/.7 reproduces ALWAYS exactly.
No fitting or detector inference; NumPy 1.26.4 preserves confidence-tie parity.

Separate exploratory **validation-only** diagnostics on 200 crossing2 frames:
14937 GT appearances, 8086 Car1 misses, 4283 recoverable by at least one feasible
configuration (52.97%). 4094 misses (50.63%) fall in empty Car1-detection cells.
Car2 recovery conditional on a miss drops from 474/743 (63.80%) within 20m of
Car2 to 86/2489 (3.46%) beyond 80m, using cell-center distances. This is an
unadjusted association in one already-inspected recording, not a causal result
or runtime gap probability. Empty cells do not establish visibility/occlusion.
On the same 134 both-available frames, Car2 recovers 477 appearances not
recovered by Infra, and joint recovers 146 missed by both singles. Adding Car2
to Infra also loses 235 existing matches. No corrected spatial model trained.
See [gap diagnostics](URBANING_GAP_DIAGNOSTICS.md) for definitions, scope and
the proposed next conditional analysis.

## Frozen regional/tree full replay completed (2026-11-03)

User requested the unchanged regional and tree policies on the full 1400-frame
crossing3 inventory. The new runner reuses all completed prediction/pose caches,
requires exact frozen input hashes and reproduces previous baseline/policy AP
in both ordering modes. No detector, fitting, package installs or shared venv
changes. **Ares job 21578375 completed in 6m24s, exit 0.** Uploaded result
ZIP SHA256 `e7070e7bfc4743a7bba90310ce3a39ba893281c62c6f7c0e2a05c6c56472e802`,
3,175,911 bytes. Hash/CRC, 1400 payload bindings and both-order replay parity
of all eight policies passed using the portable statistics.

Full-test global mAP@.5 / requests: regional **32.3282% / 1401** (31.09%
request saving versus ALWAYS), tree **32.5766% / 1488** (26.81%), ALWAYS
**33.7102% / 2033**. Both are higher quality and lower cost than prior
GainGeometry **32.2393% / 1533**. Pure independent random p=.75 averages
**31.4119% / 1523.43**. Exact-budget controls average **31.9546% / 1401** and
**32.2086% / 1488**: advantages .3736pp and .3681pp, above all 100 draws.
This is randomization evidence on five already-inspected recording groups,
not proof of generalization or a recording-level significance test.

Tree always queries available Infra, and adds Car2 in 177/722 both-available
frames; it never abstains when a peer exists. An explicitly **post-hoc** control
with Infra priority and random timing of extra Car2, at equal total budgets,
averages **32.1277% at 1401** / **32.3434% at 1488** over seeds 0–99. Regional
and tree retain modest **.2006pp/.2332pp** advantages. Exact budgets are borrowed
from policy outcomes; this is an offline diagnostic, not a deployable method.
Both policies lose pedestrian AP versus Infra-only, and mean F1 is slightly
below the original budget-random means. Keep these limitations alongside mAP.

Pure independent random is a main comparison, not hidden behind model-conditioned
controls. Predeclared p=.5/.75/.9 with seeds 0–99; matched budget/schedule remain
secondary. Primary: global-sort four-class BEV mAP@.5 plus requests/savings.
The regional model retains its known spatial pooling limitation and penalty 8;
the tree retains F1 cost .05. Do not tune either on crossing3, which has already
been inspected. See [full frozen replay](URBANING_FROZEN_FULL.md).

## AP measurement completion verified (2026-11-03)

Ares export **21577295** completed successfully in 2m01s. The user supplied
`urbaning-ap-export.zip`: 1,737,081 bytes, SHA256
`ce8893d439d446edf0cb328881a0b31523a138b1eed713b844f68e1da7e557c5`.
Archive/code/source bindings and both-order baseline parity passed. The common
evaluator replayed unchanged regional/ridge/tree validation choices and both
100-seed matched controls locally with NumPy 1.26.4. No fitting or detector calls.

On **200 validation crossing2 frames** (not the full crossing3 test), global-sort
BEV mAP@.5 / requests: ALWAYS **37.6015% / 334**, regional audited prototype
**37.5371% / 329**, prior ridge **36.9347% / 296**, prior tree **37.2465% / 313**.
Regional saves 1.50% requests and loses .06448pp mAP versus ALWAYS. Its budget
random mean is **37.3700%**, but its schedule random mean is **37.5503%**, both
at 329 requests. Thus better F1 than schedule random did not mean better mAP.
Prior ridge random means: budget 35.8588%, schedule 37.1092%; tree: 36.6280%,
37.0627%. All are already-inspected, selection-used validation results.

Default-order mAP remains separate: ALWAYS 27.4893%, regional 27.4813%, prior
ridge 27.0681%, tree 27.1902%. Previous ridge/tree class AP reproduced exactly
in both orders. Per-class AP, both controls and a Polish summary were bundled
as `urbaning-common-ap-21577295.zip`. Missing regional AP is now completed;
the structural pooling limitation and lack of independent evidence remain.
No corrected spatial model has been trained. Earlier pending-export statements
below describe the preparation stage and are superseded here.

## AP measurement completion prepared (2026-11-03)

After the audit, the user authorized completing the missing AP export/common
evaluator first. `scripts/urbaning_ap_replay.py export` reads the existing two
training caches (400 frames) and validation cache (200), verifies original fixed
baseline AP/GT/fallbacks and writes portable per-detection confidence/TP/FP/GT
statistics with exact frame/run/trace/payload bindings. No detector, fitting,
downloads, environment changes or crossing3 access occurs. The final ZIP is
re-read and checked before DONE. One Ares worker job is prepared; **the real
600-frame export has not been run from this session**.

The common evaluator reuses the existing cached evaluation function. It accepts
frozen choices, keeps global-confidence-sort BEV mAP@.5 primary and upstream
default AP separate, includes class AP/F1/request diagnostics, and performs
exact budget/schedule controls. Prior ridge/tree choices must reproduce both
stored AP orders; the audited regional prototype retains frozen F1/requests.
There is no model/budget/threshold selection. The corrected spatial learner
is not implemented by this step. Missing regional AP is **still pending the
real Ares export**, not a new completed result.

Local validation covers fixture export/readback, nontrivial AP ordering, split,
hash and source guards, old-policy adapters, missing classes and matched controls.
Five supplied real inspection cases reproduced 20 class-count/frame-F1 outcomes;
these selected cases do not replace full-cache parity. See
[AP export/replay protocol](URBANING_AP_REPLAY.md) and the audit below.

## Audit verdict — authoritative current interpretation (2026-11-03)

The user objected to inconsistent metrics and overstated intermediate progress,
and authorized an audit rather than another experiment. See
[the complete audit](URBANING_AUDIT_2026-11-03.md). No new detector job or fitting
was performed. Historical entries below are a ledger, not independent successes.

The checkpoint reference is close to the released eval file: upstream-default
mAP@.5 24.8134% versus 24.8563%; global-sort mAP from the same predictions is
33.7102%. Never mix these orderings or call their difference a model improvement.
The 1400-frame report has consistent hashes/arithmetic and correct matched random
budgets. Both original learned policies have lower mean mAP/F1 than budget random.
Full raw-cache matching was not rerun locally; those original caches are on Ares.

**A structural limitation was demonstrated in the regional prototype:** an
affine per-cell predictor followed by sum pooling depends only on feature sums.
Exchanging low/high scores between cells near opposite peers can change local
maps while leaving all final action scores/decisions unchanged. It does not
establish spatial need-to-partner reasoning. MSE improvement 23.4% is prediction
error only. The five saved validation requests (1.50%) are not an independent
acquisition advantage. New-policy mAP was promised without the necessary export.

The repeated 200-frame validation is development-only; 400 training frames are
two recordings, not independent cell samples. Test material was partly inspected
before subsequent extensions. Random seed spread is not a confidence interval.
One CoBEVT LiDAR checkpoint was evaluated, not every fusion method or RGB/thermal.

Five of six shared archives passed integrity checks. The learning ZIP was
damaged at its prediction NPZ; nine complete members including all models/report
were CRC-recovered without changing their bytes. A compact repair omits that
incomplete NPZ and records how to regenerate predictions without fitting.
Preserve caches and historical results. No further model search is part of audit.

## Regional acquisition replay completed (2026-11-03)

The user authorized the same F1/request-savings comparison for the new regional
predictor, with fair random controls. Its coefficients remain frozen. Sum signed
predicted FP+FN reductions over all 401 cells/classes, then select one feasible
whole-frame action with a per-peer error-count penalty. Fixed grid
0/1/2/4/8/16/32/64 selects penalty 8 on validation F1 minus .05*requests. These
are distinct units; the regional counts are not passed as F1 gains.

On the same 200 validation frames, ALWAYS makes **334 requests**, F1 **67.4533%**;
regional makes **329**, F1 **67.3785%**: only **five requests saved (1.50%)** and
.07476pp F1 loss. It chooses Infra instead of both on five frames, and never NO.
Penalty 16 saves 49.70% but drops F1 to 62.9455%; it is an unselected tradeoff.
Prior ridge/tree counts and F1 were reproduced from their saved choices after
exact provenance checks: ridge 296 requests/66.8805%, tree 313/67.0080%.

100 exact budget-matched random controls average F1 **67.2597%** at the same
329 requests; regional exceeds 92 draws. Schedule-matched controls average
67.1036%; only five ambiguous single-peer choices exist (32 possible schedules,
30 unique among 100 seeds). Random spread is not a recording confidence interval.
This is validation-selected development evidence, not a crossing3 test result.
**New-policy mAP remains unavailable locally**: counts lack per-detection scores.
See [regional policy replay](URBANING_REGIONAL_POLICY.md). Earlier claims below
that no acquisition replay exists are superseded here; no independent test exists.

## Completed regional feature-ablation pilot (2026-11-03)

Regional dataset job **21576386** completed and its uploaded ZIP was audited:
400 train / 200 validation frames, exact file hashes, identities, availability,
TP/FP/FN conservation and recovery/loss bindings. Validation frame F1 reconstructed
from regional counts equals the earlier tree pilot. Overflow target counts are
zero in these recordings. The 46 features are manually engineered hypotheses,
not a feature set supplied by the UrbanIng paper.

The user authorized fitting the first regional learner. A NumPy ridge experiment
ran directly on that ZIP locally in about five seconds, with no new Ares job,
detector calls or crossing3 access. Three directly supervised action heads predict
per-class regional **FP+FN reduction**. Train-only scaling, unavailable-action
masks and recording splits are enforced. Fixed alpha grid .01/.1/1 selects by
validation macro MSE; this is not acquisition policy selection.

Validation MSE: zero **.049041**, training mean **.048335**, geometry **.047468**,
local evidence **.041654**, combined **.041330**, plus neighbors **.041260**,
full class-aware 46 features **.037557** (alpha .1). Full improves this prediction
error 23.4% versus zero, **not detection F1/AP**. Changed-cell MSE improves
1.562838→1.131719, but harm-cell MSE worsens 1.278871→1.602021. Empty-Car1
regions improve minimally or not at all: most signal remains in regions with
existing detections. The information-deficit goal is therefore not solved.

Five models, predictions, a fixed example map and detailed stratified report
are generated. No independent test or new request/F1/AP/utility result exists.
The one validation recording has already been inspected; avoid treating it as
unseen. See [regional learning protocol](URBANING_REGIONAL_LEARNING.md).
Earlier preparation statements below are superseded by this section.

## Regional dataset preparation (2026-11-03)

Inspection job **21574240** completed in 2m18s (exit 0). The uploaded
`urbaning-frame-inspection.zip` contains five selected validation cases and
all 200 frame match traces. In frame 161, GT object 2 is Vehicle at about 67m
from Car1. Car1 has no overlapping prediction, Car1+Car2 reaches IoU .532,
Car1+Infra's best overlap is .412 and all sources .503. This is a qualitative
GT-selected case, not proof of visibility or a general partner ranking. The
NO-beneficial category had three positive candidates but was omitted by spacing;
do not claim it was absent from the recording.

The user approved the next concrete step: prepare fixed regional inputs and
offline targets from the existing **400 train / 200 validation** frames. The
exporter is prepared, not yet run on real full recordings. It retains all 400
fixed 10m cells plus explicit overflow, uses only Car1 detections and assumed
pose/availability metadata as 46 input features, and exports GT-derived regional
TP/FP/FN, recovered/lost objects and deltas separately. Count conservation must
reproduce full-frame matching. Unavailable action masks are mandatory; no GT-driven
cell selection or per-cell communication charge is allowed. There is no fitting,
inference, download or crossing3 access. See
[regional dataset protocol](URBANING_REGIONAL_DATASET.md).

This is input/label preparation, not a learned information-deficit map or a
new performance result. Empty detection cells do not establish observability.
The intended next learner can predict local partner usefulness after checking
these labels; raw LiDAR coverage and RGB/thermal remain later steps.

## Current objective, verified results and spatial inspection (2026-11-03)

The user restated the main goal: Car1 should identify spatial regions with
missing/uncertain information and predict whether another agent's particular
sensor can improve the task there, before receiving its perception payload.
Agents can own multiple modalities; RGB/thermal are later extensions. Global
frame-level partner selection and class-wise reporting are intermediate steps.
Low-score detections alone cannot represent entirely missed/occluded objects;
do not claim to have a visibility/observability map from box summaries.

The user supplied the completed **1400-frame full-policy report** (seven
crossing3 sequences, five original recording groups). All-source predictions
match the earlier benchmark numerically. Global-sort mAP@.5 / F1 / requests /
utility at cost .05: ALWAYS **33.7102% / 54.5905% / 2033 / .473298**;
Gain–Ego **33.1274% / 53.7529% / 1838 / .471886**;
Gain–Geometry **32.2393% / 52.2992% / 1533 / .468242**. Both learned policies
lose F1/utility to all 100 corresponding exact budget-matched random draws.
Entropy's frozen thresholds reproduce ALWAYS. NO occurs only in 89 frames
with no available partner; neither learned model skips all available peers.
Car2 is available in 766 frames, Infra in 1267, both in 722. Direct partner
quality comparisons must stratify availability.

The GT-assisted offline F1-minus-cost reference uses **1306 requests** (35.8%
less than ALWAYS), F1 **54.0039%**, global mAP@.5 **33.6362%**, utility **.493396**.
This establishes hindsight headroom for that objective, not a deployable policy
or an mAP optimum. Default-order mAP@.5 for ALWAYS is **24.8134%**; keep AP
ordering explicit. The report was read from `urbaning-full-policy-report.zip`.
No completed diagnostic report has yet been supplied.

The validation tree pilot succeeded as job **21569108** after dependency
isolation. On its 200 crossing2 validation frames, ridge alpha 10 won utility
(.594805, F1 66.8805%, 296 requests) against the selected tree (.591830,
67.0080%, 313 requests) and ALWAYS (.591033, 67.4533%, 334 requests).
Its ridge weights/scaling equal the original Gain–Geometry model exactly;
validation success therefore did not generalize to crossing3. Trees have not
been evaluated on the full test in this report. These are validation-selected
results, not an independent performance estimate.

The user now authorized looking at concrete frames and where each source
recovers/misses objects. A separate **train/validation-only** inspector is
prepared, not run on real recordings. It exports full-scene/zoom comparisons,
object-index match traces and a strict Car1-evidence versus offline-outcome
boundary, bundled as one ZIP. It performs no inference/fitting/downloads and
does not alter the completed experiment. See
[frame inspection protocol](URBANING_FRAME_INSPECTION.md). Older preparation
and pending-result statements below are superseded by this section.

## Validation-only nonlinear policy pilot (2026-11-02)

The first pilot job **21569029** failed during the scikit-learn import preflight,
before any cache loading or training. The supplied log tail does not reveal the
original ImportError. The revised batch entry point installs all five pinned
scientific runtime packages into a fresh job-specific directory under
`phdsim-work/dependencies`, verifies versions/module origins and a tiny model
fit inside the existing container, then runs the pilot. It does not change the
shared venv. The experiment output path remains unchanged because that failed
preflight occurred before output creation. No real pilot results exist yet.

The user authorized a cheap comparison of ridge and shallow boosted trees on
the existing crossing1/2 training/validation caches, keeping the same 32
Gain–Geometry features and request cost .05. The isolated runner and batch job
are prepared, not executed on real caches. Three gain heads are independently
fitted with availability masks. A fixed four-configuration tree grid and the
existing ridge alphas are selected on validation utility; the best constant
NO/Car2/Infra/ALWAYS baseline is also selected on validation. Exact matched
random controls use seeds 0–99. See [tree pilot protocol](URBANING_TREE_PILOT.md).

This pilot performs no new detector inference, downloads, pose exports or
crossing3 evaluation, and does not modify the active experiment worktrees,
models or jobs. Validation-selected performance is development evidence only;
no new real results or model improvement are claimed. User-reported diagnostics
job **21566813** was submitted after the full-policy collector; no completed
diagnostic report has been supplied yet.

## Latest execution and diagnostic follow-up (2026-11-02)

The user submitted full-policy array **21564341**, collector **21564342**, and
single-sequence preview **21564899**. Sequence `20241127_0010_crossing3_08` and its
preview completed successfully. The uploaded preview ZIP was read: 200 frames,
Infra available in all 200 and Car2 in 39. Gain–Ego used 217 requests with global
mAP@.5 39.2178%; Gain–Geometry used 237 with 38.6464%; Infra-only used 200 with
39.3278%. Geometry did not improve selection in this inspected recording. The
full seven-sequence policy report has not been supplied yet.

The user authorized post-hoc availability-stratified, original-recording and
paired marginal-F1 analysis, plus frozen gain prediction errors and GT-assisted
utility headroom. A separate diagnostics job is prepared to wait for collector
21564342; it performs no training/tuning/detector inference and packages both
full and diagnostic reports into `urbaning-analysis.zip`. See
[diagnostic protocol](URBANING_DIAGNOSTICS.md). Submit from a separate worktree;
do not edit the checkout used by the active full-policy array. Older preparation
statements below are superseded by these user-confirmed submissions/results.

## Current verified state and next run (2026-11-02)

User-supplied full benchmark report confirms completion of seven crossing3
sequences, 1400 frames, all-source frozen CoBEVT. mAP@.5 with upstream default
ordering is 24.8134%, compared with 24.8563% in the checkpoint release report;
with global confidence sorting the same predictions score 33.7102%. This is a
close numerical reproduction, not an exact match. Do not mix AP ordering modes.

The earlier recording-level experiment and Gain–Geometry fit/test completed.
On the inspected 200-frame crossing3 pilot, Gain–Geometry used 295 requests,
versus 370 for ALWAYS and 365 for Gain–Ego; global-sort mAP@.5 was 36.9542%,
36.0734% and 36.1705%, respectively. Infra-only used 184 requests and scored
37.3602%. These are pilot results, not full-test policy results.

The user authorized expanded policy evaluation on the full 1400-frame test,
using the existing frozen Gain–Ego/Geometry models, cost .05 and seeds 0–99.
The separate full-policy runner is prepared, but no such job has been submitted
from this session. It reads completed benchmark conversions, computes four
counterfactual outcomes per frame and reports both AP ordering modes with matched
random controls. No policy refitting or tuning on crossing3 is authorized by
this expansion. See [full-policy protocol](URBANING_FULL_POLICIES.md).

This session has no direct Ares SSH access; the user runs supplied SSH commands.
Ares paths: `/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work`,
original repo `phdsim`, verified container wrapper `bin/urbaning-python.sh`.
Use a separate worktree and preserve existing outputs. The official model release
currently offers only CoBEVT weights; other methods have configurations but no
weights were found in that release. Earlier dated machine/progress statements
below are historical and superseded by this section.

## Latest geometry-policy extension (2026-10-30)

The user approved predicting partner utility from partner poses relative to
low-score Car1 detections. A separate 32-feature geometry profile, pose-only
sidecar exporter and cached fit/replay path are implemented; the 16-feature
baseline remains unchanged by default. No geometry model has been trained on
real recordings. See [geometry policy contract](URBANING_GEOMETRY_POLICY.md).
Infra's released pose is the bundled site's coordinate origin, not an individual
sensor; use proximity only as a proxy. Pre-query pose sharing is explicit added
metadata, not an established online transport capability.

The user supplied successful Ares container doctor output and the 10-frame CPU
smoke metrics, matching the earlier pilot. Preflight Slurm job 21540119 completed
with exit 0. The user then submitted baseline job **21540128** (8 CPUs, 24 GB,
12 hours); the latest supplied trace showed crossing2 inference in progress.
No final independent-recording policy result has been supplied. This assistant
still has no direct Ares SSH access. Do not update the active Ares checkout while
that experiment runs; use the separate geometry branch/check out afterwards.
Earlier machine-state notes below describe preparation history and are superseded
by these user-provided execution observations.

## Research tracks and reporting

[EXPERIMENTS.md](EXPERIMENTS.md) is an index only. Current UrbanIng LiDAR detection
results live in [URBANING_EXPERIMENTS.md](URBANING_EXPERIMENTS.md); earlier PST900 /
PSTNet segmentation results live in [PSTNET_EXPERIMENTS.md](PSTNET_EXPERIMENTS.md).
Keep their models, splits, metrics and pending work distinct: pixel mIoU is not
detection AP/mAP. Use Car1, Car2 and Infra in UrbanIng explanations and state
which platform performs the detection task.

## Research objective

Study **selective acquisition of existing peer observations** for a defined
perception task. An agent first uses its own available observations and decides
whether to request useful additional observations from other agents. Measure
task quality against communication cost, transferred bytes and latency.

Acquisition here means requesting a measurement already captured by another
agent. It does not inherently mean driving somewhere, taking a new measurement
or exchanging every agent's predictions automatically. Exchanging features or
predictions can be an explicitly chosen protocol, but it is not the definition
of observation acquisition.

Keep the dataset importer, agent allocation, perception, fusion, acquisition
decision, runtime delivery and evaluation as separate responsibilities. Avoid
changing several of these at once when interpreting experiment results.

## Latest agent model

The user explicitly replaced the earlier one-modality-per-agent restriction with
**agent -> sensors[] -> timestamped observations**:

- An agent can own several sensors, including different modalities.
- Each sensor produces its own observations and has its own capture times.
- Vehicles are mobile agents; physical infrastructure sensing stations can be
  static agents with the same observation/communication responsibilities.
- Movement is not the immediate research objective; replay uses recorded poses.
- The observation pool remains independent of simulator agent assignment.
- Allocation controls which observations each agent receives and in which time
  slots. Per-agent counts should be configurable, not fixed at 100.

For UrbanIng, the two recorded cars are the two natural mobile agents. Each has
six RGB cameras and a LiDAR. Infrastructure has thermal cameras and LiDARs.
Representing each physical station as a static agent is the intended direction;
the exact mapping from source sensor names to stations still needs verification.
The number of sensor streams is not automatically the number of agents.

**Implementation boundary:** `datasets/allocation.py` still implements the older
v1 `AgentSlot` with one modality and at most one own observation per frame. The
multi-sensor design and UrbanIng simulation ownership have not been implemented.

## Dataset preparation and storage

The agreed two-stage approach is:

1. Dataset-specific preprocessing creates a pool/catalog of native observations,
   independent of agents, with payload references and separate offline labels.
2. A later scenario preparation stage assigns sensors/observations to agents and
   establishes time-dependent input availability.

The user wants multiple datasets normalized into a common representation, with
large batch downloads/transforms potentially running on Cyfronet later. The
[25-dataset audit](DATASET_AUDIT.md) describes the proposed generic v2 contract;
that general loader is not implemented yet.

The storage direction is Parquet metadata queried with DuckDB, with binary
payloads retained as files/object-storage assets. New datasets are appended
occasionally; experiments generally read stable snapshots. No central database
server or Cyfronet deployment has been set up.

## UrbanIng-V2X: active detection and acquisition study

The current research direction is cooperative **3D object detection**, followed
by acquisition experiments on a working detector/fusion baseline. The dataset
authors benchmarked **LiDAR-only** cooperative detection using PointPillars and
several fusion methods. The availability of RGB and thermal in the dataset does
not mean their published benchmark trained RGB/thermal fusion.

The intended order agreed with the user is:

1. Establish working 3D detection and fusion as a reference.
2. Compare strategies for deciding when, from whom and which information to
   acquire, measuring detection quality and communication cost.

Selective communication already has prior work, including methods in the
authors' benchmark. Do not claim novelty without a relevant literature comparison.
The user selected the authors' released **LiDAR CoBEVT SIS_1_2_vs_3** checkpoint
for stage 1. A pinned external-model adapter and offline comparison runner are
implemented: Car1, Car1 + Car2, Car1 + Infra, all sources, random-one-peer and
an optional uncertainty gate based on Car1's predictions. Car1 (`100000`) and
Car2 (`200000`) are platform identities; this pilot uses Car1 as the detector's
reference agent. Infra (`-1` at crossing1) is the bundled infrastructure site.
All actions share fixed all-source GT. The original multi-sensor native catalog
remains separate.
The released model groups roadside sensors into one infrastructure-site input;
this is not sensor-level acquisition or RGB/thermal fusion.
See [stage 1 protocol and commands](URBANING_STAGE1.md).

Joint subset acquisition is now implemented: no acquisition, Car2, Infra, or
both, with a separately fitted joint-gain head rather than additive single-peer
gains. The user requires comparable random behavior: schedule-matched and
exact histogram/budget-matched randomized controls over the same feasible
subsets, including zero and two requests. The independent Bernoulli-subset
baseline is also retained. Use 100 predeclared seeds, not a selected seed.
See [subset policy protocol and diagnostic replay](URBANING_SUBSET_POLICIES.md).
The fitting/export/replay path passed synthetic tests and cached replay passed
on the existing 20 real frames. No gain model was trained on real data: these
windows share one original recording, so they cannot be split between policy
fitting and validation. Recordings used for either stage are rejected during
evaluation; crossing3 remains reserved. The offline hindsight F1 selector uses
GT and must never be presented as a deployable learned policy.

Model archive integrity and strict checkpoint compatibility have been checked.
CPU tests use synthetic voxels and known boxes. A real-data CPU smoke evaluation
also completed on 20 frames (1–10 and 101–110 of the prepared crossing1 sequence);
see [UrbanIng experiment status](URBANING_EXPERIMENTS.md). The full held-out
benchmark and online acquisition remain pending. The execution environment is a remote
Linux CPU session, not the user's MacBook. One native sequence was downloaded and
verified again there; no GPU or PLGrid session is available. The complete CPU
path works on Linux; native macOS/Apple Silicon dependency installation is not validated.

One real sequence, `20241126_0017_crossing1_00`, release 1.0 of
`doi:10.7910/DVN/A9LPY7`, was downloaded, hash-verified, extracted and cataloged:

| Item | Verified count |
|---|---:|
| RGB streams / native images | 12 / 4,814 |
| Thermal streams / native images | 6 / 3,721 |
| LiDAR streams / native point clouds | 6 / 2,478 |
| Auxiliary navigation streams / records | 2 / 5,600 |
| Source synchronization anchors | 200 |
| Association memberships | 5,200 |
| Tracks / timestamped object annotations | 152 / 25,250 |

There are 201 annotation timestamps. One endpoint, containing 15 object records,
has no source synchronization anchor and is retained with an explicit flag.
Source-selected camera capture times differ from association anchors by up to
45 ms. Replay must define decision time, observation age and availability rather
than silently exposing measurements captured after the decision.

RGB images are JPEG 1920 x 1080; thermal images are 8-bit grayscale JPEG 640 x
480, without an inferred temperature conversion. LiDAR NPZ files preserve
`x`, `y`, `z`, `intensity` and per-point `time_offset_ms`. RGB vehicle views and
roadside thermal views have different viewpoints; calibration does not make
them pixel-aligned pairs.

The experimental adapter exports six JSONL/Parquet tables: `observations`,
`assets`, `streams`, `associations`, `annotations`, `geometry`. Native files are
referenced rather than copied; UTC nanoseconds remain integers. This adapter
spike is not the final cross-dataset v2 schema.

Camera rectification matched SDK 1.0.1 pixel-for-pixel on one image from each of
18 cameras. All catalog fingerprints, asset existence, observation/association
links and timestamp precision were checked. Geometry roundtrip checks establish
matrix consistency, not independent physical calibration accuracy. Image and
point-cloud previews show source data and ground truth, not learned predictions.

See [UrbanIng import and inspection](URBANING.md) and the separate
[CoBEVT stage 1 adapter](URBANING_STAGE1.md). A diagnostic real-data CPU result is
available; full held-out evaluation and online replay are pending. No general simulator agent assignment has been
performed for this dataset; the model adapter follows the official three-source
vehicle/site grouping only.

## PST900: implemented earlier research, retained separately

The implemented neural task is five-class RGB/thermal semantic segmentation.
Original PSTNet RGB/fusion computations, preprocessing, inference and global IoU
evaluation have numerical parity tests against attributed upstream reference
code. Random-weight parity is not a reproduction of trained benchmark accuracy.

An own RGB pilot completed with 48 training frames, 24 validation frames and
five epochs. Validation mIoU was **31.21%**, versus **19.24%** for background-only
prediction. Segmentation remains weak; hand-drill IoU is zero. Keep this small
pilot separate from published results and from earlier whole-frame Survivor
presence experiments.

Own PSTNet fusion training and acquisition experiments are pending. The original
authors' checkpoint links were unavailable when checked on 2026-10-17; do not
silently use random or unrelated weights. Existing code for an offline Ridge
acquisition gate predicts expected task-quality gain from locally available RGB
features, including entropy, margins and prediction statistics. Ground-truth
counterfactual gains are offline targets, not runtime policy inputs.

Training, validation, acquisition learning and final testing must remain
separate. Keep related recordings together, and account for the fact that the
older presence test subset was inspected during development. See
[PSTNet experiment status](PSTNET_EXPERIMENTS.md),
[PSTNet guide](PSTNET_REPRODUCTION.md) and
[presence baseline](PRESENCE_BASELINE.md).

## Repository and machine handoff

The user confirmed active Ares access on 2026-10-29. A recording-level protocol
and resumable subprocess driver are prepared with a CPU Slurm wrapper; see
[Ares experiment setup](URBANING_ARES.md). Two training recordings, one validation
recording and one crossing3 test recording are predeclared, up to 200 frames
each. Policy fitting is frozen before collecting test predictions. The wrapper
requests 8 CPUs, 24 GB RAM and 12 hours (maximum allocation 96 CPU-hours).
No job has been submitted: this session has no authenticated SSH configuration,
and the grant allocation/environment paths are not known. Dataverse currently
returns HTTP 403 here; connectivity from Ares has not been checked. Do not infer
that active cluster access means a runnable runtime or accessible source data.

Private GitHub repository: `https://github.com/janraj00/phdsim`.
The initial published commit is `f7323c22e953042cfc2d735c0027aa6e7b831ec2` on
`master`; this handoff is a subsequent documentation change. README and maintained
guides are in English. The user usually discusses the project in Polish and
prefers concrete, step-by-step explanations of data and decision flow.

The full suite passed **70 tests**, including on a fresh clone fetched from the
private GitHub repository, using the source machine's Python environment. Setup
on a new machine still requires recreating that machine's environment.

External research root: `D:\Doktorat\Platforma`:

- `data/pst900/` and `data/urbaning-v2x/`: roughly 11.3 GB combined.
- `models/`: roughly 326 MB, including `pstnet_rgb_pilot_v1`,
  `pst900_resnet18_v1`, `pst900_learning_cnn_v1`.
- `cache/torch/`: the verified ImageNet initializer.
- Old checkout `runs/`: roughly 38 MB of reports, histories and previews.
- Old checkout archive ZIPs and selected `outputs/` workbook files are also local.

These files are Git-ignored and are not recovered by cloning. The checkout may
move; preserve or update configured external paths. PST900 manifests embed
absolute asset paths, while UrbanIng catalog asset keys are root-relative.
Follow [the migration guide](MIGRATION.md) before assuming data or weights exist.

## Suggested starting prompt after cloning

> Read AGENTS.md, docs/CONTEXT.md and docs/MIGRATION.md. Verify the available code,
> environment, datasets and checkpoints. Continue PHDSIM with the agreed
> multi-sensor agent model. First establish a working UrbanIng 3D detection/fusion
> reference, then compare acquisition strategies under communication costs.
> Preserve earlier PST900 results and clearly distinguish implemented components
> from plans and experiments that have actually run.

