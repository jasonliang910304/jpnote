# Quiz Phase 5 CLI / config development checkpoint

Date: 2026-07-24 (Asia/Taipei)

## Scope

- Add the formal `jpnote quiz` command.
- Keep Quiz loading lazy and fault-isolated from every core command.
- Add validated local Quiz defaults to `config.json`.
- Permit one-session CLI overrides for mode, count, JLPT levels, sources, and background behavior.
- Pass configured filters into the TUI question-pool request.
- Apply the independent Quiz-history detail cap after a TUI run on a best-effort basis.

## Configuration

```json
{
  "quiz": {
    "mode": "mixed",
    "count": 10,
    "levels": [],
    "sources": [],
    "transparent_background": true,
    "history_detail_cap_mib": 100,
    "prune_after_session": true
  }
}
```

Existing browse-only configuration files remain valid and receive the Quiz defaults in memory. The core import JSON schema and core SQLite schema v5 are unchanged.

## Fault isolation

`build_parser()`, `jpnote --help`, and all core commands do not import `jpnote_app.quiz.tui`. The optional adapter is imported only inside `command_quiz()`. Import failure is rendered as a concise command error and cannot block browse, import, audit, repair, export, or other core commands.

## Data-import concurrency

This checkpoint changes repository code and local preferences only. It does not migrate or write the core `jpnote.db`; normal grammar and vocabulary imports may continue.

## Deferred

- Interactive multi-select JLPT/source filter editor inside the setup screen.
- TUI recent/history browser and export/delete screens.
- Optional scoring/guess penalty.
- Formal v0.7.0 version bump and installation smoke.
