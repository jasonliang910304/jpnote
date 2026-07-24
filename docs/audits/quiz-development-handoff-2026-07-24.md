# Quiz development handoff / health checkpoint — 2026-07-24

## Purpose

Record the recoverable development state between the v0.6.6.4 release and the future v0.7.0 Quiz release. This checkpoint exists because the central handoff documents had remained at the pre-Quiz baseline while multiple development tags and audits had already been created.

## Released baseline

- jpnote v0.6.6.4
- core SQLite schema v5
- stability gate PASS

## Quiz development completed

- Phase 1 contracts/isolation
- Phase 2 independent session/history store, retention/export, Quiz schema v2
- Phase 3 generators and question-pool safety
- Phase 4 headless service, lifecycle/recovery and detail feedback
- Phase 5 curses TUI foundation and first usability/question-quality corrections

## Latest validation supplied by the user

```text
python -m compileall -q jpnote_app tests    PASS
pytest -q                                  346 passed, 12 subtests passed
bash -n install.sh                          PASS
git diff --check                           PASS
```

Targeted results at the latest checkpoint:

```text
tests/test_quiz_phase3_generators.py       22 passed
tests/test_quiz_phase3_question_pool.py    20 passed
tests/test_quiz_phase5_tui_foundation.py   35 passed
```

## User-observed TUI findings already addressed

1. Enter in setup incorrectly changed values instead of advancing focus.
2. Kanji-to-Chinese questions were too easy for a Chinese reader.
3. Reorder questions needed an explicit Backspace hint.
4. Unrelated false readings such as `以上 → さんか` were trivial.
5. Correct responses still needed the actual answer displayed.
6. TUI should retain terminal transparency; a config switch is desired.

Implemented policy:

- kana-first meaning prompts when same-reading ambiguity is absent;
- false readings restricted to long-vowel/sokuon/hatsuon traps;
- correct, incorrect and skipped feedback shows the actual answer;
- terminal default background is used; config integration remains next.

Negative scoring was recorded as a low-priority optional idea, not part of the current release gate.

## Import/data safety

Normal grammar/vocabulary imports may continue during repository-only, Quiz-only and temporary-DB work. Development instructions must explicitly warn the user before any short window that requires imports to pause, especially core DB migration/repair/restore, consistent snapshot capture, formal install/upgrade smoke or concurrent core-writer tests.

No destructive test may run directly against the user's production `jpnote.db`.

## Next work

1. Formal `jpnote quiz` lazy-loader integration.
2. JLPT/source filters.
3. Quiz config defaults and transparent-background switch.
4. TUI history/recent/resume and shortage confirmation.
5. Installer/package smoke, then v0.7.0 release preparation.

## Remaining release work

- CHANGELOG/README/USER_GUIDE
- coverage and full health audit
- fresh install and v0.6.6.4→v0.7.0 upgrade smoke
- real core DB copy verification
- release patch, SHA-256 and continuation artifact
