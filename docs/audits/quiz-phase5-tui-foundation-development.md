# Quiz Phase 5 TUI foundation development checkpoint

Date: 2026-07-24 (Asia/Taipei)

## Scope

This checkpoint adds the first usable Python-native terminal interface on top
of the already-tested headless Quiz service.  It deliberately does not modify
core CLI startup, core schema v5, Quiz schema v2, generators, or session/history
storage.

## Architecture

- `tui_controller.py` is a pure semantic state machine and renderer.
- `tui.py` is a thin standard-library `curses` adapter.
- Core jpnote never imports either module unless Quiz is explicitly launched.
- Keyboard behavior can be tested without opening a real terminal.
- Mouse click support is opportunistic and maps rendered option rows to the
  same semantic actions as keyboard input.

## Implemented flows

- startup recovery list for active/paused/interrupted sessions;
- mixed/vocabulary/mistake setup with default count 10;
- safe-pool shortage confirmation;
- multiple-choice and true/false answering;
- reorder-4 selection and submission;
- arrow navigation, Space selection, Enter confirmation, direct 1-4 keys;
- skip, compact feedback, expandable source details;
- pause/abandon/cancel exit menu;
- completed-session summary and per-question-type performance;
- best-effort interrupted-state persistence on uncaught TUI failure;
- narrow-terminal clipping and East Asian cell-width-aware wrapping.

## Deferred to the next TUI checkpoint

- `jpnote quiz` integration through the core CLI optional loader;
- JLPT/source filter editor;
- history browser/export/delete screens;
- configuration keys for default count and retention behavior;
- broader real-terminal compatibility smoke on the user's Kitty/Hyprland setup.

## Safety notes

- no dependency was added;
- no production database is opened by import;
- all answer correctness is still determined by `QuizService` from immutable
  question snapshots;
- no response-time metric is introduced.
