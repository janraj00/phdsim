# ICAISC 2027: selective thermal acquisition experiment

Status: proposed study and implementation handoff, not completed results.  
Prepared: 2026-10-23.  
Repository baseline inspected: `09e2b0da5a9e7a8c77a57dd0fb9f5face65af47a`.

## 1. Paper objective and scope

Working title: **Predicting the Value of Thermal Observations for Budgeted RGB-T Semantic Segmentation**.

Research question: can a model using only the available RGB observation and its prediction identify thermal observations that improve segmentation more effectively than RGB uncertainty alone, at an equal acquisition budget?

Use PST900, five-class semantic segmentation, and paired RGB-to-thermal requests. An acquisition delivers an existing registered thermal observation of the same scene. Keep the perception models fixed while comparing acquisition policies.

The proposed contribution is an empirical comparison of predicted task gain and uncertainty-based acquisition under a controlled information-access protocol. Novelty must be established against existing acquisition and dynamic modality-selection methods before making a novelty claim. Existing fusion architecture and a Ridge regressor alone are not a novel contribution.

This small study does not require movement, a new fusion architecture, physical network simulation, UrbanIng 3D detection, federated learning, or a general multi-sensor allocator. Those remain separate research directions. A paired thermal provider is not evidence of decentralized multi-agent coordination.

## 2. Verified starting point and required work

The own RGB pilot used 48 training frames, 24 validation frames and five epochs: validation global mIoU 31.21%, versus 19.24% for background-only prediction. This is diagnostic; hand-drill IoU was zero.

| Component | Verified state | Work for this study |
| --- | --- | --- |
| RGB model and trainer | Implemented; small own pilot completed | Train a stronger baseline on the existing vision-training pool |
| Original RGB-T fusion | Architecture and inference implemented | Implement an explicit fusion trainer and train own weights |
| Acquisition features and Ridge gate | Implemented | Restrict gate supervision to the acquisition holdout |
| Comparison pipeline | Implemented for original pretrained experts | Adapt provenance, data roles, budget controls and reporting to own training |
| Selective replay | Implemented | Execute with the selected own checkpoints and measure actual selective execution |

The current CLI exposes `train-rgb` but no `train-fusion`. The comparison currently sends every original `train` row to gate fitting; that is unsuitable for the own-training separation below. Configurations also still point at the unavailable authors' checkpoint locations.

Published benchmark numbers are references, not targets already reproduced by this repository. Do not use random weights or unrelated checkpoints as substitutes.

## 3. Data roles and frozen models

Preserve the existing recording-family allocation:

| Role | Existing pool | Permitted use |
| --- | --- | --- |
| Vision training | 273 original-training frames | Fit RGB and fusion weights |
| Vision validation | 130 frames from `bag1`, `bag7`, `bag11` | Select perception checkpoints and training settings |
| Acquisition learning | 194 frames from `bag4`, `bag5`, `bag6`, `bag8`, `bag12`, `bag17` | Generate gain targets and select/finally fit the gate |
| Official test | 288 frames | Final reporting after the protocol and models are frozen |

Verify these counts and identities against the actual manifest before execution. Keep suffix variants of a recording in one family. Check recording overlap across all roles; an official split does not by itself establish independence.

The historical presence study inspected part of the official test set. Before inspecting segmentation results, recover and record those frame IDs. Use the identifiable, previously uninspected remainder for the primary confirmatory comparison; report all 288 frames separately as the official-split descriptive result. Report the exclusion list and class/group coverage. If earlier exposure cannot be reconstructed or recording overlap prevents independence, describe the evaluation as exploratory and resolve an independent evaluation before claiming confirmation.

Train RGB on its permitted pool and select its checkpoint using vision validation. Train the original fusion stream with that RGB network, including its batch-normalization statistics, frozen. Choose fusion settings and checkpoint on vision validation. Then freeze both models for all acquisition experiments. Verify the fusion bundle contains exactly the same RGB checkpoint as the RGB-only baseline.

Plan three complete RGB/fusion training seeds, with identical data roles and the same acquisition comparisons for each pair. Preserve the pilot and previous checkpoints. If compute prevents completion, report the reduced number explicitly; repeated random masks do not count as independent perception-training runs.

## 4. Supervision and acquisition variants

On acquisition-learning recordings only, compute both frozen predictions and an offline gain target:

`g_i = frame_mIoU(fusion_i) - frame_mIoU(RGB_i)`.

Retain negative and zero gains. Keep the current documented convention for absent classes, and state that this per-frame target is a learning surrogate, distinct from global mIoU.

Use the existing 19 RGB-only features and Ridge implementation. Select regularization by leave-one-recording-family-out evaluation within the six acquisition families; fit the final gate on all six after selection. No perception tuning is allowed on these recordings. Ground-truth masks and unrequested thermal pixels are forbidden runtime inputs.

| Variant | Decision |
| --- | --- |
| No acquisition | Return RGB predictions for every frame |
| Always acquire | Return fusion predictions for every frame |
| Random acquisition | Select the same number of thermal observations at random |
| Uncertainty | Select highest normalized mean RGB entropy |
| Learned gain | Select highest gain predicted from RGB-only features |
| Entropy-only learned gate | Same Ridge procedure, using only mean entropy; feature ablation |

Predeclare budget fractions `0.25, 0.50, 0.75`; the primary comparison is `0.50`. For a strict equal-budget comparison, first run RGB on a known evaluation batch, compute each policy's scores, and request the top `floor(q * N)` thermal observations. Random uses exactly the same count. Break score ties deterministically using frame IDs. Use random seeds 0 through 19 and report their distribution.

This is an **offline batch acquisition protocol**, not a causal streaming or decentralized deployment claim. Ranking may use RGB scores from the known batch, but never test masks or thermal outcomes. Keep this distinction explicit in the paper.

Separately exercise the existing pointwise threshold gate in selective replay: choose thresholds from acquisition-family out-of-fold predictions, freeze them before test, and report achieved request rates. Do not force a test request rate by adjusting thresholds after seeing test outcomes. Batch-ranking and pointwise-threshold results must have distinct labels.

## 5. Quality, resources and Utility

For the selected output mask of each frame, accumulate one pixel confusion matrix over the evaluation set. Compute each class IoU from that matrix, then average the five class IoUs for global mIoU. Do not average frame mIoUs and label the result global mIoU.

Report:

- Global five-class mIoU, foreground-only mean IoU, and each class IoU.
- Thermal pulls and request fraction `q`.
- Actual delivered PNG bytes; these are payload bytes, not measured network traffic.
- End-to-end latency and the feature/gate and thermal/fusion components, including median and p95.
- All hardware, software, threading, batch size and timing settings.

Use primary normalized acquisition Utility:

`U_lambda = Q - lambda * q`,

where `Q` is global mIoU on [0, 1]. Freeze the sensitivity grid `lambda = {0, 0.001, 0.005, 0.01, 0.02}` before test. These are declared quality penalties, not measured energy or monetary costs. Show the complete grid rather than choosing a winning test setting.

For computation sensitivity, additionally report:

`U_full = Q - lambda * q - mu * (C_gate + C_extra)`.

Normalize both time terms by mean RGB-only inference time on a separate profiling subset. `C_gate` includes incremental RGB feature extraction and the policy decision; `C_extra` includes selected thermal loading/preprocessing and additional fusion inference. Common RGB work is excluded from the incremental penalty. Use the predeclared sensitivity grid `mu = {0, 0.005, 0.01}`; these are scenario weights.

Required **no prediction-cost ablation**:

`U_no_gate_cost = Q - lambda * q - mu * C_extra`.

Evaluate the same frozen choices and measured predictions, setting only the gate-cost term to zero. Keep acquisition and extra fusion costs. Report measured gate latency even in this ablation. If policies are reoptimized under a different cost model, label that as a separate experiment.

Offline counterfactual caching is for fitting and quality comparisons. It cannot establish deployment latency savings. For timing, execute real selective replay, reuse the RGB output, and verify that declined thermal assets are not opened. Use warm-up and device synchronization where needed; exclude training and teacher caching from runtime measurements. Network transport, energy, and flight costs are not measured here.

## 6. Success criterion and evidence

Predeclare one primary success criterion:

> At a 50% thermal-acquisition budget, learned gain has higher global mIoU than both entropy ranking and mean matched-count random acquisition, with the lower bound of a paired 95% recording-family bootstrap interval above zero for each difference.

Aggregate complete training seeds with equal weight, and use a hierarchical paired bootstrap over training runs and test recording families; recompute global confusion-based mIoU for each resample. Use 2,000 resamples and record the bootstrap seed. Both comparisons must pass; secondary budgets cannot rescue a failed primary test. Report the number of independent test recordings and the limits of intervals when this number is small.

Always report full-fusion and RGB-only endpoints, including negative results. A gate that saves requests by discarding useful thermal information has not automatically succeeded. Any claim about retaining a fraction of the full-fusion gain requires a positive, credibly estimated full-fusion gain.

The criterion is a proposed study decision, not an ICAISC acceptance rule. A failed criterion is still a result, but does not support the planned superiority claim.

## 7. Deliverables and implementation order

1. Add a study configuration with explicit frame roles, recording groups, training seeds, budgets, random seeds, Utility weights and output paths.
2. Implement a fusion-training entry point with frozen RGB and provenance/checkpoint validation. Expand RGB training beyond the pilot configuration.
3. Adapt teacher collection and gate fitting to the acquisition-only holdout. Remove assumptions that own checkpoints are original author checkpoints.
4. Add equal-budget batch controls, the entropy-only feature ablation, uncertainty intervals and Utility reporting.
5. Execute true selective replay and retain per-component timing and information-access traces.
6. Produce one main results table; a quality-versus-request-rate plot; a Utility sensitivity figure; feature/gate-cost ablation tables; and fixed qualitative examples of helpful, unnecessary, harmful and wrongly requested thermal observations.
7. Write the full paper with related work, methods, protocol, results, limitations and reproducibility details.

Record commit, environment lock/export, dataset and split fingerprints, checkpoint SHA256 values, selected epochs, configs, all seeds, machine details and exclusions. Preserve per-frame scores, choices, confusion matrices and result-generation commands. Put datasets, weights and generated runs outside Git; commit only code, configs and maintained documentation.

Meaningful checks should cover group isolation, gate-fit input roles, frozen RGB weights/statistics, no thermal access after declining, budget counts and global-IoU aggregation. A documentation-only plan does not require retraining or rerunning the full suite.

## 8. Schedule and submission

| Date | Intended milestone |
| --- | --- |
| 23-30 October 2026 | Audit data roles and prior test exposure; train RGB/fusion; check acquisition potential on validation |
| 31 October-5 November | Freeze protocol; fit gate; finish baselines and focused related-work comparison |
| 6-9 November | Execute final evaluation, repetitions, intervals and replay measurements |
| 10-13 November | Complete manuscript and supervisor review |
| 14 November | Anonymization, formatting, source-package and submission checks |
| 15 November | Published submission deadline; verify current CFP and cutoff timezone before relying on it |

Go/no-go checkpoint on 30 October: assess whether the working fusion model and variation in thermal benefit provide enough evidence to justify continuing toward this deadline. If training or provenance is unresolved, record that limitation and reconsider the deadline rather than substituting pilot scores for completed experiments.

ICAISC currently requests full papers, preferably around 12 pages, with double-blind review and Springer proceedings formatting. Source: [official ICAISC website](https://icaisc.eu/), checked 2026-10-23. Recheck detailed instructions before submission.

Later conferences remain separate opportunities, not automatic destinations for the same manuscript:

| Venue | Published full-paper deadline | Preparation reminder |
| --- | --- | --- |
| [FUSION 2027](https://www.fusion2027.org/call-for-papers) | 14 February 2027 | 4 January 2027 |
| [IROS 2027](https://www.ieee-ras.org/event/2027-ieee-rsj-international-conference-on-intelligent-robots-and-systems-iros-70525/) | 1 March 2027 in IEEE RAS calendar | 18 January 2027 |
| [ECAI 2027](https://ecai2027.org/) | 14 April 2027 | 1 March 2027 |

Conference dates and deadlines are a snapshot checked on 2026-10-23. Verify the latest CFP, any abstract deadline and submission timezone. Reminders are preparation prompts, not submission authorization.

## 9. Handoff to the implementation agent

Read `AGENTS.md`, `docs/CONTEXT.md`, `docs/EXPERIMENTS.md` and `docs/PSTNET_REPRODUCTION.md`. Treat this document as a proposed ICAISC study plan. First verify the machine, dataset, manifest and checkpoint availability; cloning does not restore ignored data or weights. Implement the missing fusion trainer and acquisition-only data roles while preserving the existing pilot and UrbanIng work. Follow the study stages above, record deviations, and distinguish implemented code, executed experiments and reference benchmark values in every report.
