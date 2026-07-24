# Quiz Phase 5 Isolated Installation Smoke — Development Checkpoint

Date: 2026-07-24

## Scope

This checkpoint adds automated and operator-friendly isolated installation
validation before any real user installation is touched.

It validates the existing installer by replacing `HOME`, `JPNOTE_DATA_DIR`,
`JPNOTE_QUIZ_DB`, `XDG_CONFIG_HOME`, and `XDG_DATA_HOME` with temporary
directories.

## Added validation

- installer copies the complete `jpnote_app`, including optional Quiz modules;
- bundled documentation is installed;
- generated launcher is executable;
- installed `jpnote --version` and `jpnote --help` work;
- installed `jpnote quiz --help` exposes mode/count/JLPT/source options;
- installed lazy Quiz TUI loader imports successfully without starting curses;
- fresh installed `init` and `stats` use only the isolated core data directory;
- core initialization does not create Quiz history;
- installation itself does not read or modify a pre-existing core database;
- reinstall creates a backup of the previous launcher;
- removing the installed Quiz package causes `jpnote quiz` to fail cleanly
  without a traceback while core version/help/stats remain available;
- installed `manual --path` points at the bundled user guide.

## Files

- `tests/test_quiz_phase5_installation.py`
- `scripts/smoke_isolated_install.sh`

## Data-safety status

No pause in normal grammar/vocabulary imports is required for this checkpoint.
All installation and database paths are redirected to temporary directories.

The following later step is different: before a real `./install.sh` upgrade and
installed-command smoke against the user's normal launcher, explicitly pause
`jpnote paste` / `jpnote import`, confirm a clean Git checkpoint, and create a
current backup.

## Expected baseline

Before this checkpoint:

- `365 passed, 18 subtests passed`

After adding the seven tests:

- `372 passed, 18 subtests passed`

## Next gate

After isolated installation tests pass:

1. commit and tag this installation-readiness checkpoint;
2. synchronize central handoff documents;
3. decide remaining Quiz v1 history/export/delete scope;
4. prepare v0.7.0 release files and health-check;
5. explicitly pause imports only for the short real-install/upgrade smoke window.
