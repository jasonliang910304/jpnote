# Quiz Phase 2 history management development checkpoint

Date: 2026-07-24 (Asia/Taipei)

Baseline:

- branch: `main`
- commit: `6e08c4c`
- development tag: `quiz-phase2-session-store-2026-07-24`
- core SQLite schema: v5, unchanged
- Quiz SQLite schema: v1, unchanged

## Scope

This checkpoint adds the retention, export and explicit-deletion layer on top of
the independent Quiz session store.

Implemented:

- default detailed-history cap of 100 MiB;
- byte accounting for immutable question-event snapshots;
- oldest-terminal-session-first detail pruning;
- permanent retention of session summaries during pruning;
- protection of active, paused and interrupted resumable sessions;
- an explicit result when protected details prevent satisfying the cap;
- stable JSON-ready exports for all history, one session or an inclusive date
  range;
- explicit `available` versus `pruned` detail status in exports;
- atomic JSON file replacement with mode `0600` for the exported file;
- safe single-session and bulk history deletion;
- explicit opt-in before deleting resumable sessions;
- fail-closed export when an unpruned session has incomplete detail rows.

## Isolation properties

- All operations use the independent Quiz database only.
- No core table, core SQLite row ID or private CLI handler is referenced.
- Core schema v5 and Quiz schema v1 are unchanged.
- Pruning deletes question-event details only; it does not delete summaries.
- Resumable sessions are never selected by automatic detail pruning.
- Storage and export failures are raised as Quiz-owned storage errors.

## Storage-cap interpretation

The 100 MiB limit applies to the logical byte size of detailed question-event
records. SQLite may retain free pages after rows are deleted, so the physical
`quiz.db` file does not have to shrink immediately. Those pages remain reusable
by later Quiz writes without touching the core database.

## Verification performed in the isolated development tree

- Python compile check: passed
- new history-management tests: 16 passed
- pruning order and summary retention: passed
- resumable-session protection: passed
- explicit pruned export representation: passed
- date-range and single-session export: passed
- atomic private JSON output: passed
- safe deletion boundaries: passed
- core-table isolation check: passed
- patch apply check: passed
- whitespace check: passed

The complete repository regression suite must still be run after applying this
patch locally. The expected count from the current 199-test baseline is 215
passed tests plus the existing 12 subtests.

## Not included yet

- CLI commands or confirmation prompts;
- automatic retention invocation from a session engine;
- TUI history browsing;
- generated-question engine;
- signal/exception orchestration;
- a formal v0.7.0 release or installation update.
