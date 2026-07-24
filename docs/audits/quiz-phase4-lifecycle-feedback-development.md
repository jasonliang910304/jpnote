# Quiz Phase 4 lifecycle / feedback development checkpoint

Date: 2026-07-24 (Asia/Taipei)
Baseline: Phase 4 headless service patch applied on top of `4697370`
Status: development checkpoint; not a `v0.7.0` release

## Scope

This checkpoint prepares the headless Quiz core for the future Python-native
TUI without registering `jpnote quiz` yet:

- resumable-session discovery for `active`, `paused` and `interrupted` states
- continue / decline-recovery service operations
- outer lifecycle interruption guard for SIGINT and unexpected exceptions
- debug-adapter best-effort interrupted-state persistence
- first-version overall and per-question-type result summaries
- optional expanded source details for wrong / skipped feedback
- precise history state filtering

## Crash and recovery behavior

A normal SIGINT or unhandled application exception inside the lifecycle guard
marks an active session `interrupted` and preserves the original exception.
If the persistence attempt itself fails, it does not replace the original
failure.

A hard process kill cannot execute cleanup. The already persisted session
therefore remains `active`, but is still returned by the resumable-session
query. Continuing it reuses the exact stored remaining question snapshots.
Declining recovery immediately persists `abandoned`.

## Feedback boundary

The immutable saved question remains authoritative. Expanded details are read
through the stable `QuestionSourceReader` contract only:

- vocabulary: display, reading, level, meanings, examples, aliases and sources
- mistake: original prompt/context, correct answer, reason, source/section and
  linked stable entry keys

Deleted sources return `missing`; public core read failures return
`unavailable`. Neither condition changes or invalidates saved Quiz history.

## Quiz schema v2

This checkpoint upgrades only the independent `quiz.db` schema from v1 to v2.
Core `jpnote.db` remains schema v5.

Schema v2 adds a permanent JSON summary column to each Quiz session. Per-type
answered/correct/incorrect/skipped counters are updated in the same transaction
as each answer. This is necessary because retention may later delete question
details, while the v1 specification requires per-question-type summaries to
remain permanently available.

Migration properties:

- existing v1 sessions with retained details are backfilled transactionally
- a migration failure rolls back the added column and leaves user_version at 1
- newer unknown schemas still fail closed
- history export version becomes 2 and includes per-type summaries
- pruning details never removes the persisted summary

## Debug adapter additions

```bash
python -m jpnote_app.quiz.debug_cli resumable
python -m jpnote_app.quiz.debug_cli continue SESSION_ID
python -m jpnote_app.quiz.debug_cli decline SESSION_ID
python -m jpnote_app.quiz.debug_cli result SESSION_ID
python -m jpnote_app.quiz.debug_cli details SESSION_ID QUESTION_EVENT_ID
python -m jpnote_app.quiz.debug_cli recent --hide-abandoned
```

The debug adapter remains JSON-only and is not the final user-facing UI.

## Intentionally unchanged

- core SQLite schema v5
- core CLI startup path
- `VERSION` and release tag
- installer
- public import JSON schema
- existing textbook `attempts`
- response-time tracking
- final TUI framework and rendering
