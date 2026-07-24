# jpnote 開發路線圖

最後更新：2026-07-24（Asia/Taipei）
正式 release 基準：v0.6.6.4（正式 tag 尚未切換）
release-candidate source version：0.7.0
目前開發位置：v0.7.0 版本／文件與 readiness audit 完成；下一步為 DB 副本、upgrade 與真實安裝 gate

## 已通過的前置 gate

- v0.6.6.4 stability gate：通過。
- core schema 維持 v5。
- Quiz 採獨立 `quiz.db`，目前 schema v2。
- 最新完整 regression：`376 passed, 18 subtests passed`。
- app-only coverage：`76%`。
- 隔離安裝 smoke 與 release-readiness audit：通過。

## Phase 1：Quiz 契約與隔離骨架 — 完成

- optional Quiz package。
- stable entry/attempt read contracts 與 capability model。
- fault-isolation tests。
- 禁止直接使用 core SQLite row ID、repository internal、CLI private handler。

## Phase 2：Quiz session 與 history core — 完成

- 獨立 Quiz store。
- active/interrupted/paused/completed/abandoned。
- immutable snapshots、逐題保存、resume/abandon。
- 100 MiB detail retention、summary 永久保留。
- JSON export、pruning、安全刪除。
- Quiz schema v2 保存永久題型摘要。

## Phase 3：Capability-based generation — 完成

- vocabulary/mistake/mixed pools。
- MCQ、true/false、reading trap、multiple-choice replay、`reorder_4` replay。
- distractor safety、homophone/meaning collision guards。
- unique-source-first、fixed seed、shortage report、soft anti-extreme。
- 漢字意思題在安全時以假名作 prompt。
- 讀音錯誤選項僅用長音／促音／撥音等細微陷阱。

## Phase 4：Headless service／debug adapter — 完成

- plan/start/next/answer/reorder/skip。
- pause/resume/interrupted/abandon。
- resumable、result、details、recent。
- SIGINT/exception recovery。
- source detail feedback 與 permanent question-type summaries。

## Phase 5：Python-native TUI — 進行中

### 已完成

- curses TUI foundation。
- 設定、題目、選項、重組、回饋、details、退出與結果畫面。
- keyboard fallback 與可用時的 mouse support。
- Enter/Space 設定流程修正。
- reorder Backspace 提示。
- 答對也顯示實際答案。
- terminal default background／透明度相容。

### 正式 CLI／config foundation — 完成

- `jpnote quiz` lazy loader 與 core failure isolation。
- config keys：default mode/count、levels/sources、transparent background、history cap/prune policy。
- CLI single-session overrides：mode/count/level/source。
- TUI 顯示已套用 filters，並依 config 執行 session 後 pruning。

### 互動式篩選／history navigation — 完成

- stable source catalog 驅動的 JLPT/source 多選畫面。
- recent history summaries 與 session result details。
- active/paused/interrupted session 可從 history 繼續。
- wrong/skipped-only filter 與 abandoned show/hide filter。
- 題庫不足確認畫面維持既有安全縮減流程。
- setup Enter 流程仍為「模式 → 題數 → 開始」，filters/history 使用明確快捷鍵與滑鼠目標。

### history 逐題檢視／隔離安裝 — 完成

- history summary 可進入逐題清單。
- 每題顯示題目、選項、作答、正解、結果與來源詳情。
- retention 已清除 details 時明確只顯示永久摘要。
- 隔離 installer/package smoke 已驗證 fresh install、reinstall、manual、lazy loader 與 Quiz 缺失時的 core failure isolation。

### 下一個 checkpoint：v0.7.0 release gate

1. 以正式 DB 副本跑 quick_check、foreign_key_check、audit、stats 與 read-only Quiz planning。
2. 驗證 v0.6.6.4 → v0.7.0 隔離 upgrade。
3. 暫停匯入並執行正式 backup／install／installed-command smoke。
4. 產生 release patch、SHA-256、annotated tag 與最終 continuation prompt。
5. gate 完成前不建立 `v0.7.0` tag。


### Phase 5 後續（不阻塞 v1）

- history export/delete TUI 入口。
- optional negative scoring／guess penalty。

## 不阻塞 v1 的 backlog

- optional negative scoring／guess penalty。
- response timing、streak、familiarity、spaced repetition。
- radar chart、長期趨勢。
- multi-writer retry/serialization。
- attempt identity index optimization。

## 日常匯入安全規則

預設可持續使用 `jpnote paste/import`。只有在明確標示「先暫停匯入」時暫停；主要適用於正式 core DB migration/repair/restore、固定 DB 快照、正式安裝升級驗證或可能同時寫入 core DB 的測試。純 Quiz/repository/temporary-DB 測試不需暫停。

## 每階段驗收

- core 在 Quiz absent/disabled/broken 時完整可用。
- Quiz 寫入只進 Quiz store，不污染 core attempts。
- stable public IDs，不使用 SQLite row ID。
- 每一階段有 contract、fault-isolation、regression tests。
- 狀態或下一步變更時同步 handoff、roadmap、continuation prompt 與 audit。
