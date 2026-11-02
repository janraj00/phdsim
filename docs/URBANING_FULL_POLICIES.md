# Full-test evaluation of frozen acquisition policies

Prepared on 2026-11-02; not yet executed. The completed CoBEVT reference covers
seven crossing3 sequences / 1400 frames. Its default-order mAP@.5 was 24.8134%,
versus 24.8563% in the released checkpoint report. Global-sort mAP@.5 was
33.7102%; these ordering modes must not be mixed in comparisons.

## Frozen protocol

- Read the exact completed benchmark inventory and per-sequence converted data.
  Do not download, extract or convert again.
- Car1=100000, Car2=200000, Infra=bundled roadside site. Save all four source-subset
  outcomes on every frame using the verified frozen detector and existing paired
  runner. All actions share the same all-source GT.
- Keep existing `urbaning-joint-gain-001/joint-gain.json` (Gain–Ego) and
  `urbaning-geometry-001/geometry-gain.json` (Gain–Geometry). Freeze their hashes
  before launching inference. Do not fit models, costs or thresholds on crossing3.
- Replay NO, Car2, Infra, ALWAYS, entropy subsets, frozen learned policies,
  independent Bernoulli random subsets, and schedule-/budget-matched random
  controls with predeclared seeds 0–99. The privileged hindsight F1 selector stays
  separately labeled as nondeployable.
- For both learned policies report both AP ordering modes on identical choices,
  plus mean frame F1, requests and Utility at the existing .05 cost per request.
  Changing AP ordering must not change choices, F1, cost or random budgets.
- Use globally aggregated statistics across the full test inventory, never the
  mean of individual sequence AP. Save deltas of all-source AP relative to the
  completed benchmark as a consistency diagnostic (point shuffling / different
  retrieval paths can lead to small changes).
- Geometry sidecars expose pose-only metadata and ego detection features. Infra
  position is a site-coordinate origin proxy, not a physical pole location.
- This is expanded evaluation of already developed pilot policies. One crossing3
  sequence and full all-source reference have already been inspected; it is not
  a new pristine test of later method/parameter changes. Related segments of a
  recording remain grouped; the frozen policies were fitted outside crossing3.
- Request counts are bundle-cost proxies; no network or online causal availability
  measurements are implied by cached replay.

## Execution on Ares

From the separate `phdsim-full-policies` checkout, run:

```bash
bash scripts/slurm/submit_urbaning_full_policies.sh
```

The login process loads Python and uses only the standard library to freeze the
plan. The array runs at most two sequences simultaneously (4 CPUs/12 GB/24-hour
limit each); inputs are read-only and outputs are separate per sequence. An
`afterok` collector uses 4 CPUs/24 GB/4-hour limit. Limits are not runtime estimates.
Completed stage1 caches are reused only after coverage/model checks; completed
markers additionally bind run/trace/pose hashes. The cache loader validates box
payloads, GT fingerprints and numerical parity with original fixed baselines.
Partial inference directories are preserved and rejected; inspect and rename the
failed sequence's partial `run` directory before resubmitting its index. Do not
rerun submission while a prior array writes to the same output paths.

The new output root is `../phdsim/runs/urbaning-full-policies-001`. Source conversion,
benchmark reports, original pilot models and historical outputs are not modified.
Once all array tasks succeed, the collector writes `full-policy-report.json`.
If a task fails the afterok collector waits; fix/resubmit the failed index and
submit collect explicitly after all sequences succeed.

The current full reference saved statistics only, not per-frame box caches for
all subsets. This job necessarily runs new subset inference; it does not reuse
all-source AP statistics as a substitute for uncomputed partner outcomes.

Download to the agreed Mac directory:

```bash
mkdir -p ~/Documents/phdsim-results/urbaning-full-policies-001
scp 'plgrajczykjan@ares.cyfronet.pl:/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-full-policies-001/full-policy-report.json' \
  ~/Documents/phdsim-results/urbaning-full-policies-001/
```
