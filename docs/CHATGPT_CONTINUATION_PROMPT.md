# jpnote ChatGPT 續接提示詞

> 使用時機：新聊天無法取得舊對話脈絡時，連同最新版 repository 提供給 ChatGPT。

請接續開發 jpnote。先閱讀：

1. `docs/PROJECT_HANDOFF.md`
2. `docs/ROADMAP.md`
3. `docs/QUIZ_V1_SPEC.md`
4. `docs/audits/quiz-development-handoff-2026-07-24.md`
5. `docs/RELEASE_CHECKLIST.md`
6. `docs/DELIVERY_GUIDE.md`
7. README、CHANGELOG、USER_GUIDE

## 目前基準

- 正式 release/tag 基準：`jpnote v0.7.0`
- 正式安裝版本：`jpnote 0.7.0`
- core SQLite schema：v5
- Quiz SQLite：獨立 `quiz.db`，schema v2
- stability gate：通過
- Quiz 開發已完成 Phase 1–4，以及 Phase 5 TUI、usability/question-quality、正式 CLI/config、互動式 filters/history navigation、history 逐題檢視與隔離安裝 smoke
- 最新完整測試：`378 passed, 18 subtests passed`
- app-only coverage：`76%`
- 隔離安裝、release-readiness、正式 DB 副本、前版升級、真實安裝與 TUI smoke：PASS
- post-release commits：`a660950`（是非題回饋標籤）、`74fb82a`（`paste --stdin`）
- `paste --stdin` targeted regression：`13 passed`；temporary-data installed smoke：PASS
- post-release maintenance：installed fzf helper isolated bootstrap、Quiz 準備畫面 refresh、session question batch insert

啟動新工作階段先確認基線：

```bash
git status
git fetch --tags origin
git rev-parse --short HEAD
git rev-parse --short origin/main
git rev-parse --short 'v0.7.0^{}'
jpnote --version
```

不要無條件重跑已通過的 v0.7.0 完整 release gate；依當次修改執行針對性測試，只有 blocking regression 或正式 release 才擴大驗證。

## 已完成 Quiz 功能

- optional/fault-isolated package 與 stable read contracts。
- independent Quiz history、immutable snapshots、resume/abandon、retention/export。
- safe generators、question pools、shortage reporting。
- headless service/debug adapter 與 lifecycle recovery。
- curses TUI foundation。
- 設定 Enter 流程、reorder Backspace 提示、正確答案回饋、terminal default background。
- 漢字意思題在安全時優先以假名作 prompt。
- 讀音 false trap 只使用長音／促音／撥音等細微變化，不使用無關詞讀音。
- 正式 `jpnote quiz` lazy loader；Quiz failure 不阻止其他 core CLI。
- config 支援 mode/count/levels/sources、transparent background、history cap 與 prune policy。
- CLI 支援單次 `--mode`、`--count`、`--level`、`--source` 覆寫。
- TUI 內支援 JLPT/source 多選、recent history/result details、未完成 session 繼續。
- history 支援 wrong/skipped-only 與 abandoned show/hide filters。
- history 可查看所有保存中的逐題題目、選項、使用者答案、正解、結果與來源詳情；details 已 pruning 時只顯示摘要。
- 隔離安裝 smoke 已驗證 package 完整性、installed CLI/help/manual、reinstall backup 與 Quiz 缺失時的 core failure isolation。
- installed launcher 已改為 `python3 -I` isolated bootstrap；repository/current-directory 與 `PYTHONPATH` shadow regression 通過。
- 正式 DB snapshot、read-only Quiz planning、v0.6.6.4 → v0.7.0 upgrade、正式安裝與 TUI 啟動 smoke 全部通過。

## 已完成 post-release hotfix

- `jpnote paste` 保留 Wayland 剪貼簿輸入。
- `jpnote paste --stdin` 可從 pipe／SSH 標準輸入讀取完整 JSON。
- stdin 與 clipboard 共用既有 `_run_import_text()`，沒有另做解析、預檢或匯入邏輯。
- 沒有 core/Quiz schema 或 public import JSON schema 變更。
- 正式 stdin 匯入因 stdin 已用來承載 JSON，非互動使用需加 `--yes`；預檢可用 `--check`。
- `--file PATH` 未加入；檔案輸入繼續使用 `jpnote import FILE`。


## 已完成搜尋／Quiz 啟動 maintenance

- installed 版 fzf search reload／filter helper 不再使用裸 `python -m jpnote_app...`。
- helper 比照主 launcher 使用 `python -I`、明確 app root 與 `runpy.run_module()`，避免 cwd／`PYTHONPATH` shadow。
- Quiz 開始 session 前先 refresh「正在準備題目……」，同步建題期間不再只有靜止設定畫面。
- Quiz session 初始題目列改用同一 transaction 內 batch insert；無 schema 變更。

## 下一個正確工作項目

目前完整排程：

1. 是非題顯示改為 `○／×`，同步 question/feedback/history。
2. `reorder_4` 顯示完整句子並高亮重組片段，提供無色 fallback。
3. TUI history export/delete 入口與刪除確認。
4. TUI 錯誤訊息／空狀態 polish。
5. release artifact 自動化與 install/release script 整合。
6. 單字漢字洩題改善；假名 prompt 必須排除所有同讀音詞條的意思，確保唯一答案。
7. fuzzy candidates、AI context、grammar combinations、romaji／語源、fzf／未分類／mistake level。
8. multi-writer／identity index。
9. 低優先：負分制、timing、streak、familiarity、spaced repetition、radar／trends。

不要因非 blocking finding 重啟同規模廣域健檢；優先依實際使用回饋做針對性修正。

## 日常資料匯入

使用者會持續匯入文法與單字。預設不需停止 `jpnote paste`、`jpnote paste --stdin` 或 `jpnote import FILE`。只有當回覆明確標示「先暫停匯入」時才停止，通常是正式 core DB migration/repair/restore、固定 DB 快照、正式 install/upgrade smoke 或可能同時寫入 core DB 的測試。純 repository、Quiz 或 temporary DB 測試可並行。

## 硬性原則

- core 在 Quiz absent/disabled/broken 時仍可 install/start/browse/import/audit/repair/export。
- Quiz 不直接查 core SQLite tables，不使用 row ID 或 CLI private handlers。
- Quiz live history 不寫入既有教材 attempts。
- 文法類學習練習不建立既有 jpnote attempts。
- 破壞性、migration、repair、fuzz 測試不得直接使用正式 `jpnote.db`。
- 不因非 blocking finding 重啟廣域健檢或延後 Quiz。
- 每次狀態/下一步/schema/測試基線變更都同步 handoff、roadmap、continuation prompt 與 audit。
- 使用者環境是 Arch Linux + Hyprland；編輯器預設 nvim。
