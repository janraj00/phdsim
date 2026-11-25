# SCOUT topic chats

Created 2026-11-14 at the user's request. These are separate topic chats with
focused handoffs, not automatic copies of the full source conversation.

Source/coordinating chat: `01a1c646-794f-7ea3-9ae2-b4da55f4a210`
(title at creation: Doprecyzuj nowość współpracy agentów).

All chats belong to the local Platforma project (`/Users/janek/Doktorat`).
SCOUT implementation is in `/Users/janek/Doktorat/phdsim-scout`, branch `scout`.
The initial prompts request read-only context intake, not parallel edits.
No additional Git branches or worktrees were created for these chats.

| Chat title | Thread ID | Responsibility |
|---|---|---|
| SCOUT — Architektura agentów | `01a1da5e-5a15-7871-946f-c1378c8ecfe5` | Logical ownership, agent composition and interfaces |
| SCOUT — Środowisko i symulacja | `01a1da5e-6589-77f3-bebe-c7b17539f245` | World generators, sensing, motion, clock and delivery |
| SCOUT — Akwizycja i uczenie | `01a1da5e-702e-7d72-967a-5e3ce45e5ac4` | Candidate proposals, acquisition value, labels and future learning |
| SCOUT — Eksperymenty i weryfikacja | `01a1da5e-7ac1-7663-ab7c-e110db6d7184` | Protocols, baselines, leakage/timing checks, metrics and reproducibility |

## Shared context

Start with `AGENTS.md`, `CONTEXT.md`, `SCOUT_COMPONENTS.md`, `SCOUT.md` and
`SCOUT_LABELS.md`. Re-check current files before implementation: the worktree
has uncommitted code that must not be overwritten by a new checkout.

Use the source chat for shared research decisions and cross-component contract
changes. Assign concrete implementation tasks and file ownership before
concurrent edits. Separate conversations do not provide filesystem isolation.
Repository consolidation remains deferred until UrbanIng is finished.

## Primary ownership after autonomous helper clarification

| Component / responsibility | Primary topic chat |
|---|---|
| Rover/drone agent containers, state ownership and shared message contracts | SCOUT — Architektura agentów |
| Information-need selection, communicated decision context and recipient-value estimates | SCOUT — Akwizycja i uczenie |
| Drone observation-pose/action generation, usefulness ranking, proposals and refusal decisions | SCOUT — Akwizycja i uczenie |
| Terrain, visibility, sensor likelihoods and consistent belief updates | SCOUT — Środowisko i symulacja |
| Motion, simulation clock, communication timing and physical resource accounting | SCOUT — Środowisko i symulacja |
| Objectives, baselines, offline labels, grouped splits, metrics, verification and reports | SCOUT — Eksperymenty i weryfikacja |
| Cross-component decisions, dependencies and integration order | Source/coordinating chat |

The drone agent container and its decision algorithm have different ownership:
architecture composes the object and defines interfaces; acquisition supplies
its execution-proposal/value logic. The sensor owner supplies one quality model
which both measurement generation and pre-query planning must use consistently.
Verification checks that agreement independently.

This table assigns responsibility, not simultaneous permission to edit the same
file. A task touching shared DTOs/configuration or a module outside its primary
scope should identify those files and dependencies before edits. Direct user
authorization in any topic chat is sufficient; do not request the same approval
again merely because the coordinating chat did not deliver it. Record that
decision in shared context so other chats can use it.

The original read-only intake instruction applied to the first handoff turn,
not later implementation tasks explicitly assigned by the user.
