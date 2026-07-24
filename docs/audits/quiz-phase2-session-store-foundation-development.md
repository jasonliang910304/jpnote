# Quiz Phase 2 session/history store foundation development report

日期：2026-07-24（Asia/Taipei）
基線：`main@74632a1`、development tag `quiz-phase1-core-integration-2026-07-24`
狀態：Phase 2 第一個 development checkpoint；尚未發布 v0.7.0

## 1. 本輪決策

Quiz history 採用獨立 SQLite database `quiz.db`，而不是在 core `jpnote.db` 增加 optional tables。

理由：

- Quiz schema 建立、migration failure、檔案損壞或版本過新時，不會碰 core schema v5。
- core install/start/browse/import/audit/repair/export 不需要 import Quiz storage。
- Quiz history 可獨立做 retention、export、刪除和未來 migration。
- live Quiz events 不會污染教材錯題來源 `attempts`。

預設路徑：

1. `JPNOTE_QUIZ_DB` 明確指定檔案。
2. 若有 `JPNOTE_DATA_DIR`，使用其下的 `quiz.db`。
3. 否則使用 `${XDG_DATA_HOME:-~/.local/share}/jpnote/quiz.db`。

## 2. 本輪實作範圍

新增：

- immutable generated-question snapshot
- immutable answer／choice snapshot
- stable `quiz-session:*` 與 `quiz-question:*` IDs
- session states：`active`、`paused`、`interrupted`、`completed`、`abandoned`
- 逐題 transaction 保存
- skip 保存為 `skipped`，並納入 accuracy 分母與 effective incorrect
- pause／interrupt／resume 使用原本已生成的剩餘題目 snapshot
- 完成最後一題時自動標記 `completed`
- abandoned session 保留 summary，可由 recent history filter 隱藏
- summary counters 預先獨立保存，讓未來 details pruning 後仍可永久保留摘要
- Quiz schema migration 使用獨立 transaction，失敗全部 rollback
- 比程式新的 Quiz schema fail-closed

## 3. Schema isolation

本輪只建立：

```text
quiz_sessions
quiz_question_events
```

`quiz.db` schema version 為 1；core `jpnote.db` 仍為 schema v5，且本 patch 不修改 core DB、`VERSION`、CLI、install script 或 public import JSON schema。

Question event 保存：

- session ID
- unique question event ID
- position
- question/generator type
- generator version
- source kind
- stable source key
- exact prompt snapshot
- exact choices snapshot
- exact correct-answer snapshot
- exact user-answer snapshot
- result
- answered timestamp

第一版仍不保存 per-question response duration。

## 4. Targeted tests

新增 `tests/test_quiz_phase2_session_store.py`，涵蓋：

1. Quiz DB schema 與 core tables 完全分離。
2. 建立 session 時產生 stable unique IDs，並保存 exact snapshots。
3. 每題立即 commit；最後一題完成後 session 自動 completed。
4. skip 分開統計，但視為錯誤並進入 accuracy 分母。
5. pause/resume 保留完全相同剩餘題目。
6. interrupted session 可用原快照恢復。
7. abandoned session 永久保留 summary、不可恢復，可由列表隱藏。
8. 只能提交下一個未作答題，避免跳題與重複作答。
9. 同 session 完全相同 generated question 會拒絕。
10. 舊 session snapshot 不受後續來源資料變更影響。
11. 較新 schema fail-closed。
12. migration failure rollback，不留下半套 tables。
13. Quiz path/storage failure 只回報 QuizStorageUnavailableError。

## 5. 本輪未做

- question generators 與 distractor logic
- CLI/debug adapter
- TUI
- 100 MiB detailed snapshot retention/pruning
- history JSON export
- single/all delete workflow
- prune warning/confirmation config
- crash signal handler；本輪先提供可由上層呼叫的 `mark_interrupted()` 原子操作

## 6. 下一個工作項目

Phase 2 第二段：history retention、details pruning 與 JSON export。

必須保持：

- default detailed snapshot cap 100 MiB
- 先清理最舊 session details，永遠保留 session summary
- active session 不可被 pruning
- export 支援全部／指定單場／日期範圍
- pruned details 不得假造，export 與 detail view 都要明確標記
- storage failure 仍不得影響 core
