# Quiz v0.7.0 Release-Readiness Audit — Development Checkpoint

Date: 2026-07-24

## Purpose

This checkpoint adds a single non-destructive audit command for the state
immediately before the v0.7.0 release-candidate version and documentation
changes.

The audit redirects all runtime data and configuration paths to a temporary
directory. It does not read, migrate, back up, or modify the user's normal
`jpnote.db` or `quiz.db`.

## Command

```bash
scripts/audit_quiz_v070_readiness.sh
```

## Checks

- Git working-tree summary and HEAD
- source version, core schema, and Quiz schema
- Python compilation
- shell syntax for installer and isolated install smoke
- complete pytest regression suite
- app-only coverage report
- isolated installation and installed-command smoke
- source-tree `jpnote` and `jpnote quiz` help
- fresh isolated core initialization and stats
- verification that core initialization does not create Quiz history
- optional Quiz TUI lazy-loading
- tracked database / secret-like file guard
- Git whitespace checks

## Data-import status

Normal grammar and vocabulary imports may continue while adding and running this
audit. It uses only temporary runtime directories.

Imports must be paused later, for the short real-install / upgrade smoke window,
before the actual installed launcher is replaced.

## Release decision

Passing this audit does not by itself publish v0.7.0. The following remain:

1. version and release documentation update;
2. fresh health-check and coverage result recording;
3. previous installed-version upgrade smoke;
4. formal backup and real installed-command smoke;
5. final tag and release package.
