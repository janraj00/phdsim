# Information needs and autonomous helper proposals

Coordination design note, 2026-11-14. The user supplied this target direction
after discussion in “SCOUT — Akwizycja i uczenie”. It records research intent;
message fields and the test below are proposed specifications, not implemented
contracts. No policies, executable code or transport have changed.

## Target ownership

The rover identifies **what it needs to know, why, and by when**. The drone
assesses **whether and how it can deliver information useful to the recipient**,
not only whether a commanded flight is feasible. It proposes measurement
poses/sensors and evaluates quality, timing and costs from local knowledge and
the explicitly supplied recipient context. It can decline or offer an alternative.
The rover compares proposals with continuing without a new observation.

The **target region** and **measurement pose** are separate variables. Asking
about cell8 does not command flight to cell8. Sensing it from cell5 requires
support from the sensor/visibility model.

## Proposed domain interaction

| Stage | Sender | Minimum information |
|---|---|---|
| Need | Rover | Request ID, target property/region, relevant belief, affected decision, useful-until time, declared budgets, context version |
| Offer or refusal | Drone | Request reference, measurement pose/sensor, covered region, predicted quality, delivery estimate/range, cost, estimated recipient benefit or inability to estimate it |
| Acceptance or no query | Rover | Selected offer reference or continued travel without a new observation |
| Result | Drone | Request/offer reference, measured region, actual measurement pose, capture time, uncertain observation and delivery metadata |

These are proposed domain concepts, not chosen A2A wire schemas. Unknown utility
must not silently become zero utility or certain benefit.

Battery and sensor knowledge alone do not determine recipient value. For a first
binary-terrain test, the rover could share its estimated costs of alternative
route decisions conditional on the target being free/blocked, together with
its target-state belief. Those estimates must come from the rover's belief,
not hidden truth. This is a candidate compact representation of decision context,
not a settled general contract. The drone need not read the rover's private map.

The rover's decision may change during negotiation. Context versions and
useful-until times identify stale offers; revision/cancellation policy remains
to be specified. Neither agent receives hidden-world fork outcomes online.

## First proposed experiment

One rover has a ten-cell route. The first three cells are sufficiently known;
cell8's state may change its choice at an earlier fork. The answer deadline
comes from that fork decision, not necessarily arrival at cell8.

Offer two ways to answer the **same** question, plus no measurement:

1. Sense cell8 from near cell5: potentially faster/cheaper, lower quality.
2. Sense cell8 from a better/closer pose: potentially better quality, slower or
   more expensive.
3. Decline or continue without a new observation.

Visibility and quality differences must follow the declared sensor model.
Correction: the user and the environment/simulation chat report the approved
distance-dependent sensor implementation: linear drone accuracy from0.90 at
distance0 to0.60 at radius5, with per-cell likelihoods used by belief updates.
The owner reports26 SCOUT tests passed. Reuse this model in the proposed test;
do not implement a second competing accuracy function. Distance dependence
does not itself establish an occlusion model.

Synchronization note: this coordinating chat's filesystem view still returned
the legacy constant-accuracy sensor when checked. The newer implementation is
confirmed by the owner chat's recorded edits and completion report, not by
executing it in this view. Reconcile source snapshots before integration; do
not overwrite the approved newer sensor with the stale copy.

Test cases should cover useful timely offers, better measurements arriving too
late, and cases where neither offer justifies acquisition. Specify the utility
and resource constraints before evaluation. A time-only objective may be
indifferent to extra energy while a hard energy budget is slack.

Compare the existing rover-selected pose, a helper considering only geometry
and costs, and a helper using the supplied recipient decision context. Use matched
budgets and independent world/noise groups. These are proposed comparisons.

## A2A and current implementation

The official [A2A introduction](https://a2a-protocol.org/latest/topics/what-is-a2a/)
describes autonomous agent communication, capability discovery and asynchronous
tasks. That communication layer does not provide SCOUT's recipient-value model
or observation planner. A first test can use local typed messages on the
simulation clock before integrating a full A2A stack. No LLM requirement follows
from adopting this interaction pattern.

The pilot currently interprets its target as the drone's flight/measurement
point and checks feasibility. The existing104 offline rows remain realized
intervention outcomes under that old contract. They do not establish expected
VoI, autonomous execution selection or a learned offer policy for this design.

Cross-component work: architecture defines the contracts; acquisition defines
shared decision context and utility estimates; simulation defines sensing and
timing; evaluation defines comparisons and information-boundary checks. The
next step is the small scenario/contract specification, preserving the current
executable baseline. No implementation is authorized by this note alone.
