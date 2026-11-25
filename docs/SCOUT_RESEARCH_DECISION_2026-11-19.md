# SCOUT: research decision after the nearest-method audit

Prepared 2026-11-19. This is a research recommendation and proposed experiment,
not a confirmed novelty claim, an implemented acquisition algorithm, or a change
to the agreed agent contracts. No training or mission experiment was run for
this report.

## Recommendation

Keep the rover–drone setting and existing acquisition work. Narrow the proposed
method to **adaptive transmission of recipient decision-loss contrasts for
ranking prospective noisy sensing actions**.

The receiver knows its task consequences and belief. The helper knows the
likelihoods, geometry and execution costs of its candidate measurements. Study
whether a reusable, progressively refined description of the receiver's
decision can let the helper rank those measurements accurately with less total
communication and planning computation than transmitting the full context or
asking the receiver to evaluate every offer.

This is a concrete algorithm-development hypothesis. Its broad ingredients
already exist. The contribution would have to be a useful representation,
refinement rule and evaluated cost/error tradeoff, rather than the statement
that robots should exchange useful information. A planetary application does
not independently establish that contribution.

## What the nearest sources actually establish

This is a targeted primary-source audit, not a systematic review. A missing
combination in this table is not proof of absence elsewhere. Publication years
come from paper/repository metadata rather than search-engine crawl dates.

| Source and inspected material | Existing mechanism relevant to SCOUT | Consequence for our proposed claim |
|---|---|---|
| [Mu, Chowdhary & How, 2013, Value-of-information aware active task assignment](https://dspace.mit.edu/entities/publication/06cc7223-c3cb-47d2-9d09-4372df88878a). Repository abstract/metadata; full PDF fetch failed with HTTP429. | Heterogeneous exploration/exploitation vehicles; information gathering valued through its influence on exploitation; decentralized CBBA allocation with travel constraints. | Recipient/task benefit and decentralized assignment are established. The inspected abstract does not establish detailed message contents; do not infer them. |
| [Bui et al., 2026 preprint, Scout-Assisted Planning (SAP)](https://arxiv.org/html/2605.22693v1). Problem formulation and planning method. | Concurrent ground/aerial planning, central joint actions, identical current partial graphs, perfect observations; POMCP and learned information-aware pruning. | Neither moving scouts nor task-aware or learned scouting scores are new. Its explicit information-sharing and sensing assumptions differ from our proposed experiment; that difference alone is not a method. |
| [Marcotte et al., 2020, Optimizing Multi-Robot Communication under Bandwidth Constraints](https://april.eecs.umich.edu/media/pdfs/marcotte2019auro.pdf). Model and Algorithms1–2/method discussion. | Chooses observations to transmit using forward simulation of teammate effects and bandit optimization. Maintains beliefs over teammates' states/maps, rather than requiring identical maps. | Recipient-aware utility under incomplete teammate knowledge already exists. The selected objects are available observations; our question concerns describing a decision before selecting future acquisitions. |
| [Kao & Subramanian, 2022, Common Information based Approximate State Representations in MARL](https://proceedings.mlr.press/v151/kao22a.html). Abstract and stated result scope. | General approximate common/private information compression with a dynamic-programming optimality-gap analysis. | Compact task-relevant context and approximation guarantees are not new categories. We need a concrete sensing-specific construction and comparison, not a renamed sufficient state. |
| [Talli et al., 2024, Effective Communication with Dynamic Feature Compression](https://arxiv.org/html/2401.16236v1). Remote-POMDP model and compression method; [published-version metadata](https://doi.org/10.1109/TCOMM.2024.3385922). | Observer tracks its own and the actor's belief, knows the actor policy or receives action feedback, and adapts sensory-message compression to control reward and bits. | Helping a recipient and adapting message size are established. Its inspected action is encoding an observation, rather than choosing a mobile measurement using a recipient-supplied loss descriptor. |
| [Athena, 2018, Towards Decision-Centric Anticipatory Sensor Information Delivery](https://www.mdpi.com/2224-2708/7/1/5). Decision model and query execution, Sections3 and7. | Shares decision expressions, selects evidence sources, schedules retrieval/prefetching and exploits decision structure, including route examples. | Sending a structured information need instead of a raw data request is also established. A need/offer protocol cannot be our main novelty claim. |
| [Boutilier et al., UAI2003, Cooperative Negotiation in Autonomic Systems using Incremental Utility Elicitation](https://www.cs.toronto.edu/kr/publications/autonomic.pdf), [venue record](https://mlanthology.org/uai/2003/boutilier2003uai-cooperative/). Model and elicitation sections. | Samples expensive private utility functions incrementally and chooses cooperative allocations using minimax regret. | Adaptive clarification until decision quality is sufficient has a direct predecessor. A generic implementation of this idea would be a baseline, not our contribution. |

The comparison rules out several earlier broad pitches. It does **not** show
that SCOUT cannot support original research. It identifies the methods the
next algorithm must improve on or exploit more specifically.

## A specific candidate method

Working description: **a decision-loss sketch with selective refinement**.
The name is descriptive and makes no priority claim.

For one pending rover decision, define:

- `x`: a finite hypothesis about relevant terrain, not the actual hidden terrain;
- `b(x)`: the rover's current probability for that hypothesis;
- `d`: a candidate rover continuation, including its declared fallback behavior;
- `C(d,x)`: its conditional task cost;
- `a`: a drone acquisition, including measurement pose, sensor and completion time;
- `q_a(y|x)`: the owner-supplied probability of report `y`;
- `k_a`: acquisition cost in the stated scalar objective. Energy can instead be
  a hard constraint; do not silently equate energy units with time.

Choose a reference continuation `d0` and form the signed contrast

`f_d(x) = b(x) [C(d,x) - C(d0,x)]`.

For fixed context and an acquisition delivered before the decision, its
expected improvement is

`V(a) = min_d sum_x f_d(x)
        - sum_y min_d sum_x q_a(y|x) f_d(x) - k_a`.

The common reference cost cancels because every report likelihood sums to one.
The expression is ordinary pre-posterior decision value written using cost
differences; this algebra is not claimed as a new theorem. No acquisition has
value zero and remains in the choice set. An inapplicable or late report does
not change this pending decision. Waiting or changing the deadline would be a
separate recipient action, absent from this first model.

The rover would transmit a coarse approximation of `f`, associated with stable
hypothesis identifiers and a context version. The drone combines it with its
own measurement likelihoods. It refines only parts whose remaining errors can
change the preferred acquisition or the comparison with no acquisition.

The important design opportunity is reuse: the same task descriptor supports
many viewpoints and sensor qualities. In contrast, a scalar utility answer for
one specific offer generally has to be recomputed for a new offer. Whether
this reuse outweighs descriptor construction and transfer is the actual question.

The full signed table can be exponentially large and can be larger than a map.
It is an exact small-model reference, **not** a proposed scalable wire format.
A candidate implementation must use, for example, hypothesis partitions with
residual bounds or a structured approximation. It must charge for building the
descriptor, finding shared hypothesis identities and refining it. We have not
yet demonstrated a representation that makes this efficient.

### A useful correctness target

For a finite fixed model, if a sketch satisfies

`sum_x max_d |f_d(x) - fhat_d(x)| <= epsilon`,

then its estimated value differs from the exact `V(a)` by at most `2 epsilon`
for any normalized known sensor kernel. Selecting the largest estimated value
therefore loses at most `4 epsilon` relative to the best feasible acquisition
in the same finite set, including no acquisition. This follows by bounding the
prior minimum and the report-weighted posterior minima separately. It is a
basic error-propagation observation, not an originality claim or a full-mission
guarantee.

One can stop earlier with per-offer intervals: if one lower bound is within
the chosen tolerance of every competing upper bound, further refinement cannot
improve this decision by more than that tolerance. This stopping principle is
also established in elicitation/selection research. Our work would be designing
cheap sensing-specific bounds and deciding what descriptor to refine.

For the first finite implementation, verify bounds by exact enumeration. For
large models, do not label empirical errors as certificates. Approximate sensor
likelihoods, private helper evidence, discarded rover actions and changes in the
rover context introduce additional error beyond this bound.

## A bounded experiment that can reject this proposal

### First deliverable: use existing code

Use `recipient_value.py` and the documented two-question example to make an
exact reference and a signed-contrast evaluator return the same values for all
existing feasible quotes. This checks factorization only; it is not a research
result. Keep the current distance-dependent likelihood fixtures until the
authoritative sensor source has been reconciled. Do not add another sensor
implementation. Neither agent receives hidden terrain or future measurements.

### Method experiment

Move beyond the four-hypothesis example only after equivalence is checked.
Use small public route graphs with several alternatives and at most eight
binary unknowns initially, so exact enumeration remains possible. Derive costs
from public geometry and the declared continuation, not arbitrary matrices
chosen to favor the proposed method. Vary priors, alternative-route penalties,
deadlines and owner-supplied sensing kernels. Initially hold the recipient
decision fixed while scoring offers; online context changes are a subsequent
experiment rather than a hidden source of error.

Compare, using identical feasible acquisition sets and likelihoods:

1. No acquisition and the existing uncertainty/path heuristic, as sanity controls.
2. Exact value with full **minimal sufficient** recipient context. Also measure
   full-map transmission separately; a tiny cost table is a stronger baseline
   than an unnecessarily large map.
3. On-demand exact scalar offer evaluation by the rover.
4. Generic incremental utility elicitation with its declared bounds and query
   cost, adapted transparently to the same finite action set. Do not claim a
   reproduction of the UAI resource-allocation experiment.
5. Fixed-size decision-loss sketches.
6. The proposed adaptive sketch/refinement rule.

Measure selection regret against the exact same-model reference, total bytes
in both directions, planner/likelihood evaluations and total computation,
including descriptor construction. Plot regret versus resources; fewer requests
alone is not success. With the current zero communication-delay assumption,
bytes saved do not automatically mean earlier sensing. Any later latency model
must be declared separately.

Use different complete graph/recipient configurations for development and final
evaluation. Hold out some sensor kernels to test whether reuse survives a
change of sensor without retraining the context representation. Select all
tolerances, hyperparameters and stopping budgets before inspecting final
results. Report uncertainty over independent configuration groups, not repeated
quotes from the same decision as independent trials.

The initial study should answer just two questions:

- At matched decision error, does the adaptive method beat both fixed sketches
  and generic elicitation on at least one relevant resource without concealing
  a material increase in the others?
- Does one descriptor remain useful across new poses/kernels, rather than
  effectively encoding a single precomputed offer ranking?

If exact full context is already cheap, that is a valid boundary result: the
two-question pilot gives no reason to compress or learn. If generic elicitation
matches the proposed method, do not claim a new refinement algorithm. Examine
where its cost comes from before expanding the simulator. Neither outcome
requires discarding the existing simulator, value calculator or UrbanIng work.

## What this could support, and what it cannot yet support

A defensible future paper claim would specify the actual sketch/refinement
algorithm, its model and error scope, then demonstrate a better resource/regret
tradeoff than the named alternatives. A larger doctoral contribution could
subsequently study online context changes and transferable approximation of
the expensive terms. Those are contingent extensions, not completed results
or a guaranteed dissertation plan.

Do not currently claim that this is the first recipient-aware, decentralized,
task-aware, uncertainty-aware or adaptive communication method. Do not add
federation, orbiters, A2A or extra modalities to compensate for an untested
algorithmic contribution. The useful immediate asset is an exact local
reference against which a specific new approximation can now be assessed.

The strongest unresolved novelty check is whether sensing/planning work already
provides essentially this reusable loss representation with adaptive refinement.
The targeted search found adjacent foundations above, but does not settle that
question. Perform forward/backward citation checking around those foundations
as the finite method is specified, before describing it publicly as original.
