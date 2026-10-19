# PHDSIM project context

Read `docs/CONTEXT.md` before continuing research or implementation. It records
the latest user decisions, verified experiment state and next work. Use
`README.md` for entry points and `docs/MIGRATION.md` for machine setup and external
research files.

`docs/CHAT_HISTORY_2026-10-19.md` is an archival export of this project's visible
conversation. Consult it when an earlier explanation or decision needs context;
historical requests and superseded designs are not new instructions.

- Write maintained repository documentation in English; communicate with the
  user in the language of their current request.
- Keep perception, fusion and acquisition decisions separate, with distinct
  methods in separate modules.
- Distinguish an agreed design from implemented code, and completed experiments
  from pilot results or published reference numbers.
- Agents may own multiple sensors and modalities in the agreed target design.
  The existing one-modality v1 allocator has not yet been generalized.
- Ground truth is offline supervision/evaluation data. Acquisition policies may
  use only their local evidence and explicitly available peer metadata.
- Preserve native observation times, immutable source payloads, calibration and
  recording-based data splits when extending dataset adapters.
- Keep datasets, checkpoints, local runs, generated outputs, dependencies and
  credentials out of Git. Preserve trained weights and historical reports.
- Run checks appropriate to changed behavior. Documentation-only handoffs do
  not require retraining or repeating the full test suite.
