# Cached spatial error inspection

Prepared on 2026-11-03; not yet run on real Ares recordings. This is the first
qualitative step toward the user's research objective: identify where Car1
lacks information and estimate which peer sensor could supply useful evidence
before acquiring its perception payload. RGB and thermal remain a later stage.

## What this export does

The default batch job reads the existing **200-frame validation recording**
`20241126_0004_crossing2_00` and its trace-bound pose sidecar. It requires no
new detector inference, policy fitting, dependency installation or downloads.
Crossing3 is rejected before loading predictions to keep method development
on training/validation recordings. Existing caches and models remain unchanged.

The existing independent reader verifies GT fingerprints, fallback consistency,
pose/trace bindings and baseline AP. A separate object-index trace repeats the
same greedy, confidence-ordered, same-class BEV IoU .5 matching and upstream
0--100m corner-radius filter. Its F1 must equal the verified cached evaluator
on every frame/action. GT identifiers are **frame-local array indices**, not
tracking IDs. Per-class F1 is undefined when both GT and predictions are empty;
no artificial empty-class reward is used.

Up to six distinct cases are selected only from frames where **both Car2 and
Infra are available**. The fixed selection order is:

1. A reference at the middle of the eligible chronological frames, independent
   of detection quality.
2. Maximum number of GT instances recovered by Car2 but missed by Car1 and the
   Infra variant.
3. The corresponding Infra-specific recoveries.
4. Instances recovered with both partners but missed by all three other variants.
5. Instances matched with Infra but lost after also adding Car2.
6. Car1-only's largest positive advantage over queried variants in F1 minus
   .05 per request.

All outcome-based selections use GT and are explicitly **qualitative examples,
not frequency estimates or deployable decisions**. Ranking ties use frame key;
selection enforces uniqueness and at least 10 row positions between cases.
A category with no positive candidate, or no candidate satisfying spacing,
is omitted with a recorded explanation. No example is invented or forced.
Object recovery need not imply higher overall F1: added false positives and
lost matches are shown too.

## Deliverables and interpretation

`urbaning-frame-inspection.zip` contains:

- `index.html`: a local viewer with counts and side-by-side figures.
- `manifest.json`: selection reasons, omitted categories, software/code identity,
  source hashes, detector identity and pose assumptions.
- `frame-summaries.jsonl`: exact object match traces and counts for all input
  frames and feasible actions; this is offline label/outcome data.
- Per case, `scene.png` and `zoom.png`: identical axes and GT across four input
  variants, full scene plus a 36m zoom around the first selected GT index.
- Per case, `local-evidence.json`: only Car1 boxes/scores/entropy, availability,
  native association metadata and assumed pre-query relative poses.
- Per case, `offline-outcomes.json` and the original hashed `predictions.npz`:
  GT, partner/fused predictions and their evaluation; these must not be used
  as pre-query model inputs.

Green outlines are correct predictions, orange outlines are false predictions,
red dashed outlines are missed GT, and grey dashed outlines are matched GT
references. Zoom labels V/H/2W/P identify class and confidence. The blue ring
identifies the focused GT object. Pose markers locate Car1, Car2 and the
**Infra site-origin proxy**, which is not an individual pole/sensor location.

These are plots of **cached detections and offline errors**. They are not raw
LiDAR coverage, calibrated uncertainty, occlusion or visibility maps. A missed
GT box cannot be exposed to Car1 at decision time. The next research question
is whether local evidence can predict where these errors occur and which peer
will help. Native associations are preserved, including the existing causal
timing limitations; an online observation transport is not demonstrated.

## Ares execution

Submit from a separate inspection worktree using the existing container wrapper:

```bash
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_frame_inspection.sbatch
```

Resources: 4 CPUs, 12 GB, one-hour limit. Actual runtime is unmeasured on Ares;
cache verification/matching dominates plotting. The existing CPU environment
must provide NumPy, PyYAML and Matplotlib (already in the stage-1 requirements).
Matplotlib is checked before cache processing; the batch job never changes the
shared venv. On failure, preserve outputs and select a fresh absolute directory
through `URBANING_INSPECTION_OUTPUT`.

Output:
`phdsim-work/phdsim/runs/urbaning-frame-inspection-001/urbaning-frame-inspection.zip`.
On the Mac:

```bash
mkdir -p ~/Documents/phdsim-results/urbaning-frame-inspection-001
scp plgrajczykjan@ares.cyfronet.pl:/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-frame-inspection-001/urbaning-frame-inspection.zip \
  ~/Documents/phdsim-results/urbaning-frame-inspection-001/
```

Attach that ZIP for analysis, or extract it locally and open `index.html`.
