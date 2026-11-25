# SCOUT and Scout-Assisted Planning: assumption comparison

Primary-source review, 2026-11-19. This is a specification/code comparison and
a two-pose analytical check, not a reproduction or benchmark of SAP.

Source: [Bui et al., Scout-Assisted Planning, v1](https://arxiv.org/html/2605.22693v1).
The section references below distinguish the paper's formulation from our
implemented calculator and proposed cooperation specification.

## Assumptions and implementation status

| Aspect | SAP: primary-source facts | SCOUT target | Current isolated example |
|---|---|---|---|
| Geometry and unknowns | Known graph; blocking locations and priors supplied (section 3). | Local beliefs; needs derived from navigation consequences. | Public corridors, two unknown cells/priors and fork supplied. |
| Coordination | Central planner; identical shared partial graph (section 3). | Rover need, independent drone offer, rover acceptance. | Pure functions; message exchange is specified, not executed. |
| Viewpoint | Scout visits a candidate blocking point (sections 3–4). | Question region and measurement pose separate. | All 225 poses generated in the perfect-sensor comparison. |
| Measurement | Perfect; sensing time neglected (section 3). | Distance-dependent noisy likelihoods; finite sensing time. | Manual noisy quote fixtures, or an explicitly idealized all-grid comparison. |
| Timing | Concurrent motion; replan upon new evidence (section 4). | Same physical concurrency, plus explicit useful-until/context. | One fixed common approach and decision deadline. |
| Selection | IAP pruning followed by POMCP joint planning (section 4.4). | Offer value versus no query with recipient-local context. | Exact enumeration for two routes and at most two unknowns. |
| Learning | Offline GNN predicts conditional cost difference (section 5). | Learned utility/transfer remain hypotheses. | No trained recipient-value selector. |

SAP's equations 8 and 11 use
`p*(1-p)*sum(V_blocked - V_traversable)/flight_time` for IAP priority.
This is distinct from our one-decision expected saving against no query.
It is a pruning score, not the complete SAP planner.

Our small calculator is not an approximation of all SAP capabilities. In
particular, a fixed fork and fixed continuation are substantially narrower
than repeated online planning. Shared partial knowledge is also not hidden
ground truth. Sampling plausible states from a declared belief is different
from reading the actual hidden simulator state; our restrictions do not rule
out belief-based Monte Carlo planning.

## Concrete implication on the existing grid

Keep the declared two-route cost table, priors, energy limit 6, drone start
`(2,3)` and rover decision at tick 4. Query upper passage A at `(9,4)`.
For this check, supply two explicit likelihood fixtures from the approved
contract: accuracy 0.60 at distance 5 and 0.90 at distance 0. No sensor
implementation is added or changed.

| Option | Pose | Distance to A | Accuracy | Flight + sensing | Expected route cost | Expected saving |
|---|---|---:|---:|---:|---:|---:|
| No query | — | — | — | — | 24.70 | 0 |
| Early, distant view | `(4,4)` | 5 | 0.60 | 1 + 1 = 2 | 24.70 | 0 |
| Later, close view | `(9,4)` | 0 | 0.90 | 3 + 1 = 4 | 22.50 | 2.20 |

With prior P(A blocked)=0.5, the distant report produces posterior 0.4 or 0.6.
The optimal choice remains the lower route for both reports. Thus uncertainty
decreases but this particular route decision receives zero expected benefit.
The close report produces posterior 0.1 or 0.9, selecting upper or lower,
respectively. Both acquisitions fit the energy allowance; the exact-deadline
report is processed before route selection.

These values were checked with the existing pure recipient-value calculator
using the two quoted likelihoods. They are analytical predictions under the
fixed continuation/failure model, with no intervening informative rover
observation. No report was sampled. This is not a global noisy-sensor ranking
over all poses, and no SAP implementation was run.

The earlier all-grid perfect-sensing report remains valid under its own stated
assumption: it selected `(4,4)` with expected cost 21.75. The new calculation
shows why that choice cannot be carried over unchanged to noisy sensing.

## Research decision

Use the existing map to isolate question/pose/quality/time trade-offs. Keep
explicit which parts are supplied, computed, implemented or only specified.
For the immediate next analytical stage, fix geometry and beliefs and compare
the usefulness of timely noisy views against no acquisition and expected own
evidence. A change in the best offer is a model behavior to verify, not a
novelty claim.

Treat decentralized offers based on limited recipient context as a candidate
research constraint. Establish what context suffices for a useful value
estimate, how context updates invalidate estimates, and how much performance
is lost relative to a shared-context reference. This requires comparison with
other decentralized information-request methods before claiming a gap.
Sensor quality, decentralized control and transfer learning are individually
established topics; combining them does not by itself establish novelty.

No shared contracts, sensor code, mission loop or previous run outputs were
changed by this review. Authoritative sensor-source reconciliation still
precedes online integration.
