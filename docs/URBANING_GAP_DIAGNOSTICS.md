# Descriptive information-gap diagnostics

Updated 2026-11-04. No fitting or detector inference. Primary policy evaluation
remains global-sort, four-class BEV mAP@.5 on 1400 crossing3 frame records. The
object/region diagnostics below use a separate **200-frame validation recording**
`20241126_0004_crossing2_00`, not those 1400 test records. Both sets were previously
inspected. Counts are object appearances in frames, not unique tracked objects
or independent examples.

## Complete comparable policy table

Savings are measured against 2033 ALWAYS requests; AP loss is ALWAYS AP minus
policy AP, in percentage points. AP gain is relative to Car1. Random rows are
means over seeds 0–99. The historical always-one-peer random was additionally
replayed offline on 2026-11-04, using unchanged `choose_one_peer` and the existing
full portable statistics. No probability, threshold or model was selected.

| Policy | mAP@.5 (%) | Requests | Requests saved | Saving (%) | AP gain vs Car1 (pp) | AP loss vs ALWAYS (pp) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Car1 / NO | 23.9064 | 0 | 2033 | 100.00 | 0 | 9.8038 |
| Car1 + available Car2 | 27.3463 | 766 | 1267 | 62.32 | 3.4399 | 6.3638 |
| Car1 + available Infra | 31.7422 | 1267 | 766 | 37.68 | 7.8358 | 1.9680 |
| Random one available peer | 31.7038 | 1311 | 722 | 35.51 | 7.7974 | 2.0063 |
| Independent random p=.5 | 28.9725 | 1016.32 | 1016.68 | 50.01 | 5.0661 | 4.7377 |
| Independent random p=.75 | 31.4119 | 1523.43 | 509.57 | 25.06 | 7.5055 | 2.2983 |
| Independent random p=.9 | 32.8147 | 1829.68 | 203.32 | 10.00 | 8.9083 | .8955 |
| Entropy subsets .5/.7 | 33.7102 | 2033 | 0 | 0 | 9.8038 | 0 |
| GainEgo | 33.1274 | 1838 | 195 | 9.59 | 9.2210 | .5828 |
| GainGeometry | 32.2393 | 1533 | 500 | 24.59 | 8.3329 | 1.4709 |
| Regional frozen prototype | 32.3282 | 1401 | 632 | 31.09 | 8.4218 | 1.3819 |
| Tree frozen prototype | 32.5766 | 1488 | 545 | 26.81 | 8.6702 | 1.1335 |
| ALWAYS | 33.7102 | 2033 | 0 | 0 | 9.8038 | 0 |

Entropy-subset choices reproduce ALWAYS exactly on this inventory. Its original
full-report metrics were reproduced from portable statistics. Original frozen
NumPy 1.26.4 was retained: confidence ties must preserve metric ordering/parity.
The earlier one-peer entropy gate and separately fitted tree-pilot ridge do not
have a distinct full-1400 result; smaller development results must not be mixed
into this table. Conditional budget/schedule random controls remain separate
from independent deployable baselines; see the full replay report.

## Operational definition and source validation

A candidate recoverable gap is a GT object missed by Car1 at BEV IoU .5 but
matched after including an available peer subset. This is an offline label,
not an input to the acquisition policy. It does **not** establish physical
occlusion or prove why the detector failed. Classification/localization errors
also count. Recovering GT alone is not AP improvement: added false positives
and lost previous detections must also be measured.

The regional dataset's verified inputs/targets and 200 frame inspection audits
share the exact run/trace/prediction/GT/pose provenance. Every frame's FN total
and recovered-GT counts were reconciled against the object-index audit. The
regional manifest SHA256 is
`7a8a9ee18002968befd43b3d15778401625faea92f72850f1b23e28a6655e85c`.
All grid summaries use fixed 10m cells and distinguish unavailable peer masks.

## Observed characteristics on validation

- Eligible GT appearances: **14937**. Car1 misses **8086**. At least one feasible
  partner configuration recovers **4283 (52.97%)**; none recovers **3803 (47.03%)**.
  The union is deduplicated by frame-local GT index across the configurations.
- **4094 / 8086 (50.63%)** misses fall in cells containing no cached Car1
  detection. Thus a query rule restricted to existing low-score boxes omits
  roughly half of the misses in this recording. Empty detection cells do not
  distinguish empty, observed or unobserved space; about 89% of spatial cells
  have no Car1 detection. The 97.08% miss rate for GT appearing in empty cells
  is conditional on offline GT presence, not a runtime risk estimate.
- Car2 recovers **474/743 (63.80%)** of Car1 misses in cells 0–20m from Car2;
  **1148/2301 (49.89%)** at 20–40m; **421/1491 (28.24%)** at 40–60m;
  **97/1062 (9.13%)** at 60–80m; **86/2489 (3.46%)** beyond 80m. Distances
  refer to cell centers, not exact object positions. This association has not
  controlled for class, distance to Car1, scene/time or visibility.
- On the **same 134 both-available frames**, Car1 misses 5720 GT appearances.
  Car2 recovers 1350; Infra 2784; both 3184. Car2 recovers **477** missed objects
  that the Infra variant does not recover. **146** are recovered by the joint
  variant but neither single-peer variant. Adding Car2 to Infra also loses
  **235** previous Infra matches. These are overlapping sets, not additive
  counts of unique scene objects.
- Class-specific recoverability varies strongly. Among eligible misses, Car2
  recovers 34.72% for Vehicle versus 6.28% for Pedestrian. Infra recovers 62.30%
  and 12.03%; joint recovers 69.75% and 14.28%, respectively. Availability masks
  differ between Car2 and Infra denominators; only the matched 134-frame subset
  supports direct same-frame source comparison.

## Next diagnostic, not yet completed

1. Build a per-region gap label and a separate per-source recoverability label,
   retaining no-gap, recoverable, unrecoverable and harmful-query cases.
2. Cross-tab or model Car2 distance jointly with Car1 distance, class and local
   score/empty-cell evidence; report support and original recording identity.
   This checks whether the distance association survives measured confounders.
3. Evaluate geometry-only, local-evidence-only and interaction models on
   separate development recordings before freezing a protocol for new footage.
   GT/peer predictions supply offline targets only. The current linear pooled
   regional model must not be presented as solving spatial gap localization.
4. For physical explanations, inspect original LiDAR density/visibility and
   object geometry. The existing detection summaries cannot establish whether
   an empty region is truly unobserved or why Car1 failed.
