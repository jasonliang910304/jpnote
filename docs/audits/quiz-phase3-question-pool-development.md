# Quiz Phase 3 question-pool development checkpoint

Date: 2026-07-24 (Asia/Taipei)
Baseline: `7d3aa7a` (`quiz-phase3-generator-foundation-2026-07-24`)
Status: development checkpoint; not a release

## Scope

This checkpoint adds the headless question-pool and session-selection policy on
top of the capability-based generators.  It does not add a CLI command, TUI,
installation change, schema migration, or core-storage dependency.

## Implemented

- `mixed`, `vocabulary`, and `mistake` pool modes.
- Deterministic internal seed support for reproduction and debugging.
- Stable-key de-duplication of input entry and attempt snapshots.
- One question per source before alternate question types from that source are
  considered.
- Mixed mode includes both source kinds when both are safely available and the
  requested session has at least two slots, without imposing a fixed quota.
- Exact generated-question snapshots are never duplicated in one plan.
- Safe-pool shortage reporting exposes requested, available, selected, and
  missing counts; unsafe questions are never synthesized to fill a request.
- Soft true/false anti-extreme selection begins at five true/false questions
  and prefers an available answer that keeps either side at or below 80%.
- Immutable output is directly suitable for the independent session store.

## Isolation

The new module consumes only immutable `EntrySnapshot` and
`AttemptReplaySource` values plus the public Quiz generator API.  It does not
import SQLite, the core repository, the DB layer, or CLI-private handlers.

## Tests added

The targeted tests cover mode/count validation, unique-source priority,
alternate-type reuse, malformed-source skipping, mixed-mode source diversity,
shortage diagnostics, fixed-seed reproduction, input-order stability, exact
question de-duplication, linked vocabulary/mistake coexistence, and the soft
true/false anti-extreme rule.

## Deferred

- CLI/debug adapter and user confirmation when a requested count is unavailable.
- Session creation orchestration and signal handling.
- Python-native TUI.
- Public configuration for default count or seed.
