# Single-fork cooperation scenario

Historical single-question walkthrough. The active minimal calculator now has
two information needs; see [one decision, two needs](SCOUT_SINGLE_DECISION.md).

Proposed acquisition walkthrough, 2026-11-15. Prepared after the user chose to
set Jev aside and start with a simple scenario. This is a reviewable scenario
definition, not an implemented mission, an experiment result, or a change to
the shared cooperation contracts. It uses the message responsibilities in
[the cooperation specification](SCOUT_COOPERATION_CONTRACTS.md).

## Question and objective

Can the drone propose an observation of an uncertain passage from a different
cell, and can the rover choose it because it helps its next route decision?

Minimize expected remaining rover mission time, subject to a maximum incremental
acquisition energy of 5. Break time ties in favor of lower acquisition energy.
Flight runs in parallel with rover movement. Communication delay is zero;
flight and sensing durations are not zero. There is one need and at most one
accepted observation. Jev, A2A transport and training are outside this scenario.

## Known geometry and the one unknown

Use a 32 by 32 grid with four-connected rover motion. One rover step, including
a rejected attempt to enter a blocked cell, takes one time unit. The known
corridors are:

- Shared approach: `(1, 10)` to the fork F at `(3, 10)` along row 10.
- Route A: F to goal G at `(11, 10)` along row 10: 8 steps if open.
- Route B: F down to `(3, 13)`, across to `(11, 13)`, then up to G:
  `3 + 8 + 3 = 14` steps.
- All other cells are known impassable to the rover. The drone may fly over
  them under the approved simplified flight/sensor model.

Every corridor cell is known free except R8 at `(8, 10)`. The rover has prior
`P(R8 blocked) = 0.5`. The actual state is unavailable to either decision maker.
R5 at `(5, 10)` is a possible drone measurement pose, not the question cell.

For this first proposed scenario, the rover has reliable contact evidence and
no remote measurement of R8. This is an explicit scenario simplification, not
a change to the existing rover sensor. Other own-sensing models are extensions.

The fixed continuation rule is to follow the selected route until reaching the
goal or encountering the blockage. After a rejected entry into R8, the rover
returns to F and takes B. There is no voluntary mid-route switch in this first
decision model. This restriction makes the fork the last useful decision for
the need; it does not claim that later information is useless under a more
general replanning policy.

## Route costs derived from that geometry

If the rover chooses A and R8 is blocked, it travels 4 steps from F to `(7, 10)`,
spends 1 time unit on the rejected entry, returns 4 steps to F and takes B:

`4 + 1 + 4 + 14 = 23`.

Thus the rover can construct this conditional table from known corridors and
the declared continuation rule, without inspecting the state of R8:

| Action at F | R8 free | R8 blocked |
|---|---:|---:|
| Route A | 8 | 23 |
| Route B | 14 | 14 |

For posterior blockage probability p, estimated A cost is `8 + 15*p`; B cost
is 14. Choose A if `p < 0.4`, B if `p > 0.4`. Either route is time-equivalent
at equality. The table is exact within this deliberately restricted model;
general cost estimation from a partially known map remains subsequent work.

## Decision at time 1

The rover is at `(1, 10)` at time 1. Continuing along the known approach takes
it to `(2, 10)` at time 2 and F at time 3. It can keep moving while the drone
works. There is no new diagnostic rover evidence about R8 before F in this
version; contact sensing and local state updates remain active.

The need asks about R8, shares the prior and conditional route costs, and has
`useful_until = 3`, objective and energy limit as above. The drone starts at
`(2, 10)` at time 1, is available, has speed 3 and sensing duration 1.
Negotiation and acceptance take no simulated time in this fixture.

Generate positions inside the sensor footprint of the question cell and check
flight reachability, resources and timing. For the first walkthrough, inspect
two proposals explicitly: sensing from R5 and sensing from R8. Restricting the
comparison to these poses is not a general viewpoint-coverage guarantee.

Reuse the approved sensor model from the environment owner:

`q(d) = 0.90 - 0.06*d`, for Euclidean distance `d <= 5` from measurement pose
to the queried cell. Reports are binary with symmetric error `1-q(d)`. No
occlusion is modeled. This predicts sensor likelihoods, not the terrain state.

| Proposal | Flight distance | Distance to R8 | q | Flight duration | Result time |
|---|---:|---:|---:|---:|---:|
| Observe from R5 | 3 | 3 | 0.72 | 1 | 3 |
| Observe from R8 | 6 | 0 | 0.90 | 2 | 4 |

Result time is `1 + ceil(flight_distance / 3) + 1`. Capture and receipt coincide.
At time 3, receipt/fusion must precede the route decision. The R8 proposal is
too late for this need under the fixed continuation rule.

Use the pilot accounting coefficients: flight energy 0.3 per cell, sensing
energy 2, response energy 0.0005 per byte and 8 bytes per measured cell. A full
radius-5 footprint has 81 cells at either pose, hence 648 response bytes:

- R5 incremental energy: `3*0.3 + 2 + 648*0.0005 = 3.224`.
- R8 incremental energy: `6*0.3 + 2 + 648*0.0005 = 4.124`.

Both fit the acquisition limit. That limit assumes the rover's remaining
navigation energy is reserved separately. Return flight, computation energy
and request/acceptance overhead are omitted, consistently with the pilot
accounting abstraction. Extra footprint cells are known and do not affect the
route choice in this scenario.

## Estimate value before observing

No new observation: A expected cost is `(8 + 23)/2 = 15.5`; B cost is 14.
The no-query policy therefore chooses B, with expected cost 14 from F.

For R5, each report has probability 0.5 under the supplied prior. Bayes gives:

| Future report | Posterior P(blocked) | Expected A cost | Expected B cost | Choice |
|---|---:|---:|---:|---|
| Free | 0.28 | `8 + 15*0.28 = 12.2` | 14 | A |
| Blocked | 0.72 | `8 + 15*0.72 = 18.8` | 14 | B |

Expected decision cost after the timely R5 observation is
`0.5*12.2 + 0.5*14 = 13.1`. Estimated saving is `14 - 13.1 = 0.9`.

A timely q=0.90 observation would give expected cost
`0.5*(8 + 15*0.1) + 0.5*14 = 11.75`, a saving of 2.25. The R8 proposal is
not timely, so that conditional number cannot justify accepting it here.

| Option | Expected cost from F | Expected remaining time from time 1 | Extra energy |
|---|---:|---:|---:|
| No new observation | 14 | 16 | 0 |
| Observe from R5 | 13.1 | 15.1 | 3.224 |
| Observe from R8 despite missing this decision | 14 | 16 | 4.124 |

The rover accepts R5. The decision uses only the prior, conditional cost model,
sensor likelihoods, timing and resources. It does not use a sampled future
report, hidden terrain or a simulator fork.

The expected saving is a model prediction. In an individual run, a noisy report
can induce the worse route. A report does not turn the belief into certainty.

## Observable interaction

1. At time 1, rover sends the need and drone returns proposals or a refusal.
2. Rover compares the proposals with no new observation and accepts R5.
3. Rover continues toward F while the drone flies and senses.
4. At time 3, the drone provides a noisy R8 report with its sensor likelihoods.
5. Rover updates P(blocked) and selects A or B as shown above.
6. Rover follows the declared continuation rule, updating contact knowledge.

This is a proposed use of the existing four message concepts. It adds no
shared fields, executable DTOs, cancellation behavior or transport semantics.

## Boundaries and the next extension

The supplied conditional costs are now derived from a tiny known topology,
rather than chosen arbitrary scores. This does not solve general candidate
selection across many uncertain regions, correlated terrain, longer drone
routes or arbitrary replanning. It isolates one complete recipient-value
calculation before those extensions.

The first extension should permit rover evidence about R8 before F and compare
the added value of the drone against that same future own-sensing baseline.
A need with multiple question regions and route-dependent deadlines follows
afterward. These require an explicitly agreed description of future recipient
sensing/motion; this document does not extend the cooperation contract.

The current source snapshot still exposes the older constant drone sensor.
Before implementing or running this scenario, reconcile that snapshot with the
environment owner's approved distance-dependent implementation. Also verify
zero-delay delivery ordering and the declared rover continuation/sensing mode
with their owners. Do not change or duplicate the sensor here, and do not
describe the existing 104 offline labels as results of this scenario.
