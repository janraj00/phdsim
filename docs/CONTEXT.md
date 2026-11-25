# PHDSIM research handoff

Updated for the **SCOUT branch: 2026-11-20**. Earlier explanations in the
[conversation archive](CHAT_HISTORY_2026-10-19.md) include superseded assumptions.

## Active SCOUT work

### Integrated semantic replay and viewer (2026-11-20)

After usage limits interrupted the four implementation chats, the user asked
to resume them and this chat. All four resumed and completed checks. This
chat integrated the terrain generator, RGB and LiDAR sensors, semantic
classifier and fixed sweep in `experiments/scout/semantic_mission.py`.
Two drones cover the plot and the rover takes two preplanned local captures.
RGB, LiDAR and fusion share the same mission trace. Runtime estimates are
updated only after a measurement completes. Offline evaluation uses truth.

The three held-out Earth-analogue missions are at `runs/scout-semantic-demo`.
The [viewer instructions](../apps/scout-viewer/README.md) produce an offline
HTML file with the elevation and semantic replays. 65 focused Python tests
and the offline replay logic checks passed. Browser access to the file URL
was blocked by the tool policy. Adaptive semantic acquisition and the link
budget remain separate work.

### Parallel semantic implementation (2026-11-20)

The user requested separate working chats and a local mission visualizer.
Four chats started with disjoint file scopes for terrain and sensors,
semantic fusion, fixed coverage planning and the viewer. See
[workstreams and data contracts](SCOUT_SEMANTIC_WORKSTREAMS.md). The coordinating
chat prepared `runs/scout-visualizer-demo/mission.json`, a checked replay of
elevation mission 2021, so the viewer can start before semantic integration.

### Semantic terrain experiment design (2026-11-20)

The user chose a semantic class map as the principal task, with configurable
classes and recognition models. [The semantic environment design](SCOUT_SEMANTIC_ENVIRONMENT.md)
assigns separate responsibilities to terrain generation, sensors, perception
and fusion, agents, coverage planning, acquisition and communication. The
first proposed benchmark isolates RGB and LiDAR fusion on matched poses in a
seeded Earth analogue. It then compares an optimized fixed sweep with adaptive
acquisition. Delayed delivery and actual serialized payload sizes follow on
the same scene. This is a design handoff. The current executable remains the
elevation benchmark.

### Completion rule comparison on matched elevation traces

Implemented and ran the replay in [SCOUT elevation mapping](SCOUT_ELEVATION.md#completion-rules-on-identical-measurement-traces).
Compare existing pointwise coverage with the mean probability of being within
height tolerance and a calibrated threshold on that mean. Each planner uses
one uninterrupted trace per seed. The original pointwise rule remains the
normal simulator stopping rule. The 5% calibration target concerns premature
declarations per mission, with a maximum score over all bad checkpoints and
a separate calibration split. It is not a conditional success guarantee.

On 200 held-out adaptive traces, the pointwise, expected and calibrated rules
verified 34, 95 and 84 declarations and made 1, 44 and 6 premature ones,
respectively. On the 32 adaptive traces verified by both pointwise and
calibrated rules, the latter stopped 4.53 ticks earlier on average. Fixed-plan
counts were 10/0, 75/39 and 65/8 (verified/premature). All 80 original trace
prefixes matched on the 40-pair replay. Output directories are
`runs/scout-elevation-stopping` and `runs/scout-elevation-stopping-pilot`.

### First elevation mapping benchmark (2026-11-19)

Implemented and ran [SCOUT elevation mapping](SCOUT_ELEVATION.md), with two
drones and one rover, a synthetic 32 × 32 elevation field, a coarse prior,
concurrent actions and an ideal shared map. The fixed schedule is built before
launch with the same greedy scorer that the adaptive policy reuses after
completed measurements. Both share their first assignments and budgets.
The synthetic aerial noise depends on standoff and a local imaging regime
revealed by measurement quality metadata. This fixture is independent of the
existing occupancy sensor. Controllers stop on estimated quality. Offline
evaluation checks the actual height error.

The default target is 85% surface within 25 cm, with a runtime pointwise
confidence threshold of 90%. Verified declarations were fixed 0/10 versus
adaptive 3/10 on seeds 42–51 and 2/40 versus 6/40 on seeds 100–139. Actual
end-of-run mean coverage in the repeat was 85.08% versus 85.64%. Outputs
are under `runs/scout-elevation-v0` and `runs/scout-elevation-repeat`.
52 focused tests passed. This comparison uses elevation alone, simplified
motion and immediate sharing. Its next scientific comparator is a simpler
adaptive policy under the same observations and budgets.

### Terrain reconstruction direction and business handoff (2026-11-19)

After reading the user-linked chat `01a1e9fd-4b09-7d53-9a5a-bff78a85b3d8`,
the user developed the large-area terrain-model/digital-twin direction and
requested a polished research description to paste into a business discussion.
See [terrain-model target](SCOUT_TERRAIN_MODEL.md) and the Polish copy-ready
`../../research/scout-terrain-model-2026-11-19/OPIS_BADAWCZY.md`.

The candidate main task is progressive construction/refinement of a terrain
model to declared quality and coverage, minimizing elapsed time subject to
energy and communication budgets. Multiple sensing agents remain core; the
proposed first Earth analogue has at least two drones and a ground peer.
Existing-data transfer and acquisition of new observations are both choices.
Preserve geometry/semantics/uncertainty/provenance, local information boundaries,
functional sensor quality and explicit unresolved states. Final map ownership,
completion procedure and numerical requirements still need design decisions.

The earlier sensor-family bound is an optional method candidate, not an
accepted replacement for the full system objective. No novelty of the whole
vision is claimed. Lunar use requires distinct mobility/energy models, e.g.
rovers/propulsive hoppers rather than Earth multirotors. Sources establish a
real mapping use case (USGS products, CADRE and planned MoonFall), not a
verified research gap. This turn produced documentation only; no new mission,
fleet coordination, sensor implementation or learned policy was added.

### Delivered limitations audit and finite diagnostic (2026-11-19)

The user explicitly requested the promised comparison of concrete method
limitations and one mechanism worth improving, then asked to continue.
Delivered `../../research/scout-method-comparison-2026-11-19/REPORT.md`:
primary-source method comparison, adversarial overlap checks, mathematical
scope, reference baselines and rejection criteria. Closest task-level anchors
are ASLaP-HR and the AIPPMS lineage, not only SAP. The recommended candidate is
a learned conservative sensor-family residual-error estimate for pruning
expensive acquisition evaluations with detailed-calculation fallback. This
is not confirmed novelty or an accepted replacement doctoral topic; Bayesian
acquisition, amortization and confidence-bound pruning already have predecessors.

Added an isolated standard-library Gaussian diagnostic in that research
directory. It separates observable U from a property component V inaccessible
to the aerial observation family; the local instrument measures U+V. A fixed
uncertainty-priority control spends6 abstract budget units without resolving
two regions; known conditional-gain selection resolves required regions with
cost5. Exact-floor pruning makes the same choices across360 factorial cases,
plus1000 correlated covariance checks. The serial example uses9 detailed gain
evaluations versus3 plus6 floor-bound evaluations: no runtime speedup or
learned-policy benefit is established. This is not a reproduction of a paper
or a physical/multi-agent concurrent mission. It uses no terrain truth or
future measurement values. JSON/CSV retain inputs and source provenance.

No production sensors, contracts, mission code or remote jobs changed. Approved
distance-dependent sensor behavior and the reconnaissance startup vision remain
separate from the abstract diagnostic. The new report explicitly prevents
claiming that every RGB viewpoint shares a permanent observability floor or
that marginal calibration guarantees correctness under adaptive selection.

### Follow-up check of the 2023 multi-UAV paper (2026-11-19)

The user asked whether its heterogeneous-team future work was subsequently
done. Found the later coauthor paper
[Oerlemans, Shi and Popović, 2026](https://arxiv.org/html/2606.12306v3).
This supplies an aerial–ground example, with a different author team; it does
not establish the proposed learned multimodal ground-measurement assignment.
The distinction and version dates are recorded in the startup vision's
`RECONNAISSANCE.md`. Do not treat a 2023 future-work statement as evidence of
an open gap in 2026. No code, contracts or experiments changed.

### Proposed mission variant: area reconnaissance, not payload delivery (2026-11-19)

The user proposed that drones explore an area, learn where further inspection
is unnecessary and where a rover should perform local measurements. Prepared
the working variant `RECONNAISSANCE.md` and `SCOUT_reconnaissance_vision.pdf`
under `../../research/scout-startup-vision-2026-11-20/`, preserving the earlier
delivery version. This is a target-vision variant, not implemented functionality
or evidence of novelty. Multiple drones remain central; information needs may
originate from drones as well as a rover. The rover is a mobile sensing peer,
not a mandatory payload carrier. Define mission questions, evidence quality
and coverage/review requirements; unknown regions must not be silently marked
irrelevant or resolved. Additional observation, another sensor, local rover
measurement and stopping further inspection are distinct choices.

The earlier `SCOUT_TARGET_MISSION.md` describes the prior delivery proposal;
it is not an irrevocable research scope. SAP is no longer the only relevant
comparison: learned multi-UAV informative planning and multimodal active science
are established adjacent work. No simulator, sensor or contracts changed here.

### Immediate need: defense / dual-use startup vision for tomorrow (2026-11-19)

The user corrected the first draft: multiple drones are core to the vision,
not a later optional extension. The revised first demonstrator specifies one
rover and at least two drones, independent offers and executor selection with
availability/commitment checks. This supersedes the draft's one-rover/one-drone
demonstrator scope; existing executable capabilities are still reported
separately and no multi-drone implementation was claimed or added here.

The user clarified the source of immediate pressure: a meeting with a startup
contact tomorrow, not a dissertation novelty defense. They explicitly identify
the application as defense and dual use. Prepared a Polish one-page concept
and speaking notes in
`../../research/scout-startup-vision-2026-11-20/`: `SCOUT_vision.pdf` and
`VISION.md`. Proposed focus: robotic mobility/logistics supported by terrain
traversability observations; civilian rescue/inspection applications and
potential UGV/UAV integrators remain use-case/customer hypotheses.

The material distinguishes existing research components from the proposed
integrated demonstration. It makes no claim of established novelty, market
validation or operational defense readiness. No domain code, experiments,
communications to third parties or commitments were made.

### Return to target mission before method selection (2026-11-19)

After reviewing the proposal figure and the broader multi-agent autonomy
project description, the user asked to define the actual mission and robot
responsibilities. See [target mission](SCOUT_TARGET_MISSION.md): proposed payload
delivery A-to-B with one rover and two sensing helpers, local decision ownership,
autonomous offers/refusal, acceptance, concurrent movement, result fusion and
cross-agent experience for future learning. The existing one-helper case remains
the integration starting point. Concrete team/sensor defaults are proposals,
not implemented features or novelty evidence.

The earlier context-compression candidate is set aside as an optional research
hypothesis, not a selected doctoral direction. Existing wire contracts, sensor
code and experiment behavior were not changed. The target document does not
implement cancellation, consensus, new modalities or federation. Mission success
is judged by task completion/resources, with uncertainty as a diagnostic.

### Nearest-method audit and a concrete research candidate (2026-11-19)

The user asked this coordinating chat to investigate a viable contribution
after the acquisition chat found substantial overlap. See
[research decision](SCOUT_RESEARCH_DECISION_2026-11-19.md) for a seven-source
primary-literature comparison, inspected-material limits, and a proposed
decision-loss sketch with selective refinement. Generic recipient value,
compression and incremental utility elicitation all have predecessors.

The proposed contribution is a reusable sensing-specific representation and
refinement rule, evaluated against exact minimal context, per-offer evaluation,
generic elicitation and fixed sketches. It remains a research hypothesis, not
confirmed novelty or implemented behavior. A finite-model error observation
is provided as a correctness target, not a new theorem or mission guarantee.
No source behavior, shared contracts, sensor implementation or experiments
changed for this documentation-only audit.

### Bounded next-study protocol and context sensitivity (2026-11-19)

After the user emphasized the need to act, prepared `SCOUT_NEXT_STUDY.md`:
a proposed sequence of a precise related-method comparison, a small joint
agent/sensor/pose benchmark specification and a reference table before training.
This is not confirmation of novelty or approval of all future implementation.

Completed an isolated21-context analytical diagnostic in ignored
`runs/scout-quality-timing-diagnostic-v0`: three geometry-derived deadlines
crossed with seven upper-passage priors; same two approved quote fixtures and
conditional route-cost model. At deadline2, q=0.60 yields savings0.377/0.668 at
priors0.35/0.40, but zero at0.50. No hidden truth, future reports, simulation
forks or learning. Script assertions passed; no domain code changed. Distinct
likelihood scalars are not evidence of implemented heterogeneous modalities.

### SAP comparison and noisy-pose analytical check (2026-11-19)

The user requested a primary-source assumption comparison after sharing a
related-work review. See `SCOUT_SAP_COMPARISON.md`. The current toy example is
not evidence of novelty or a reproduction of SAP. Distinguish the proposed
decentralized contracts from executable behavior and a pruning score from
full planning. Concurrent rover/drone movement is not a new differentiator.

With the existing cost table/deadline and two explicit approved likelihood
fixtures, the pure calculator gives `(4,4)` at q=0.60, available2: expected
cost24.70, zero gain; `(9,4)` at q=0.90, available4: cost22.50, gain2.20.
This checks only two poses, not a noisy all-grid ranking or physical mission.
The earlier perfect-sensor outputs remain separate. No policy, sensor, shared
contract or mission-loop code changed, and no new learning run was performed.

### Automatic path needs and all-grid viewpoints (2026-11-18)

The user authorized a small baseline inspired by Traversing Mars. Added the
isolated `decision/acquisition/path_aware.py` and analytical comparison
`experiments/scout/path_aware_demo.py`; see `SCOUT_PATH_AWARE.md`. The heuristic
derives unknown cells from a computed optimistic rover path and enumerates all
225 drone poses, scoring covered unknown path cells per execution tick subject
to time/energy limits. It is a one-view adaptation, not the paper's full IPP
method or a claim to its guarantees. Local evidence only; no simulator forks.

Both selectors use the same generated poses and explicitly perfect reports.
The previous manual viewpoints and noisy likelihood fixtures are ignored, not
reused as a sensor model. At a four-tick deadline both selectors choose `(4,4)`:
expected route cost21.75 versus24.70 without information. A constructed one-tick
case puts the drone above the alternative lower passage: the path heuristic
declines, while recipient value selects `(9,11)` with expected cost22.45. This
illustrates useful information off the single optimistic path, not superiority
over the published algorithm. Start/goal, public corridor map, two uncertainty
locations and fork timing remain configured.

Inspected outputs are `runs/scout-path-aware-v0` and
`runs/scout-path-aware-near-fork-v0`; each preserves all pose quotes and model
inputs with provenance. 45 focused tests passed, including13 new tests. Shared
contracts, mission/controller loop and sensor implementation are unchanged.
Authoritative distance-quality integration and online context updates remain.

### Isolated single-decision value calculator (2026-11-15)

The user asked the acquisition chat to start building a small example, with
Jev set aside: one route decision and two information needs, with the drone
choosing among representative observation poses. Added the pure local-context
estimator `decision/acquisition/recipient_value.py`, an analytical example
`experiments/scout/single_decision.py`, a separate JSON fixture and 14 tests.
See `SCOUT_SINGLE_DECISION.md` for the run command, model and boundaries.

Conditional costs come from a public 15x15 corridor topology plus a declared
contact/backtrack continuation. The calculator enumerates belief hypotheses
and possible noisy reports without truth, future payloads or simulator forks.
The inspected default ranks upper observation 22.50, joint observation 23.85,
no query 24.70; lower observation arrives after the decision and adds no value
for that decision. These are analytical model predictions with a fixed failure
penalty, not simulated or learned mission results. 32 focused tests passed in
this filesystem snapshot (18 existing plus 14 new).

Quality is supplied as explicit fixture likelihoods at the approved model's
specific distances; no duplicate sensor implementation was added. Flight/time,
footprint and energy quotes reuse existing helper/accounting code. Authoritative
sensor-source reconciliation still precedes online integration. Shared message
contracts, mission loop, legacy sensor, CLI and existing policy factory were
not changed. This is not yet autonomous agents exchanging messages online,
an exhaustive pose generator, A2A integration or a trained selector.

### Minimal cooperation contract specification (2026-11-14)

Latest architecture-chat clarification: only communication delay is zero.
Flight and sensing still take time; information arrives immediately when the
measurement is ready, not upon acceptance. The rover may continue moving and
its context may change during execution. Timing, context versions and useful
deadlines remain active in the contract example; executable mission timing is
unchanged. This supersedes the assistant's overbroad intermediate simplification
that also removed flight/sensing time and froze rover context.

The user authorized the architecture chat to specify four rover–drone messages,
without implementing contracts or A2A. `SCOUT_COOPERATION_CONTRACTS.md` records
need, offer/refusal, acceptance/no-query and result fields, separate question
regions and measurement poses, versioned recipient context and delivery
deadlines, and an R8/R5 example using the approved distance-dependent sensor.
It is a proposed integration specification, not executable behavior. The sensor
source-view discrepancy below remains unresolved; no sensor code was changed.

### Sensor correction and primary topic ownership

The user confirmed a functional rather than constant sensor accuracy model.
The environment/simulation chat records user approval and implementation of
linear drone accuracy0.90 at the center to0.60 at radius5, per-cell likelihoods
in Observation/belief fusion, and26 passing SCOUT tests. This coordinator's
filesystem view still reads the older constant model; reconcile source views
before integration, preserving the approved newer work. Do not silently treat
old constant-accuracy artifacts as measurements of the new model.

`SCOUT_CHATS.md` now assigns primary component responsibility. Architecture owns
containers/contracts; acquisition owns rover needs and drone proposal/value
decisions; environment/simulation owns sensing/physics/timing; verification
owns protocols, labels and evidence. A user-approved cross-component change in
another topic chat must not require duplicate permission here.

### Target: information needs and autonomous drone proposals (2026-11-14)

User-supplied coordination note clarifies the intended responsibility split:
rover describes the information need, affected decision and useful-until time;
drone evaluates whether/how it can help and proposes measurement poses/sensors
or declines; rover compares offers against continuing without acquisition.
Target region and measurement pose are separate. Both agents use local and
explicitly shared information. A2A is communication inspiration, not the value
estimator. See `SCOUT_INFORMATION_REQUESTS.md` for the proposed minimal scenario
and message concepts. No executable contract/policy or A2A infrastructure was
changed. The old feasibility-only drone and104 realized labels remain the
implemented baseline, not evidence of this target capability.

### Logical ownership recorded (2026-11-14)

The user requested a logical component split. `SCOUT_COMPONENTS.md` separates
environment, rover autonomy, drone helper, communication, simulation engine and
offline laboratory. Candidate generation/selection logically belong to the
rover; hidden-world counterfactual evaluation does not. This is documentation
of ownership and implementation boundaries, not a new code refactor or a claim
that complete agent containers and a learned selector are already implemented.

### Offline counterfactual labeling added

The user authorized the next implementation stage. The mission engine now
supports decision checkpoints, idempotent pause/resume and independent offline
forks retaining pending captures, undelivered observations, resources and policy
state. Full results for seeds42–46 and both original policies retain exact parity.

`decision/acquisition/candidates.py` generates local-view-only proposals along
current and alternative routes. `experiments/scout/counterfactual.py` evaluates
one forced first action and then the same continuation policy. It writes
separate inputs, supervision targets and world-group IDs; no hidden truth or
terminal outcome is supplied as a model input.

Command: `PYTHONPATH=src <python-3.11+> -m phdsim.cli scout --config
configs/scout/pilot.json --collect-labels --seeds 42 43 44 45 46
--decision-ticks 0 8 16 --max-candidates 6 --output runs/<fresh-name>`.
`runs/scout-counterfactual-v0` has104 rows from15 states:89 requests (5 positive,
7 negative,77 zero realized time gains) and15 no-request baselines. These are
inspected synthetic hindsight labels, not expected-VoI or learned-policy results.
See [labeling protocol and limitations](SCOUT_LABELS.md).

The user authorized the first synthetic SCOUT pilot after discussing the
generator, initial belief and policy configuration. Repository cleanup remains
deferred until UrbanIng is finished.

- Separate worktree `/Users/janek/Doktorat/phdsim-scout`, branch `scout`, based
  on local master `0ac86068d4b7817cffbca9291c73d1988402685f`.
- Domain modules now live in `environments/`, `sensors/`, `belief/`,
  `planning/`, `agents/`, `communication/`, `simulation/`, `costs/`,
  `decision/acquisition/` and `evaluation/`. `experiments/scout/` composes them.
  The shared CLI now dispatches `scout`; the old command is a thin alias.
- Implemented: seeded worlds, hidden truth, immutable local decision view,
  noisy Bayesian occupancy updates, belief-only navigation, drone requests,
  timed capture/delivery, resource reservations, two acquisition baselines,
  JSON/JSONL/SVG reports and source/configuration hashes.
- Run: `PYTHONPATH=src <python-3.11+> -m phdsim.cli scout --config
  configs/scout/pilot.json --compare --output runs/<fresh-name>`.
- Ten focused tests passed using Python 3.12; full ten-mission records match
  the pre-refactor reference exactly. See `SCOUT.md` for coverage.
- Diagnostic output: `runs/scout-pilot-v0-demo`, seeds42–46, both policies.
  All ten missions reached the goal. Scouting increased reserved energy;
  only seed45 became faster (64 versus63 ticks). No superiority claim.
- Not implemented: belief-sampled online value planning, learned acquisition, explicit
  wait/slow choices, federation, image perception, orbiters or validated
  planetary costs/dynamics.

Retain the agreed decentralized/federated direction: policies use local
evidence and explicitly received information. Training/aggregation topology
is not selected or implemented. This pilot has a rover decision maker and
local helper feasibility check, not a complete decentralized fleet.

The sections below are retained **October19 historical context**. Pending
UrbanIng statements there do not describe the current active study.

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

## UrbanIng-V2X: prepared data, next experiment

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
No particular trained UrbanIng model or final modality combination has been
selected, reproduced or evaluated in this repository.

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

See [UrbanIng implementation and commands](URBANING.md). No UrbanIng detector,
learned fusion, acquisition policy, online replay or task-quality result exists
yet. No agent assignment has been performed for this dataset.

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
[experiment status](EXPERIMENTS.md), [PSTNet guide](PSTNET_REPRODUCTION.md) and
[presence baseline](PRESENCE_BASELINE.md).

## Repository and machine handoff

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
