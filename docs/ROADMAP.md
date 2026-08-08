# jpnote 開發路線圖

最後更新：2026-08-08（Asia/Taipei）
正式 release/tag：v0.7.2；annotated tag 應指向本文件所在 release commit
正式安裝版本：0.7.2
目前開發位置：v0.7.2 release gate 完成；下一階段先做 bounded safety/stability gate，再進近期 Quiz／mobile backlog

## 0.7.2 高優先主軸 — completed

### A. stable stdin import protocol

- `jpnote import --stdin`／`jpnote import -` 共用既有 `_run_import_text()`；strict UTF-8、optional BOM、16 MiB 上限。
- `jpnote.import.v1` envelope 對 success/error 都提供固定 protocol/version/jpnote_version/ok/mode/status；wire JSON 使用 ASCII escape，避開 Windows PowerShell 5.1 code-page 污染。
- protocol check 回傳 `preflight_token`；Windows apply 帶回 token，並仍保留 writer lock 內的 DB preflight revalidation。
- legacy `--format json` 保持原本未包 envelope 的輸出，避免破壞既有 script。

### B. repository-owned Windows client

- 版本化 PowerShell module manifest、Install／Uninstall、README 與 native tests。
- PowerShell 5.1／7；同時安裝兩個使用者 module path，same-version reinstall 先備份且失敗可回復。
- strict UTF-8／JSON、本機 16 MiB、reparse point、檔案替換／修改與 SHA-256 guards。
- 原始 bytes 直接寫入 SSH stdin；不使用 clipboard、Base64 或遠端 temp file。
- review/conflict fail closed；只在 protocol success 與 token match 後詢問 `[y/N]` 刪除本機來源。

### C. test／release interaction budget

- 可在開發環境完成的 targeted、protocol、temporary DB、patch apply 與 script rehearsal 不再交給使用者。
- 使用者只跑一次完整 Arch repository gate、一次 Windows 5.1＋SSH 實機 gate、一次 final release gate。
- release verification：targeted `20 passed`；完整 Arch `421 passed, 18 subtests passed`；Windows PowerShell 5.1＋SSH 實機 gate 與後續兩日使用 PASS。


### D. Release completion

- versioned isolated install／stdin protocol smoke：PASS。
- 正式安裝 `jpnote 0.7.2`，正式 DB 安裝前後 SHA-256 相同；當次 read-only copy smoke 為 486 items／27 attempts、critical 0／needs_input 0。
- Windows PowerShell 5.1＋SSH real check/import/source cleanup：PASS，後續兩日實際使用正常。
- core schema v5、Quiz schema v2、public import JSON schema 均不變。

## Post-v0.7.2 next priorities

1. bounded safety/stability gate：installer rollback、read-only side effects、CI／版本相容、backup/undo/Quiz DB 權限與高風險 failure paths；通過後不無限重跑同規模 audit。
2. 匯入預檢更新明細：所有 preflight 入口對同 stable key 更新／合併顯示 type、display、stable key 與必要主要變更；Windows 使用 core protocol 結果。
3. Quiz 題數直接輸入／自訂值；再處理 `○／×`、`reorder_4` 完整句、漢字洩題＋同音詞唯一答案。
4. 手機 Quiz 架構 spike：TUI/SSH 僅備援，優先評估 Tailscale-only Web／PWA、受限 API、認證、session／斷線恢復、多裝置安全邊界。
5. Quiz 啟動效能／動態 loading、history polish、grammar 詳細頁 hanging indent 與其他既有 backlog。

## 0.7.1 高優先主軸 — completed

### A. multi-process writer／undo ordering — 第一階段已實作

- persistent advisory writer lock，不刪 lock file，process crash 由 kernel 自動釋放；拒絕 symlink／hard link／非一般檔案／非目前使用者擁有的 lock file。
- lock 覆蓋 mutation snapshot → transaction → export → backup publication。
- undo 覆蓋 target selection → recovery snapshot → restore → relocation → export。
- connect migration／orphan pending recovery、manual backup/init/export 走同一鎖。
- regression：兩個 process 同時寫入時，第二份 undo snapshot 必須包含第一個 process 已 commit 的狀態；正式 import apply 前在鎖內重驗 DB state，拒絕使用過期 preflight。

### B. import-first＋來源檔清理 — 第一階段已實作

- `jpnote import FILE` 使用單次驗證後來源快照。
- 成功後互動詢問刪檔，預設保留；`--delete-source`／`--keep-source` 可明確控制。
- 非互動／JSON 預設保留；check、dry-run、取消、失敗、no-selection 不刪。
- final symlink、來源替換／修改 fail closed；post-commit 刪檔錯誤、EOF／Ctrl-C 只保留來源並維持 import 成功。

### 已完成 gate

- clean `ca3e51e` 套用與 `git diff --check`：PASS。
- targeted regression：`16 passed`；完整 suite：`401 passed, 18 subtests passed`。
- temporary installed smoke：互動保留／刪除、noninteractive keep、explicit delete、check/failure no-delete、undo、backup/export/stats、writer-lock metadata：PASS。
- 正式 DB SQLite 副本：quick check／foreign key PASS；audit 無 critical／needs_input。

### Release completion

- 完整 regression：`401 passed, 18 subtests passed`。
- versioned isolated install、正式安裝與同版本 reinstall backup：PASS。
- 正式 DB 安裝前後 SHA-256 相同；quick check 與 foreign-key check：PASS。
- 正式 DB read-only copy smoke：453 items、27 attempts、critical 0、needs_input 0。
- annotated `v0.7.1` tag 應指向本文件所在 release commit。

## 已通過的前置 gate

- v0.6.6.4 stability gate：通過。
- core schema 維持 v5。
- Quiz 採獨立 `quiz.db`，目前 schema v2。
- 最新完整 regression：`378 passed, 18 subtests passed`。
- app-only coverage：`76%`。
- 隔離安裝 smoke 與 release-readiness audit：通過。
- post-release `jpnote paste --stdin`：功能 commit `74fb82a`；針對性測試 `13 passed`，temporary-data installed smoke 通過。

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

## Phase 5：Python-native TUI — 完成

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

### v0.7.0 release validation — 完成

- 正式 DB 一致 snapshot：quick_check、foreign_key_check、audit、stats 通過。
- read-only Quiz source catalog／mixed／vocabulary／mistake planning 未修改 core DB snapshot。
- v0.6.6.4 → v0.7.0 隔離 upgrade 通過，core DB 邏輯內容不變。
- 真實安裝、manual/config/stats、Quiz help 與 curses TUI 啟動／乾淨退出通過。
- launcher current-directory／`PYTHONPATH` shadow 已修正並有 regression tests。
- 正式資料：261 項、audit 0、pending relations 0；安裝後 quick/foreign-key checks 通過。

### post-v0.7.0 匯入 hotfix — 完成

- `jpnote paste` 預設 Wayland 剪貼簿行為不變。
- `jpnote paste --stdin` 從標準輸入取得完整 JSON。
- 所有來源共用既有 importer/preflight/mutation pipeline；沒有 schema 或 public JSON 變更。
- `tests/test_paste_stdin.py` 與既有相關測試共 `13 passed`。
- installed launcher 以 temporary `JPNOTE_DATA_DIR` 完成 read-only preflight 與正式匯入 smoke。
- `--file PATH` 暫不加入；現有 `jpnote import FILE` 已涵蓋檔案輸入。

### post-v0.7.0 搜尋／Quiz 啟動 maintenance — 完成

- fzf search reload 與 filter panel helper 改用 isolated Python bootstrap，installed 版不再依賴 cwd／`PYTHONPATH` 找到 `jpnote_app`。
- 新 bootstrap 維持 launcher path isolation，阻擋同名 shadow package。
- Quiz 按下開始或接受 shortage 後，先 refresh「正在準備題目……」再同步建立 session。
- Quiz 初始 question-event persistence 改用 `executemany()` batch insert；schema、snapshot 與 transaction 邊界不變。
- 新增 helper path-isolation 與 TUI loading-refresh regression tests。

### 下一個 checkpoint：使用回饋與 TUI polish

1. 是非題顯示改為 `○／×`，同步 question/feedback/history。
2. `reorder_4` 回饋顯示完整句子並高亮可重組片段，保留無色 fallback。
3. history export/delete TUI 入口、確認、刷新與空狀態。
4. TUI 錯誤訊息與空狀態 polish。
5. release artifact 自動化與 install/release script 整合。

### 一般功能 backlog

- 單字意思題降低漢字提示；使用假名 prompt 時，排除所有同讀音詞條的意思，無法保證唯一正解便 fallback 或跳過。
- fuzzy duplicate candidate／確認流程。
- AI context 精簡匯出。
- `grammar_combinations`／結構化搭配資訊。
- romaji 分隔與外來語語源欄位改善。
- fzf 多選、未分類顯示、mistake level 空值處理。
- multi-writer retry/serialization 與 attempt identity index optimization。

### 低優先／不阻塞 Quiz v1

- optional negative scoring／guess penalty。
- response timing、streak、familiarity、spaced repetition。
- radar chart、長期趨勢。

## 日常匯入安全規則

預設可持續使用 `jpnote paste`、`jpnote paste --stdin` 與 `jpnote import FILE`。只有在明確標示「先暫停匯入」時暫停；主要適用於正式 core DB migration/repair/restore、固定 DB 快照、正式安裝升級驗證或可能同時寫入 core DB 的測試。純 Quiz/repository/temporary-DB 測試不需暫停。

## 每階段驗收

- core 在 Quiz absent/disabled/broken 時完整可用。
- Quiz 寫入只進 Quiz store，不污染 core attempts。
- stable public IDs，不使用 SQLite row ID。
- 每一階段有 contract、fault-isolation、regression tests。
- 狀態或下一步變更時同步 handoff、roadmap、continuation prompt 與 audit。
