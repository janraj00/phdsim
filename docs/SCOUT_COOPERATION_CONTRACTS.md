# Minimal rover–drone cooperation contracts

Proposed specification, 2026-11-14; authorized in the architecture chat.
This document defines four domain messages, not implemented DTOs, policies or
A2A transport. It refines [information needs](SCOUT_INFORMATION_REQUESTS.md).

## Current simplification: zero communication delay

The user clarified that only information transmission is immediate. Flight
and sensing still take time. Need, offer and acceptance have no transport
delay; the result arrives as soon as the measurement is ready, not as soon as
the offer is accepted. The rover may keep moving and updating its belief while
the drone executes, so its decision context may change.

`result_available_at = execution_start + flight_duration + sensing_duration`.
Distance affects flight time, sensor quality and acquisition energy. Timing
and useful-until constraints remain active. This is a proposed scenario
assumption, not a change to executable mission timing.

## Common envelope and ownership

Every message carries `message_id`, `schema_version`, `sender_id`,
`recipient_id`, `sent_at`, `need_id` and `context_version`. IDs identify immutable
messages; `context_version` identifies the rover's shared decision snapshot.
All times use the same mission clock. Regions and poses use
the declared grid coordinate frame. R5/R8 are example route labels, not stable
coordinates: messages carry actual cells.

| Message | Owner | Minimal body |
|---|---|---|
| `InformationNeed` | Rover | `question_region`, `property`, `decision_context`, `useful_until`, `constraints` |
| `DroneReply` | Drone | `status = offered / refused`; offered: nonempty `offers`; refused: `reason` |
| `OfferDecision` | Rover | `choice = accept / no_query`; accept: `reply_id`, `offer_id`; no query: `reason` |
| `MeasurementResult` | Drone | `offer_id`, `acceptance_id`, `execution_status`; success: `observation_id`, `sensor_id`, `sensor_model_ref`, `measurement_pose`, `captured_at`, `measured_region`, `evidence`; failure: `reason` |

`question_region` is what the rover asks about. `measurement_pose` is where the
drone proposes or actually performs sensing. Neither field substitutes for the
other. `measured_region` records actual coverage, including any extra cells.

## 1. Information need

For the first binary R8 scenario:

- `question_region`: cell R8 in grid coordinates; `property`: `blocked`.
- `decision_context`: `decision_id`, `as_of`, rover pose, `p_blocked` for R8,
  available route actions, and a small action-by-state table of estimated
  remaining route costs at the affected decision conditional on R8 being
  free/blocked. Include `cost_unit = mission_time_units`, the `no_query_action`
  and its estimated cost, `objective = minimize_expected_remaining_time` and an
  `estimate_method_ref`.
- `useful_until`: latest result availability before the affected route decision.
  If delivery and decision share a clock value, delivery must be processed first.
- `constraints`: maximum incremental acquisition energy. Observation age on
  receipt is zero in this scenario; flight time before capture is not age.

The table is a rover-local estimate, not a hidden-world counterfactual. It gives
the drone enough decision context to assess recipient value without receiving
the rover's entire map. Context that cannot support a value estimate must be
reported as insufficient; missing value is not zero value.

## 2. Drone offer or refusal

Each offer carries:

- `offer_id`, `measurement_pose`, `sensor_id`, `sensor_model_ref`,
  `covered_question_region`;
- `quality`: per-question-cell predicted observation likelihoods, derived from
  the sensor model at that pose; not a claim about actual terrain;
- `timing`: `accept_by`, predicted execution start, flight/sensing durations
  and `result_available_at` (a window if execution timing is uncertain).
  Capture and receipt coincide under zero transmission delay. Predictions
  are conditional on acceptance by `accept_by`;
- `cost`: estimated incremental energy and response bytes, with an accounting
  model reference. These include flight, sensing and response transfer;
- `recipient_value`: `status = estimated / unknown`, an `estimate_method_ref`,
  and, when estimated, expected route-cost saving versus the supplied no-query
  baseline, in the declared cost unit. State execution-time assumptions and
  timeliness status (`within_deadline / may_be_late / too_late / unknown`).

For binary R8, the drone can predict reports using the supplied prior and
sensor likelihoods, update that prior for each possible report, choose the
lowest expected table cost for each report, then average those costs. The
difference from the no-query baseline is **estimated decision benefit**, not
realized route saving. Benefit conditional on receipt before the route decision
must not be presented as guaranteed value when flight/sensing would finish late.

The drone chooses proposals using its own pose, sensors, availability and
resources plus received context. It may refuse for infeasibility, deadline,
cost, insufficient context or insufficient predicted usefulness. Refusal is a
drone decision, not a hidden oracle result.

### Reuse the approved sensor model

Reference the environment owner's existing distance-dependent model/version;
do not create another quality implementation. For the approved drone model,
`q(d) = 0.90 - (0.90 - 0.60) * d / 5` within radius 5, where `d` is Euclidean
distance from **measurement pose to the queried cell**. Outside the footprint
there is no observation. The binary likelihoods are
`P(report_blocked | blocked) = q(d)` and
`P(report_blocked | free) = 1 - q(d)`.
This model alone makes no occlusion claim. Both offer prediction and actual
evidence likelihoods must use the same referenced model.

The coordinating records confirm this approved model, while this filesystem
snapshot still exposes the older constant-accuracy implementation. Reconcile
the sensor source before implementing these contracts; preserve the owner's
newer work. This specification changes neither sensor implementation.

## 3. Acceptance or no query

The rover compares every offer with its own no-query option using its current
local context, timing and energy constraints. It selects at most one offer for
this need/version. `no_query` means continue without a new measurement; it
does not assert that future rover observations will be unavailable.

Execution starts only after the drone receives a valid acceptance, never merely
because it sent an offer. An acceptance must match the referenced offer's
need/version, validity window and terms; changed terms require a new offer.
Offers are not resource reservations. If availability has changed before
acceptance, report execution failure rather than silently claiming execution.

A new shared decision snapshot uses a higher `context_version`. The rover
must not accept an old-version offer without reassessment and a fresh matching
offer. This first contract does not cancel an already accepted execution.
Retries reuse IDs and must not start duplicate work.

## 4. Measurement result

Evidence contains each measured cell's noisy binary report and its applicable
likelihoods, with immutable payload identity. It contains no ground truth and
does not replace the rover's belief with a certainty claim.

Receipt follows capture immediately, after the required flight and sensing.
Transport records actual `received_at` on receipt (`received_at = captured_at`);
the drone cannot populate a future actual arrival time when sending it.
Only then may the rover fuse evidence. A late/old-context result cannot change
a past route decision, but may still be useful to the current belief after
age/model checks. Repeated `observation_id` values must not cause double fusion.

## Example exchange (illustrative estimates, not a run)

Let R8 = (8, 0), R5 = (5, 0) and drone start = (2, 0).
Use drone speed 3 cells per mission-time unit and sensing duration 1.
Only communication is immediate. The rover needs the result before its route
decision at time 3; this is not necessarily its arrival time at R8.

1. **Rover → drone:** need N1, context v3 asks about R8 with
   `p_blocked = 0.5`. Shared estimated costs in remaining mission-time units:

   | Rover action | R8 free | R8 blocked |
   |---|---:|---:|
   | Route through R8 | 10 | 30 |
   | Detour | 18 | 18 |

   No query selects the detour: expected cost 18. Energy allowance is Emax.
2. **Drone → rover:** reply D1 for N1/v3 offers O5 from R5 and O8 from R8.
   Both assume execution starts at time 1 (acceptance by that time).

   | Offer | Question | Measurement pose | Accuracy at R8 | Flight | Result available | Cost | Estimated saving if timely |
   |---|---|---|---:|---:|---:|---|---:|
   | O5 | R8 | R5 | 0.72 | 1 | 3 | E5, B5 bytes | 1.2 time units |
   | O8 | R8 | R8 | 0.90 | 2 | 4 | E8, B8 bytes | 3.0 time units |

   E5/E8 and B5/B8 are calculated by the declared accounting/coverage model,
   not chosen constants. Values use the supplied cost table, assume no
   intervening rover evidence and do not represent realized gains. O8's nominal
   benefit is conditional on a timely result; its actual timing misses this
   decision, so that number cannot justify acceptance for this need.
3. **Rover → drone:** at time 1, A1 accepts D1/O5 for N1/v3 if the context
   remains valid and E5 fits Emax. O8 is too late despite zero transmission
   delay. If neither offer is useful and feasible, send `no_query`.
   A refusal in step 2 leads to the same option.
4. **Drone → rover:** result M1 references N1/v3, O5 and A1; observation Z1
   captured at time 3 from R5 includes the noisy R8 report and likelihoods
   using q = 0.72. Receipt and fusion occur at time 3 before the route choice.
   During execution the rover may continue moving; the numerical estimate
   above is explicitly conditional on unchanged relevant decision context.

No agent reads hidden terrain, future payloads, simulator forks or offline
scores to construct needs, offers or acceptances. The simulator alone uses
terrain to generate evidence at capture time. Transport implementation,
general utility models, cancellation and A2A integration remain later work.
