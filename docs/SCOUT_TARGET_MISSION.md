# SCOUT target mission and team responsibilities

Working target specification, 2026-11-19. Prepared after the user asked to
define the actual mission and responsibilities before selecting another
algorithmic contribution. The concrete defaults below are proposals for that
discussion, not implemented features or a novelty claim. This document does
not authorize every later implementation stage or replace existing contracts.

## Target behavior

A heterogeneous robot team executes a mission using local, incomplete evidence.
Robots identify information needs, propose useful ways to satisfy them, agree
on execution, and adapt their actions after observations arrive. Experience
from multiple team members improves subsequent acquisition decisions.

The first concrete mission is **delivery of a payload by a ground rover from
start A to destination B through partially known terrain**. Scouting serves
this mission; the team need not map every cell. There may be several viable
routes. The rover observes locally and replans during execution. Its initial
route is provisional, and deciding to gather information does not freeze it.

Use a synthetic planetary-style environment with explicitly configured motion
and sensor models. It is not a validated lunar or Martian vehicle simulation.
Planetary constraints and additional mission types can be added separately.

## Team

The first complete team target is one delivery rover and two scouting helpers.
Existing one-rover/one-drone work remains the smaller integration case.

| Member | Responsibility | Private state and decisions |
|---|---|---|
| Delivery rover R | Deliver the payload; select route and information needs; compare offers with continuing or waiting | Local belief, current observations, pose, route alternatives, task consequences, deadlines and remaining resources |
| Scout H1 | Propose and execute useful measurements | Own pose, sensors, likelihood models, availability, energy, measurement poses and execution schedule |
| Scout H2 | Same helper role, with different capabilities or availability | Independently evaluates feasibility and recipient usefulness; may offer another sensing method or decline |
| Operator | Specify mission and constraints before execution | Start, destination, budgets and allowed behavior; does not choose every measurement |

For an illustrative heterogeneous sensor set, R has RGB and local depth/LiDAR,
H1 is an aerial RGB scout, and H2 is a scout with depth/LiDAR. Exact hardware,
mobility and modality models remain configurable. One agent can own several
sensors; role, platform and modality are distinct concepts.

Each modality must have a declared observation model describing what physical
property it measures, coverage, noise and failure/ambiguity conditions. Merely
assigning different accuracy constants to two occupancy sensors does not
establish multimodal perception. The approved distance-dependent quality
function remains part of the existing sensor specification and must be reused,
not replaced with a constant or a duplicate implementation.

## Operational flow

1. R plans a route from its current belief and begins moving. Helpers begin
   from configured poses and availability; they do not automatically follow R.
2. R detects a decision-relevant information need. It describes the questioned
   region/property, uncertainty, affected route alternatives and useful deadline.
   A need can concern a future route segment or an alternative route.
3. Each contacted helper considers its own feasible sensor/pose options and
   estimates whether they can help using explicitly supplied recipient context.
   It returns offers or a reasoned refusal. Unknown utility is not zero utility.
4. R evaluates offers under its current context, along with continuing without
   a new acquisition and, where explicitly supported, waiting for information.
   Waiting has a time cost and requires a new consistent usefulness deadline;
   it is not a free extension of an old offer.
5. R accepts at most one offer per need/version in this first target. A helper
   checks the acceptance against its availability and commits resources only
   if execution can start on the accepted terms. Offers alone are not bookings.
6. The helper moves to its chosen measurement pose and captures evidence.
   R may continue moving and collect its own evidence concurrently.
7. R receives evidence, checks identity/time/model, updates its belief and
   replans. It may retain its route, change it or generate another need.
8. Mission and acquisition outcomes enter an offline experience record for
   evaluation and subsequent learning.

Question region and measurement pose are separate throughout. A question
about route cell R8 may be answered by sensing from the neighborhood of R5.

## Illustrative episode, not an experimental result

R approaches a fork. One possible route crosses a region whose geometry is
unclear in the available image; another is longer. R estimates the consequences
of choosing either route and sends its need with a useful-until time.

H1 proposes a quick image from a different angle. H2 proposes a depth scan
with a different coverage/quality/time/cost tradeoff. Neither modality is
declared better in advance: the result follows from the specified observation
models, recipient context and timing. R may select either offer or continue
without one. During execution, its own sensor may reveal enough information
to change the route before the helper finishes.

This episode exercises the architecture. It is not evidence that a new method
outperforms SAP or another published planner.

## Decentralization and exceptional cases

No operational component receives the simulator's true terrain. The simulator
owns physics, event timing and measurement generation, not team decisions.
There is no runtime controller with automatic access to every robot's belief.
R owns its delivery decision, and each helper owns its proposed execution.
This is an asymmetric cooperative team, not yet a general swarm or a consensus
algorithm. Different delivery rovers and joint task allocation are later scope.

For the first contract integration, communication transmission time remains
zero; flight and sensing durations remain finite. Communication bytes still
count as a resource. This does not change the older pilot's executable timing.

| Event | Required behavior |
|---|---|
| No useful or feasible offer | R continues or explicitly replans/waits using its own evidence; lack of a reply is not a free-space observation |
| Helper availability changes before acceptance | Reject/fail the stale offer rather than overbooking or silently changing its terms |
| Accepted execution cannot finish | Helper reports failure; R continues from its current local state |
| Recipient context changes before acceptance | Reassess and obtain a matching current offer; do not accept an outdated utility estimate automatically |
| Context changes after acceptance | Reassess use of the eventual result. Existing minimal contracts do not cancel accepted execution; cancellation is a separate future extension |
| Measurement arrives after its useful deadline | It cannot affect a past decision, but may still update current belief if applicable |
| Noisy or ambiguous result | Fuse with its likelihood, not as guaranteed terrain truth |
| Duplicate evidence | Preserve provenance and avoid fusing the same observation twice |

## What collective learning means here

Experience records connect the recipient's permitted decision context, helper
capabilities, offered/selected acquisition, predicted benefit, timestamps,
actual evidence, resources and subsequent mission outcome. Offline evaluators
may additionally estimate intervention effects using controlled alternatives.
A single successful mission does not establish that its observation caused
the success or measure expected information value.

The learning target is improved prediction/selection of helpful acquisitions
across team experience, potentially including transfer to new recipients or
sensor configurations. Models must be evaluated on separate configuration/world
groups and against the same nonlearned reference decisions.

Collective learning is the use of experience across agents; its training and
model-exchange mechanism remains a method choice. A centralized offline
training baseline is compatible with decentralized execution. Federated
learning and online weight updates are not prerequisites for this scenario.

## Mission success and evaluation

Primary reporting is delivery success within declared budgets, followed by
completion time/cost among successes; also report failure times and reasons.
Do not hide failures by reporting only successful runs. Account separately
for rover travel, blocked-contact attempts, helper energy, communication bytes
and computation. A weighted aggregate requires declared weights.

Acquisition diagnostics include timely useful responses, selection regret
against a matched small-model reference, prediction calibration and redundant
measurements. Uncertainty reduction is diagnostic rather than the mission's
sole success criterion. Ground truth and counterfactual outcomes remain
offline evaluation/supervision only.

## Relation to current work

Current assets include synthetic worlds, movement/replanning, an offline
intervention evaluator, a pure recipient-value calculator and a path heuristic.
Full autonomous helper proposal generation, multihelper cooperation contracts,
general multimodal interpretation and collective learning are target behavior.
Resolve the recorded sensor-source discrepancy before integrating sensing.

The [minimal contracts](SCOUT_COOPERATION_CONTRACTS.md) remain the existing
one-helper specification. Adding peer discovery, multihelper selection,
commitment/resource handling or cancellation requires a coordinated revision;
this document introduces no new wire schema. See also
[logical components](SCOUT_COMPONENTS.md).

The immediate design baseline is this mission and decision ownership. The
earlier [decision-loss-sketch research candidate](SCOUT_RESEARCH_DECISION_2026-11-19.md)
remains an optional hypothesis, not the chosen doctoral topic or a prerequisite
for implementing this system.
