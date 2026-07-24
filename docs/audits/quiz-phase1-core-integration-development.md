# Quiz Phase 1 Core integration development report

日期：2026-07-24（Asia/Taipei）
基線：`main@86ddf06`、development tag `quiz-phase1-foundation-2026-07-24`
狀態：development checkpoint；尚未發布 v0.7.0

## 1. 本輪範圍

本輪只完成 Quiz Phase 1 的真實 core read integration，不新增 CLI/TUI、generator、session/history store 或 schema migration。

驗證邊界：

- `StudySourceService` 只透過 `JpnoteCore` public reads 取得 entries 與 replayable attempts。
- 對外只保留 stable entry key 與 attempt `event_key`。
- Quiz snapshot 不包含 SQLite row `id`。
- 真實臨時 SQLite DB 的 vocabulary、grammar、multiple-choice 與 `reorder_4` 資料皆可轉為 immutable snapshot。
- source、JLPT level、result filter 維持 public metadata 語意。
- Quiz 題源讀取不改寫 core DB。
- malformed attempt structured JSON 採 fail-soft，core 其他讀取仍可繼續。
- 本輪不建立任何 `quiz_*` table，schema 仍為 v5。

## 2. 契約一致性修正

foundation 中：

- attempt list snapshot 會從 browse record 取得 `linked_levels`。
- 以 `event_key` 單筆取得 attempt snapshot 時，`linked_levels` 原本為空。

本輪改為：

- 單筆讀取使用 linked stable entry keys，再透過 public `core.get()` 查詢 level。
- list record 若沒有提供 levels，也使用同一個 public fallback。
- 不查 SQLite table，不依賴 row ID 或 CLI private handler。

這使同一 attempt 的 list/get snapshot metadata 一致，方便後續 generator、debug adapter 與 session snapshot 使用。

## 3. Targeted automated verification

```text
python -m compileall -q jpnote_app tests                  PASS
pytest -q tests/test_quiz_phase1_integration.py           8 passed
foundation fake-core compatibility probe                 PASS
git diff --check                                          PASS
```

Integration cases：

1. 空的真實 core catalog 可安全讀取，且不新增 Quiz schema。
2. 真實 entry snapshot 保留 senses、sources 與 capabilities，並支援 type/level/source filters。
3. 真實 attempt snapshot 使用 stable event key、排除 row ID，list/get 的 linked levels 一致。
4. catalog count、levels、entry/attempt sources 正確。
5. 所有 study-source reads 前後 DB bytes 相同。
6. 損壞 `options_json` 時 snapshot 標記 structure invalid，不中斷 core stats/entry reads。
7. entry 更新後，先前取得的 immutable snapshot 不被回溯修改。
8. 不存在的 stable entry/event key 回傳 `None`。

## 4. 本輪未做

- 不修改 `VERSION`、README、CHANGELOG 或 release 文件。
- 不建立 `jpnote quiz` command。
- 不新增 Quiz storage/migration。
- 不開始 question generator 或 distractor logic。
- 不選擇 TUI framework。
- 不安裝到使用者的正式 jpnote installation。

## 5. 本機 release gate

套用 patch 後需執行：

```bash
python -m compileall -q jpnote_app tests
pytest -q tests/test_quiz_phase1.py
pytest -q tests/test_quiz_phase1_integration.py
pytest -q
bash -n install.sh
git diff --check
git status --short
```

以 `main@86ddf06` 的 178 tests 為基準，預期完整結果為：

```text
186 passed, 12 subtests passed
```

若完整 regression 通過，可建立 development checkpoint commit/tag；仍不要建立 `v0.7.0` release tag。

## 6. 下一個正確工作項目

Quiz Phase 2：獨立 session/history store 的資料模型與 migration isolation。

開始 Phase 2 前先以文件中的定稿規格建立：

- immutable generated-question snapshot
- session states：active / paused / interrupted / completed / abandoned
- unique session/question event IDs
- live Quiz history 與既有教材 `attempts` 完全分離
- optional storage failure 不影響 core
- 逐題安全保存與原題 resume

實際採獨立 SQLite DB 或 core DB optional tables，仍應在 Phase 2 第一個切點依 fault-isolation 與 migration rollback 風險做最小決策，不擴張到 TUI。
