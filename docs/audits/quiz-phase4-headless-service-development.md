# Quiz Phase 4 headless service / debug adapter development checkpoint

Date: 2026-07-24 (Asia/Taipei)
Baseline: `4697370` (`quiz-phase3-question-pool-2026-07-24`)
Status: development checkpoint; not a `v0.7.0` release

## Scope

This checkpoint joins the already isolated Quiz components without adding the
final TUI or changing the core `jpnote` CLI:

- stable `QuestionSourceReader`
- safety-first `QuestionPoolBuilder`
- immutable generated-question snapshots
- independent `QuizSessionStore`
- headless answer validation and result persistence
- JSON development/debug adapter

## Safety properties

- The service never reads core SQLite tables or row IDs.
- Planning does not create Quiz history.
- A safe-pool shortage requires explicit confirmation before creating a
  smaller session.
- The caller cannot supply a trusted `correct` boolean.  The service resolves
  the chosen stable choice ID against the persisted immutable question
  snapshot and determines correctness itself.
- Reorder answers must contain every stable choice ID exactly once.
- Stale/out-of-order question event IDs are rejected before persistence.
- Skip remains a persisted incorrect outcome and returns the exact correct
  answer snapshot for feedback.
- Pause/resume continues from the exact previously persisted remaining
  questions.

## Debug adapter

The temporary adapter is intentionally not registered as `jpnote quiz` yet:

```bash
python -m jpnote_app.quiz.debug_cli plan --mode mixed --count 10
python -m jpnote_app.quiz.debug_cli start --mode mixed --count 10
python -m jpnote_app.quiz.debug_cli next SESSION_ID
python -m jpnote_app.quiz.debug_cli answer SESSION_ID QUESTION_EVENT_ID CHOICE_ID
python -m jpnote_app.quiz.debug_cli reorder SESSION_ID QUESTION_EVENT_ID 1 2 3 4
python -m jpnote_app.quiz.debug_cli skip SESSION_ID QUESTION_EVENT_ID
python -m jpnote_app.quiz.debug_cli pause SESSION_ID
python -m jpnote_app.quiz.debug_cli resume SESSION_ID
python -m jpnote_app.quiz.debug_cli interrupt SESSION_ID
python -m jpnote_app.quiz.debug_cli abandon SESSION_ID
python -m jpnote_app.quiz.debug_cli show SESSION_ID
python -m jpnote_app.quiz.debug_cli recent
```

Output is structured JSON for tests and debugging.  A pool shortage exits with
code `3`; adapter/runtime failures exit with code `2`.  This adapter is not the
final user-facing interface.

## Intentionally unchanged

- core SQLite schema v5
- Quiz SQLite schema v1
- version string / release tag
- core CLI parser and startup path
- installer
- final Python-native TUI
- response-time tracking
