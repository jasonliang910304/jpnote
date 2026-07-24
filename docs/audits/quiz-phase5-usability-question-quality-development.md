# Quiz Phase 5 usability and question-quality development checkpoint

Date: 2026-07-24

## Scope

This checkpoint responds to the first real TUI session feedback without changing
core schema v5, Quiz schema v2, or the independent session/history model.

## Implemented

- Setup Enter/Space now advances from mode to count to Start instead of changing
  the focused value.
- Vocabulary meaning prompts prefer kana when a kanji term has a unique reading;
  ambiguous homophones conservatively retain the display form.
- False reading questions no longer borrow an unrelated entry's reading. They
  are emitted only when a subtle long-vowel, sokuon, or moraic-nasal trap can be
  produced safely.
- Hiragana long-vowel patterns such as `じょう -> じょ` are supported in
  addition to katakana `ー` removal.
- Reorder screens explicitly document Backspace undo.
- Feedback always resolves stable source details best-effort and shows useful
  canonical vocabulary/reading/meaning content even after a correct answer.
- The curses adapter enables the terminal default background best-effort so
  terminal opacity can remain effective. `run(transparent_background=False)`
  is retained as the future config hook.

## Deliberately deferred

Negative marking is not added in this checkpoint. A fair system requires
question-type-specific scoring, persistent summary fields that survive detail
pruning, migration design, and an opt-in config policy. Accuracy semantics remain
unchanged: wrong and skipped answers count as incorrect.

The formal `jpnote quiz` config surface has not been introduced yet. The TUI
currently defaults to preserving terminal transparency; a config switch will be
wired when the production CLI/config adapter is added.

## Verification performed in the reconstructed Quiz tree

- Phase 3 generator, question-pool, Phase 4 service/lifecycle, and Phase 5 TUI
  related tests: 131 passed.
- Python compile checks: passed.
- Patch whitespace check: passed.
- Existing core/full repository regression must still be run in the user's
  complete local checkout after applying this patch.
