# Quiz Phase 3 generator foundation development checkpoint

Date: 2026-07-24 (Asia/Taipei)

Baseline:

- branch: `main`
- commit: `cd6eaa4`
- development tag: `quiz-phase2-history-management-2026-07-24`
- core SQLite schema: v5, unchanged
- Quiz SQLite schema: v1, unchanged

## Scope

This checkpoint adds the first pure, headless question-generator layer.  It
consumes only immutable `EntrySnapshot` and `AttemptReplaySource` values from
the Phase 1 public read boundary and emits immutable
`GeneratedQuestionSnapshot` values already accepted by the Phase 2 session
store.

Implemented:

- vocabulary Japanese-to-Chinese four-choice questions;
- vocabulary Chinese-to-Japanese four-choice questions;
- vocabulary meaning true/false questions;
- vocabulary reading true/false questions;
- long-vowel, sokuon and moraic-nasal reading-trap questions when the source
  reading contains an explicit removable marker;
- four-choice to true/false fallback when three safe distractors are not
  available;
- original multiple-choice mistake replay;
- original `reorder_4` mistake replay;
- original-context candidate true/false replay for structurally valid
  multiple-choice attempts;
- deterministic seed support for reproducible tests and future debug tooling.

## Distractor and false-candidate boundary

Vocabulary candidates are rejected when any of these conservative signals is
present:

- same stable entry key;
- non-vocabulary type;
- same canonical display or alias collision;
- same non-empty reading (homophone boundary);
- equal or contained normalized meaning text;
- same non-empty review group.

Generated choices must have unique stable IDs and unique visible text.  The
correct answer must match exactly one visible choice.  If four-choice cannot
obtain three safe distractors, the generator falls back to a true/false
statement; if a safe false candidate does not exist, it emits a correct
statement rather than inventing a questionable false claim.

Mistake replay is fail-soft:

- multiple choice requires valid structure, prompt, choices and a uniquely
  resolvable correct answer by exact option text or numeric option ID;
- `reorder_4` requires exactly four valid parts and a full 1-4 permutation;
- candidate true/false requires saved sentence context and uses only an
  original non-correct option as a false candidate;
- malformed or ambiguous sources return no question instead of raising or
  guessing.

## Isolation properties

- no SQLite import or storage access;
- no core repository/DB/CLI-private import;
- no writes to core `attempts` or Quiz history;
- no CLI, TUI, signal handling or session selection policy;
- core schema v5 and Quiz schema v1 remain unchanged.

## Verification in the isolated development tree

- Python compile check: passed
- Phase 3 targeted generator tests: 20 passed
- deterministic seed reproduction: passed
- homophone/alias/meaning collision boundaries: passed
- four-choice -> true/false fallback: passed
- long-vowel/sokuon/nasal traps: passed
- malformed/ambiguous attempt fail-soft: passed
- permutation fuzz duplicate/multiple-correct guard: passed
- patch whitespace check: passed

The complete repository regression suite must still be run after applying the
patch locally.  The expected count from the current 215-test baseline is 235
passed tests plus the existing 12 subtests.

## Not included yet

- session-wide question-pool construction;
- unique-entry-first selection and second-question-type reuse;
- mixed-mode source balancing;
- soft 80% true/false anti-extreme constraint;
- requested-versus-safe-count reporting;
- CLI/debug adapter or TUI;
- automatic session-store creation from generated pools;
- a formal v0.7.0 release or installation update.

## Next checkpoint

Phase 3 pool construction and selection policy:

1. build a de-duplicated safe candidate pool from entries and replayable
   attempts;
2. prefer one vocabulary question per entry before reusing an entry with a
   second question type;
3. support vocabulary, mistake and mixed modes;
4. preserve deterministic seed reproduction;
5. report requested count versus safe available count without padding with
   ambiguous or duplicate questions;
6. apply a soft anti-extreme constraint to true/false answers when enough safe
   candidates exist.
