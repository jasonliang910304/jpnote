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

- 正式 release/tag：`jpnote v0.7.2`；annotated tag 必須指向本文件所在 release commit
- 正式安裝版本：`jpnote 0.7.2`
- core SQLite schema：v5
- Quiz SQLite：獨立 `quiz.db`，schema v2
- stability gate：通過
- Quiz 開發已完成 Phase 1–4，以及 Phase 5 TUI、usability/question-quality、正式 CLI/config、互動式 filters/history navigation、history 逐題檢視與隔離安裝 smoke
- v0.7.1 最新完整測試：`401 passed, 18 subtests passed`；targeted `16 passed`
- app-only coverage：`76%`
- v0.7.1 versioned isolated install、正式安裝、正式 DB 保護與 read-only copy smoke：PASS；audit 無 critical／needs_input
- post-release commits：`a660950`（是非題回饋標籤）、`74fb82a`（`paste --stdin`）
- `paste --stdin` targeted regression：`13 passed`；temporary-data installed smoke：PASS
- post-release maintenance：installed fzf helper isolated bootstrap、Quiz 準備畫面 refresh、session question batch insert
- v0.7.2 completed：`import --stdin`／`-`、`jpnote.import.v1` ASCII-safe protocol、preflight token、repository-owned Windows PowerShell 5.1／7 client
- v0.7.2 release gate：Arch `421 passed, 18 subtests passed`；versioned isolated install／正式安裝／DB hash-read-only smoke PASS；Windows PowerShell 5.1＋SSH 實機匯入與後續兩日使用 PASS
- v0.7.2 release commit/tag：`46644a1ea329d15c85f35b897485763278aa0787`；release 後首次 Windows Actions workflow 因 `steps[*].shell` 誤用 `matrix` context 在 validation 階段失敗，main 的 post-release maintenance 將 PowerShell 5.1／7 拆成明確 jobs；release tag 不移動
- 正常驗證分工：能在開發環境完成的測試不得轉交使用者；使用者只做完整實際 repository gate、Windows＋SSH 實機 gate與 final release gate

啟動新工作階段先確認基線：

```bash
git status
git fetch --tags origin
git rev-parse --short HEAD
git rev-parse --short origin/main
git rev-parse --short 'v0.7.2^{}'
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

## v0.7.2 released design

- Windows client 是 repository 正式功能，位於 `clients/windows/`，不是 profile-only workaround。
- Windows client 的 precheck 使用 `--check --yes --protocol 1`，取得完成 safe-fix 模擬後的 `preflight_token`；apply 必須帶同一 token。
- protocol apply 仍在 writer lock 內重建 DB-dependent preflight；任一層漂移都拒絕。
- client 不解析 human-readable output、不使用 Base64／remote temp、不自動接受 duplicate warnings。
- client source delete 是 post-commit、fail-soft；只刪除大小／時間／SHA-256 均未變且不是 reparse point 的同一路徑。
- PowerShell 5.1＋真實 SSH／passphrase／檔案匯入已在 Windows 筆電完成端到端驗證，後續兩日實際使用正常。

## 下一個正確工作項目

v0.7.2 release gate 已完成。下一階段依序處理：

1. 做一次有邊界的安全／穩定性 gate：安裝回退、read-only side effects、CI／版本相容、backup/undo/Quiz DB 權限與已知高風險 failure paths；通過後不要無限重跑同規模健檢。
2. 匯入預檢更新明細：任何 preflight（本機 `import --check`、一般 `import` 內建 check、Windows `Test-JpnoteFile`／`Import-JpnoteFile`）遇到同 stable key 更新／合併時，列出 type、display、stable key 與必要的主要欄位變更；Windows 只呈現 core/protocol 結果，不自行重算。
3. Quiz 高優先 UI／正確性：題數可直接輸入、自訂 50 等數值；是非題改 `○／×`；`reorder_4` 完整句；漢字洩題與同音詞唯一答案保護。
4. 手機 Quiz 架構 spike：手機 TUI／SSH 僅作備援，優先比較 Tailscale-only Web／PWA、受限 API、認證、session／斷線恢復與多裝置安全邊界，再決定正式實作。
5. 其後處理 Quiz 啟動效能、動態 loading、grammar 詳細頁 hanging indent、history polish 與其他既有 backlog。

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
