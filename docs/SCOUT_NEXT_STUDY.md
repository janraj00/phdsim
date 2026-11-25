# Next SCOUT study: a bounded plan of work

Prepared 2026-11-19 after the user emphasized the need to make progress.
This is a proposed research protocol, not an established novelty claim or
authorization to implement all the later stages. The current runnable
analytical diagnostic is recorded separately below.

## Working question

Given a recipient's current decision context, can a team select a useful
future acquisition `(agent, owned sensor, measurement pose)` before its
deadline, and can a model of this utility transfer to held-out recipients or
sensor configurations?

The recipient, affected decision and no-query continuation are part of the
context. An agent can only select its own available sensors. Abstaining is
an explicit action. Instant communication does not imply instant sensing.
This question is a candidate to investigate, not a claim that the combination
has no precedent.

## Completed diagnostic: a usable reference

`runs/scout-quality-timing-diagnostic-v0` contains the script, all 21 effective
inputs/results, CSV and report with input/source provenance. It reuses the
existing pure recipient-value calculator; domain code was not extended.

Fixed: existing 15x15 public map, questions A=(9,4), B=(9,11), lower prior0.30,
drone=(2,3), energy allowance6, fixed continuation/failure table, no informative
own rover measurement before the fork. Two quoted observations of A:

- P=(4,4), q=0.60, available tick2.
- P=(9,4), q=0.90, available tick4.

Varied: rover start=(4,7), (3,7), (1,7), deriving deadlines1,2,4, crossed with
upper priors0.10,0.30,0.35,0.40,0.50,0.70,0.90. These are separate configured
decision contexts, not a physical trajectory or received measurement sequence.

At deadline2, the distant quote saves0.377 for upper prior0.35 and0.668 for
prior0.40; for prior0.50 its saving is zero. At deadline4/prior0.50 the close
quote saves2.20. At deadline1 all acquisitions are too late. At prior0.90,
neither quote changes the optimal decision, even at deadline4.

These are conditional analytical predictions, not learned-policy results,
mission outcomes or evidence of a gap in SAP. The two accuracy fixtures are
not two modalities. No distance-quality implementation was duplicated.
Assertions checked timely/late behavior, preservation of the no-query option
and the previously verified two-pose numerical case.

## Next deliverables and decision gates

1. **A precise literature comparison.** Read the methods and evaluations of
   [SAP](https://arxiv.org/html/2605.22693v1),
   [IMAS²](https://arxiv.org/html/2510.20009v2),
   [Multi-Sensor Next-Best-View Planning](https://doi.org/10.1109/LRA.2020.3007445)
   and [Simultaneous View and Feature Selection](https://arxiv.org/abs/2012.09328).
   For each, record prospective acquisition versus existing-view selection,
   objective, agent/sensor/pose choices, information sharing and transfer tests.
   Identify one supported methodological difference. If this is already covered,
   revise the hypothesis before implementing a learned model.
2. **A small acquisition benchmark specification.** Fix one recipient decision;
   define two helpers with two genuinely distinct owner-supplied sensor models
   and two candidate poses per helper. This yields up to eight acquisitions
   plus no query. Start with 12 hand-inspectable contexts varying recipient
   priors, deadline and geometry. Declare what is supplied versus computed.
   This is an integration sanity check, not a statistical learning evaluation.
   Resolve the authoritative sensor-source mismatch first. Describe sensor
   likelihood/coverage/failure differences; do not merely rename accuracy
   scalars RGB and LiDAR. Preserve separate question and measurement regions.
3. **A reference table before training.** For each context and feasible quote,
   record expected task cost, incremental energy, bytes, result time and regret
   relative to the best quote/no-query under the same evidence model. Compare
   no query, a declared uncertainty/quality heuristic and exact small-model
   decision value. The reference must use beliefs and quote likelihoods, never
   actual hidden terrain or future reports. The table is a model-specific
   reference, not a full-mission optimal policy.

The first learning experiment should follow only when the reason for learning
is explicit: exact utility becomes expensive, relevant models are uncertain,
or transfer/sample efficiency is the target. Learning to imitate this cheap
two-question calculator alone would not justify a new method.

For a later transfer test, hold out complete world/configuration groups,
including recipient/sensor configurations. Compare shared and individually
trained models with controlled total training-data and compute budgets, report
learning curves, and keep own-evidence baselines identical. Predeclare the
primary metric and acceptable loss relative to the reference before test use.
If transfer does not help, report that outcome and revisit the hypothesis.

The concrete near-term result is a supported problem statement and a reference
benchmark. Full online contracts, A2A, language/VLA and federation are outside
these next deliverables.
