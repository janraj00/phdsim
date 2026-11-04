# Frozen spatial scores to whole-frame acquisition — Ares validation replay

Status: **prepared and smoke-tested, not a completed experiment** (2026-11-04).
The user requested moving computation to Ares after the cloud conversation
was interrupted. No job has been submitted from this session. This is the
200-frame crossing2 development validation, not the 1400-frame crossing3 replay.

## Fixed experiment

The three original ExtraTrees model profiles remain unchanged: geometry,
local Car1 evidence and their combination. Their existing validation predictions
are bound to the original detector, frame keys, payloads and frozen model hashes.
No training, detector inference, crossing3 access, installs or shared venv changes.

For each frame, compare two aggregation rules:

1. Select ten cells from all 400 by predicted Car1-gap score, and sum each
   feasible subset head's predicted signed FP+FN reduction over those same cells.
2. Sum over all 400 cells, as a pooling comparison.

Subtract the fixed cost per **actually requested peer**, once per whole frame.
Choose exactly one feasible action: Car1 alone, Car1+Car2, Car1+Infra, or all.
The joint head is supervised separately; it is not a sum of singleton heads.
There is no mixing detector boxes from different actions by cell and no region
transmission. Zero predicted gain is assigned to Car1 alone; ties favor fewer
requests, then the canonical action order.

Cost grid: **0, .25, .5, 1, 2, 4, 8, 16, 32, 64** predicted error-count units.
For each profile and aggregation, select maximum validation global-sort
four-class BEV mAP@.5 under each request cap: **.5, 1, 1.5 per frame**
(100/200/300 total on these frames). Ties favor fewer requests then grid order.
An unattainable cap is reported explicitly, not silently replaced. There is
no cross-profile winner selection. Save the protocol before candidate AP and
save deployable configurations/model bytes before random comparisons.

This selects costs on an already-inspected validation recording. It is
development evidence, not independent generalization. Learned gap/benefit
scores are policy inputs; GT and counterfactual detection outcomes remain
offline evaluation data. A cell without a Car1 detection is not an established
occluded/unobserved region. Infra positions retain the site-origin proxy caveat.

## Comparisons and reports

- Four canonical fixed baselines, with explicit unavailable-peer fallback.
- Infra when available, otherwise Car2; and the reversed priority.
- **Main random baseline:** independently ask each available peer with fixed
  p=.25/.5/.75/.9, seeds 0–99. Both/one/none are all possible.
- Secondary retrospective control: uniformly sample the same total number of
  feasible frame/peer queries without replacement, seeds 0–99. It receives only
  the scalar query count, never the model's timing or per-frame action histogram.
  This exact-total control is offline, not a claimed deployable method.

Primary measure: global-confidence-sort BEV mAP@.5, with requests, savings and
mAP loss versus ALWAYS. Both AP ordering modes and class AP are retained.
Default-order AP is separate; F1/old F1 utility are diagnostics and never select
costs here. Seed variation describes randomization on this recording, not
recording-level uncertainty. Requests do not measure bytes/latency.

Outputs: `protocol.json`, `report.json`, `selected-frozen-policies.json`,
`frozen-gap-acquisition-inputs.zip`, `WYNIKI_PL.md`, `files.json`, and the final
`urbaning-gap-acquisition-validation.zip`. The latter contains the deployable
frozen packet as well as results. No result or saving is established until
the real job completes.

## Input packet

`urbaning-gap-acquisition-inputs-001.zip`, **13,257,571 bytes**, SHA256:

```
c1e72f33bdbd61edab2773bac81d2f582b88ed4d625e9743c35ac194d8bb50ee
```

It embeds the original pilot ZIP, regional dataset ZIP and portable AP export
with individual hashes. Train frames are included only for source/baseline
verification; no refitting occurs. Staging verifies the outer SHA, exact members,
inner hashes, CRC, safe paths and size limit. Replay verifies frozen pilot files,
original baseline AP in both modes, detector/frame/payload/availability bindings.
The existing CPU container needs NumPy **1.26.4**, which preserves confidence-tie
AP parity. This runner does not need scikit-learn, Torch or Open3D.

## Submit on Ares

Download the input packet on the Mac, then use the file picker rather than an
assumed Downloads path:

```bash
ssh plgrajczykjan@ares.cyfronet.pl 'mkdir -p /net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/inputs'
if URBANING_ZIP=$(osascript -e 'POSIX path of (choose file with prompt "Wybierz urbaning-gap-acquisition-inputs-001.zip")'); then
  scp "$URBANING_ZIP" plgrajczykjan@ares.cyfronet.pl:/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/inputs/
fi
```

Use a fresh worktree at the reviewed gap-acquisition commit, then submit from
its root (fetching only does not update an existing worktree):

```bash
git fetch origin codex/urbaning-gap-acquisition
git worktree add --detach ../phdsim-gap-acquisition FETCH_HEAD
cd ../phdsim-gap-acquisition
sbatch -A plgkgacq-cpu scripts/slurm/urbaning_gap_acquisition.sbatch \
  /net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/inputs/urbaning-gap-acquisition-inputs-001.zip \
  c1e72f33bdbd61edab2773bac81d2f582b88ed4d625e9743c35ac194d8bb50ee
```

The worker requests 4 CPUs / 12 GB / a 2-hour upper limit, not an estimated
duration. It uses the established `bin/urbaning-python.sh` worker wrapper.
Actual runtime has not been measured. Look for `REPLAYED`, `PURE RANDOM`,
`RANDOM n/100 seeds`, then final `DONE` and output SHA. This is cached AP replay,
not the previous multi-hour detector pass.

## Resume after interruption

Each distinct action list is checkpointed atomically, including each random
seed. A checkpoint binds the exact protocol, implementation hashes, input
hashes and action list; it also checks its stored metric hash. An output lock
rejects simultaneous workers using the same directory. A changed input/code/
protocol refuses resumption. Final archives are replaced atomically.

After the previous job stops, pass its **same output directory** as the third
argument to the same `sbatch` command. The directory is printed as `OUTPUT:`
and defaults to `.../phdsim/runs/urbaning-gap-acquisition-JOBID`. Reusing only
the same ZIP with no output argument starts a fresh directory. Old run outputs,
raw caches, model files and shared environments are preserved.

## Verification before submission

Five focused tests cover whole-frame selection, explicit joint benefit,
unavailable heads, independent fixed-total random support, checkpoint protocol/
action binding and tamper detection, verified staging/resumption and path
traversal rejection. Bash syntax passed. A real-input smoke test verified
train/validation baseline AP in both orders, all 200 validation payload/frame
bindings, one real action list's AP and checkpoint reuse. It did not perform
the full cost-grid/random experiment or select final policies.
