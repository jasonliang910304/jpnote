# Quiz Phase 5 TUI filters and history development checkpoint

Date: 2026-07-24

## Scope

This checkpoint adds interactive, headless-testable TUI navigation for:

- JLPT multi-select filtering discovered through the stable source catalog;
- source multi-select filtering with a bounded scrolling window;
- recent Quiz history summaries;
- completed-session result details;
- continuation of active, paused, or interrupted sessions from history;
- mouse click targets for filter and history rows.

The existing setup Enter flow remains compatible: mode → count → start. Filters
and history use explicit shortcuts (`f`, `o`, `Shift+H`) and clickable rows so the
previous usability correction is not regressed.

## Isolation and data safety

- No core schema change; core remains schema v5.
- No Quiz schema change; Quiz remains schema v2.
- History browsing reads only the independent `quiz.db` through
  `QuizSessionStore`/`QuizService`.
- Catalog discovery uses `QuestionSourceReader.source_catalog()` and never reads
  core SQLite internals.
- Catalog or history discovery failure is fail-soft at the TUI boundary.
- Daily grammar/vocabulary imports may continue during this checkpoint.

## Deferred

- history export/delete screens;
- persistent editing of config values from inside the TUI;
- scoring/negative-marking rules;
- release version bump and formal installation smoke.
