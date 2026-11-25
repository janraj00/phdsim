# SCOUT: quality-constrained collaborative terrain reconstruction

Working target, 2026-11-19. The user requested a polished research description
for a separate business discussion and intends to continue implementation in
this coordinating chat. Polish copy-ready description:
`../../research/scout-terrain-model-2026-11-19/OPIS_BADAWCZY.md`.

## Direction established by the discussion

Use construction and progressive refinement of a large-area digital terrain
model as the main candidate demonstrator for SCOUT. This develops the area
mapping direction; the earlier payload-delivery scenario is historical.
The general information-cooperation mechanism should remain separable from
the mapping task. The earlier sensor-family bound proposal is an optional
method candidate, not the definition of SCOUT or a selected doctoral method.

Objective: reach declared model quality and coverage as quickly as possible,
subject to energy and communication budgets. Alternative resource tradeoffs
can be investigated explicitly; do not claim simultaneous unconstrained
minimization of time, energy and bytes.

The initial representation should make geometry, semantic labels, uncertainty
and observation provenance explicit. Exact layers, resolution, numerical
tolerances and final-map ownership are still design choices, not implemented
or fully agreed contracts. A full physical digital twin with predictive
simulation is a later scope extension.

## Proposed first demonstrator

- At least two aerial sensing agents and one ground sensing peer in an Earth
  analogue, with independently configured capabilities and resources.
- A synthetic terrain and incomplete prior. Sensor models must distinguish
  genuinely different observable properties, not only scalar accuracies.
- Preserve the accepted functional dependence of observation quality on
  sensing conditions. Reconcile the known sensor-source discrepancy before
  integrating changes; the Gaussian diagnostic is not a replacement sensor.
- Separate queried region/property from the sensor pose. Needs may originate
  from any robot. An agent may own multiple sensors.
- Alternatives include using local evidence, obtaining existing peer evidence,
  obtaining a new view, using another modality, and local ground measurement.
- Stop inspecting a region when declared requirements are met. If no useful
  feasible action exists, retain an unresolved status; do not redefine it as
  irrelevant or successfully reconstructed.

Lunar deployment needs different motion, sensing and energy models. Ordinary
Earth multirotor flight must not be carried over to the Moon. Rovers and
propulsive hoppers are possible separate platform models. Existing orbital
products can supply a prior, but do not assert a specific dataset or
calibrated lunar simulation has been selected.

## Information and responsibility boundaries

Keep environment truth, observation generation, local belief/fusion,
acquisition decisions, motion planning, communication and offline evaluation
separate. Controllers use only local evidence and explicitly exchanged data;
they never inspect terrain truth or future reports.

An information need identifies a missing property/region, quality target and
time relevance. A potential provider assesses usefulness and feasibility and
may propose an execution or refuse. Selection accounts for current
commitments, pending observations and the cost of cooperation. Provider
autonomy is target behavior, not a capability already integrated in the pilot.

Consistency requires a shared spatial reference, source IDs, observation
history/versioning, duplicate-evidence handling, conflict handling and
assignment visibility. It does not yet specify identical maps at all agents.
The final model owner or distributed completion procedure must be chosen
before implementation of mission completion; map replicas cannot simply be
averaged as independent evidence.

Initial benchmark simplifications such as a common known coordinate frame,
static terrain or ideal pose estimates must be declared. They must not be
described as implemented localization or solved multi-robot SLAM.

## Evaluation and research scope

Measure elapsed time to declared completion, actual model quality then,
premature completion, unresolved coverage, geometry error, per-class semantic
quality and uncertainty calibration. At runtime completion uses available
belief; offline truth checks that claim. Report resource exhaustion separately
from quality success. Do not evaluate time using only successful runs.

Count all modeled physical work and every communication category, including
needs, offers, acceptances, metadata, updates and retries if modeled.
Compute time, sensor acquisition cost and link cost remain separate metrics.

Compare fixed coverage/allocation, uncertainty-driven acquisition, selective
communication and strong joint conditional-benefit references on matched
inputs and resources. Any baseline with extra global knowledge must be
explicitly identified. Separate worlds and acquisition histories across
training/testing; evaluate held-out sensor/team configurations.

The proposed research concerns a specific acquisition/communication decision
method and its measured benefit. Generic multi-robot mapping, heterogeneous
sensing and information-aware planning are established. The detailed learned
representation, algorithm, novelty and guarantees remain unestablished.

Sources supporting the use case, not a novelty claim:

- [USGS lunar foundational products](https://fdp.astrogeology.usgs.gov/fdp/moon/).
- [CADRE planning and execution](https://arxiv.org/abs/2502.14803).
- [ASLaP-HR](https://arxiv.org/abs/2208.06053).
- [NASA JPL MoonFall](https://www.jpl.nasa.gov/missions/moonfall/), a planned
  mission, not evidence of deployed SCOUT-like coordination.

## Implementation status

The [elevation mapping benchmark](SCOUT_ELEVATION.md) implements the first
paired comparison with two drones and a rover. It isolates replanning on a
shared synthetic elevation map. The terrain layers, semantics, communication
constraints and distributed coordination described above remain target scope.
The original navigation/acquisition pilot remains available separately.
