# Descriptive diagnostics after full frozen-policy replay

Prepared 2026-11-02; not executed in this environment. This separate read-only
analysis uses the completed full-policy report, per-frame caches, pose sidecars
and existing frozen gain models. It never trains, tunes or runs the detector.

## Questions and outputs

1. Separate **whether to query** from **whom to query**. Partition frames into
   no partners, Car2 only, Infra only and both. For each nonempty stratum report
   all saved policies, both AP modes, F1, Utility, request/action histograms and
   explicitly nondeployable hindsight F1-utility reference.
2. Report paired marginal F1 changes: Car2 over ego, Infra over ego, Car2 given
   Infra, Infra given Car2, and both over ego. Use only frames where both endpoint
   actions are feasible. Save mean/median/quantiles, positive/negative fractions
   and the fraction exceeding the existing cost (.05 per additional request).
   Joint synergy is recorded separately and not assumed additive.
3. Quantify head prediction errors on feasible actions: MAE, RMSE, signed bias,
   Pearson correlation (null for constant inputs), predicted/observed gain
   distributions, actual utility regret against the GT-assisted selector and
   choices with worse utility than ego. Export ten largest regret examples for
   inspection. GT stays in offline diagnostics, never the deployed selector.
4. Report results by **original recording**, grouping `_08`/`_09` segments sharing
   a date/recording identifier. Do not treat neighboring frames or segments as
   independent replicates. Recompute aggregate AP from predictions/statistics,
   never average per-sequence APs.

Conditional schedule-/budget-matched random controls use the frozen seeds 0–99
and are regenerated **within each availability stratum**. Their exact request
budget and histogram match that stratum's learned policy. These controls answer a
conditional question and differ from slicing whole-test random assignments.
Randomization spread is not a confidence interval over independent recordings.
Per-recording tables omit additional random replays; full and conditional random
controls are already available.

Before slicing, both AP modes, F1, requests and Utility must reproduce the saved
full report. Fresh predictions from the frozen model must reproduce its saved
choices. Full inventory and cache identities are checked through the frozen plan,
completed markers, trace/pose hashes and the existing cache reader. Existing
models/reports/caches remain unchanged. No costs or thresholds are selected here.
This is post-hoc diagnosis on a partly inspected crossing3 test, not a new test
confirming hypotheses generated from these outputs.

## Ares

From a separate diagnostics checkout:

```bash
sbatch -A plgkgacq-cpu --dependency=afterok:21564342 \
  scripts/slurm/urbaning_diagnostics.sbatch
```

Job 21564342 is the existing full-policy collector. The dependency prevents
analysis of incomplete inputs. If that job fails, fix the full replay/collection
first; do not remove the checks to produce partial diagnostics presented as full.
This diagnostic job requests 4 CPUs, 24 GB, at most 4 hours (not an estimated
runtime). Partial output is not silently overwritten on retry.

Outputs in the existing full-policy result root:

- `diagnostics-report.json`: compact conditional and per-recording diagnostics.
- `urbaning-analysis.zip`: full-policy and diagnostic reports together. ZIP is the
  attachment format verified to work in this conversation.

Download after successful completion:

```bash
mkdir -p ~/Documents/phdsim-results/urbaning-full-policies-001
scp 'plgrajczykjan@ares.cyfronet.pl:/net/pr2/projects/plgrid/plggkgteam/plgrajczykjan/phdsim-work/phdsim/runs/urbaning-full-policies-001/urbaning-analysis.zip' \
  ~/Documents/phdsim-results/urbaning-full-policies-001/
```
