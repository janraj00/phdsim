# PHDSIM project context

Branch `scout` is a lean synthetic benchmark for multi-agent semantic terrain
mapping and selective cross-modal acquisition (**2× UAV RGB + 2× UGV LiDAR**).
Earlier PST900/UrbanIng code and corridors/elevation prototypes were pruned
after commit `2f3dc96` (full history remains in Git). Keep generated outputs in
git-ignored `runs/` paths.

Read `docs/CONTEXT.md` before continuing research or implementation. It records
the latest user decisions, verified experiment state and next work. Use
`README.md` for entry points and `docs/SCOUT_SEMANTIC_ENVIRONMENT.md` for the
semantic terrain design.

- Write maintained repository documentation in English; communicate with the
  user in the language of their current request.
- Keep perception, fusion and acquisition decisions separate, with distinct
  methods in separate modules. Treat perception classifiers as black-box
  `SemanticEstimator` plug-ins.
- Distinguish an agreed design from implemented code, and completed experiments
  from pilot results or published reference numbers.
- Ground truth is offline supervision/evaluation data only. Acquisition policies
  may use only their local evidence and explicitly available peer metadata, and
  must use strictly disjoint `fit` / `cal` / `test` seed splits.
- Keep datasets, checkpoints, local runs, generated outputs, dependencies and
  credentials out of Git.
- Run checks appropriate to changed behavior. Documentation-only handoffs do
  not require repeating the full test suite.
