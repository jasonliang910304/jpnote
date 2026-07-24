# Quiz Phase 5 History Question View — Development Checkpoint

Date: 2026-07-24

## Scope

This checkpoint closes the last v1 history-reading usability gap before release
candidate preparation.  Existing headless JSON export and safe-delete storage
capabilities remain available, while dedicated TUI export/delete actions are
explicitly deferred as non-blocking follow-up work.

## Added behavior

- `QuizSessionResult` exposes the exact immutable saved question events when
  details are still available.
- A history summary can open a per-question list.
- Each list row shows position, result, question type and a prompt preview.
- A per-question view shows:
  - full prompt and choices;
  - the user's saved answer;
  - the immutable correct answer;
  - correct / incorrect / skipped / unanswered state;
  - current optional source details resolved through stable public read ports.
- Up/down keys move between saved questions without returning to the list.
- Mouse rows in the question list are clickable.
- If retention has pruned details, the permanent summary remains usable and the
  TUI clearly reports that per-question records are unavailable.

## Isolation

- No core schema change; core remains schema v5.
- No Quiz schema change; Quiz remains schema v2.
- No write to core attempts.
- Source detail lookup remains optional and fail-soft.
- Normal grammar/vocabulary imports may continue during this checkpoint.

## Validation

Targeted reconstructed-tree validation:

```text
4 passed
python -m py_compile service.py tui_controller.py PASS
```

Expected full repository baseline after the previous isolated-install checkpoint
and these four tests:

```text
376 passed, 18 subtests passed
```

## Next gate

Prepare the v0.7.0 release candidate:

1. update version and user-facing release documentation;
2. measure app-only coverage and write the release health-check;
3. run fresh-install and previous-version upgrade smoke;
4. validate a copy of the real database;
5. produce release patch/SHA-256, then perform the short real-install smoke
   window with imports explicitly paused.
