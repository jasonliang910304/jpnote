# jpnote 開發路線圖

最後更新：2026-09-12（Asia/Taipei）
正式 release/tag：v0.7.4；annotated tag 固定指向 release commit `d6c847180e466439560769d1567048f7b382a4fb`
正式安裝版本：0.7.5 candidate（2026-09-12 actual Arch gate PASS；release/tag 尚未建立）
目前開發位置：v0.7.4 release 完成且 tag 不移動；post-release HEAD=`115ce7df...`。使用者 working tree 已套用 v0.7.5 early-performance candidate，且 2026-09-12 actual Arch full regression／real-fzf／install／formal-DB immutability gate PASS；post-gate 8-item data correction 也已完成。尚未 commit/push/tag；下一步只剩同步最終 docs，然後 user-controlled release commit/push/CI/tag。GitHub 遠端變更一律由使用者親手處理；AI 僅做 read-only GitHub 查詢、隔離修改、測試與 patch 準備。

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
- post-release CI maintenance：`694b869` 拆分 PowerShell 5.1／7 jobs；`e0095ba` 同步 contract test；`28ba7ef` 將使用 POSIX `fcntl` 的 core/import protocol job 移到 Ubuntu。最終 protocol、Windows PowerShell 5.1、PowerShell 7 jobs 全部 PASS；不修改 runtime/schema，`v0.7.2` tag 維持在 `46644a1`。

## v0.7.3 — stability + recent small UX

### dev1 safety foundation — actual Arch gate PASS

1. Linux installer：staged revision、atomic `current` activation、launcher/revision rollback、installer lock、version/revisions/compat symlink guards、Python >= 3.10 preflight。
2. core read-only connection：current schema 直接 `mode=ro`＋`query_only`；缺 DB／舊 schema 只在 memory 建立／migration，不 chmod/recover/prune/migrate 實體 DB。
3. Quiz explicit DB path：外部既有 parent 不 chmod；app-owned default parent 維持 0700，quiz.db 維持 0600。
4. 新增 Linux core CI：Python 3.10＋3.13、compileall、完整 pytest、isolated installer smoke。

### dev2 recent UX — dev1 gate 後

5. 匯入預檢更新明細：dev2 implemented；所有 local/Windows check/import 入口共用 core `updates[]/changes[]`。
6. grammar romaji search：dev2 implemented；搜尋層建立可靠 kana-derived token，不改 schema、不猜漢字讀音。
7. Quiz 題數直接輸入：dev2 implemented；setup 可直接鍵入 1–100，既有 shortage flow 處理可用題庫不足。

### release gate

- actual Arch：dev2 targeted `10 passed`；完整 repository `455 passed, 18 subtests passed`；正式 DB install/read-only hash、mtime、mode 不變。
- Windows PowerShell 5.1＋SSH：0.7.3 install/reinstall、update-detail check、protocol、no-op import、來源刪除全部 PASS。
- schema 維持 core v5／Quiz v2；release tag 僅在 push 後 Core regression 與 Windows import client CI 都 success 時建立。

## v0.7.4 — Deep Audit correctness / safety

目標：先消除唯一 High finding 與會造成行為分歧／錯誤結果的 correctness Medium；不做大規模效能重構。

完成 scope：

1. restore/undo compatibility gate：future schema、foreign SQLite、migration 後不可用 schema 在正式 DB replace 前 fail closed；exact private copy 會再次驗證，避免 path replacement race。
2. `JpnoteCore` 純 read facade 全部走 `connect_readonly()`；Quiz default read source 一併 side-effect-free。
3. DB commit 後 Markdown export failure 明確區分為 post-commit failure；protocol 告知 DB 已提交，避免使用者重做 mutation。
4. attempt 同 event key 的 content identity／linked-entry ordering 統一。
5. relation reciprocal/inverse audit 改成 directed logical identity。
6. duplicate remap scalar merge 改為 deterministic precedence；有歧義時 fail closed。
7. legacy paste clipboard／stdin 統一 16 MiB strict UTF-8 ingest boundary；parser 演算法效能改善留到 v0.7.5。

完成 gate：上述反例已在 v0.7.3 baseline 重現並於 v0.7.4 candidate 消失；assistant clean-apply exhaustive gate PASS，actual Arch full regression `485 passed, 36 subtests passed`，0.7.3 → 0.7.4 正式 install 與 formal DB fingerprint immutability gate PASS。release commit `d6c847180e466439560769d1567048f7b382a4fb` 已 push，release-commit 與 tag-triggered Core regression／Windows import client CI 全綠；annotated `v0.7.4` 固定指向該 commit。core schema v5、Quiz schema v2、public import JSON schema 均維持不變。

## v0.7.5 — Performance & Architecture Cleanup

第一原則：**功能正常／資料安全／行為等價 > 架構漂亮 > 效能提升 > dead-code 瘦身**。Git rollback 只是最後保險，不能作為大改後再看有沒有壞的替代品。

### Early-performance release candidate — implemented in isolated checkout

因使用者在 869 vocabulary 時已明顯感受到 Quiz startup delay，先把高收益且可保持 fixed-seed output 等價的工作提前，不等待整個架構清理：

- Quiz vocabulary prepared pool：normalized safety features 一次建立；對稱 pair-safety 每 unordered pair 只檢查一次並建立 exclusion set；同一 source 的 MCQ／True-False 共用 safe candidates／meaning metadata。100／200／400 source 與 v0.7.4 fixed-seed identity hash 完全一致；fresh clean-applied 869-source candidate builder 約 0.95s（含 source hydration 約 1.05s）。
- shortage confirmation：直接 persist 第一次 immutable plan，不再重讀 core sources／重建題庫。
- `recent --days N`：包含今天的最近 N 個本機日曆日，與 `--date`／`--since` 互斥。
- romaji 長音 mora preservation＋canonical-direction equivalence；不對無上下文助詞 `は` 猜讀音。
- source/installer version 0.7.5 candidate；core schema v5／Quiz schema v2／public import schema 不變。
- artifact gate：final patch 在第二個由使用者 bundle 建立的 fresh checkout `git apply --check`、actual apply、`git diff --check`、19-path byte equality PASS；clean-applied targeted regression `133 passed`、compileall 與 isolated install smoke PASS。assistant 分段完整 suite 為 `494 passed, 1 skipped, 36 subtests`，唯一 skip 是容器缺 real fzf。
- actual Arch gate（2026-09-12）：real fzf `0.74.3`；完整 `495 passed, 36 subtests passed`。正式機 897 vocab／27 attempts read-only Quiz planning total 0.915s；0.7.4 → 0.7.5 install PASS；formal DB 1050/153/897/27、quick/FK PASS，SHA-256 `c0463ac4533cb691c92b1ca3ed0229ea3dc8551a537528a9621c275f136fba70`／size 1536000／mtime／mode gate 前後完全不變。gate 後正式匯入 8 個同-key data corrections（3 個 romaji＋5 個 origin metadata），再次 quick/FK PASS；DB SHA-256 更新為 `bb4dbf7943a6d87f2ac73ed5db1c88dc7568556c26e63ce76a86ecdedc46b6d9`，audit 剩 10 個刻意多例句 review＋`または` 1 個 fail-closed review。

這只是 Quiz O(N²) 的**第一階段 hot-path reduction**：為了完全保持既有 RNG/shuffle 輸出，仍會對每個 source 建立 ordered candidate sequence 並 shuffle；真正 asymptotic redesign 若會改 fixed-seed sequence，必須另立明確 generator-version／equivalence boundary，不在這個 early patch 偷改。

### v0.7.5 remaining work after early release

- 建立 reusable bulk read／immutable source snapshot／normalized indexes，讓 export、audit、preflight、search、Quiz 等不再各自重複 hydrate。
- Quiz source catalog／session planning 消除重複 full hydration；加入真正動態 loading。
- attempt identity：移除 repeated full-table scan／N+1，建立一次性 identity snapshot/index。
- export／import preflight／search/list/romaji-audit：遷移至 bulk hydration，加入 query-count 與 scaling regression。
- `parse_payload()`：處理 adversarial repeated `raw_decode` 超線性掃描；所有 ingest path 已在 v0.7.4 先有 hard size cap。
- fzf：處理 per-keypress subprocess/full normalization 的效能面；matching/ranking semantics 本身在 v0.7.6 統一。
- 對被新架構取代的舊 implementation 做 bounded cleanup：confirmed dead code 直接刪；superseded duplicate 先遷移 caller 再刪；migration/public API/installer fallback 等 compatibility-sensitive code 不因「看似沒用」就移除。
- release tooling UX：future actual-gate script 將 raw pytest 輸出完整寫 log，但 terminal 進度改用固定寬度／分組摘要，避免點狀 progress 因終端寬度換行。

剩餘工作可依風險拆成 0.7.5.x checkpoints；每個 checkpoint 都必須可獨立正常使用，不能依賴下一段才能恢復功能。

## v0.7.6 — Search + Quiz/UI correctness

- grammar derived-romaji ranking：`imasu` 不再因 substring 大量命中 `kimasu/shimasu/arimasu/moraimasu`；exact/whole variant 優先。
- core search 與 interactive fzf 共用同一 matcher/ranker source of truth。
- Quiz True/False 顯示 `○／×`；`reorder_4` feedback 顯示完整句並高亮 movable portion，保留無色 fallback。
- 保留並強化現有 kana-prompt homophone guard；基本同音詞安全已存在，不再當作「從零實作」項目。
- Quiz history export/delete TUI 入口與 history polish。
- grammar 詳細頁 numbered paragraph hanging indent／長段落 wrapping。
- fzf 未分類／mistake level 空值等一般 UX，以及 fuzzy duplicate candidate／確認流程。

## v0.7.7 — Crash / Filesystem / CI hardening

- backup/restore publication 的 parent-directory fsync。
- installer SIGKILL／stale lock／activation residue recovery。
- app-owned data/config path symlink chmod ownership policy。
- Windows CI path trigger 補齊 shared import-contract modules。
- GitHub Actions immutable SHA／test dependency provenance hardening。
- Quiz migration history backup、corrupt `.pending-*` audit/cleanup UX。

## v0.8.0 — Mobile / Web architecture

先完成 0.7.x correctness/performance/hardening，再擴張 frontend/trust boundary。優先 architecture spike：

- Tailscale-only Web/PWA，TUI/SSH 保留備援。
- 受限 API surface、authentication/authorization、CSRF/origin boundary。
- session resume、斷線恢復、多裝置 concurrency。
- Quiz/core DB isolation 與 mutation 權限。
- 是否讓 mimir 參與部署／服務層，需在正式設計後再決定。

## v0.8.x+ learning/data features

- `grammar_combinations` 結構化搭配。
- AI context 精簡匯出、romaji 分隔／外來語 origin 呈現改善。
- optional negative scoring／guess penalty。
- response timing、streak、familiarity、spaced repetition。
- radar chart、長期趨勢。

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

### 後續 Quiz／UI backlog 已整合進版本路線

- `○／×`、`reorder_4` 完整回饋、history export/delete、hanging indent 與 search/fzf correctness：排入 v0.7.6。
- 漢字意思題的基本 kana-prompt／homophone guard 已存在；後續只保留 regression 與必要強化，不再列為未實作 foundation。
- Quiz source snapshot/index、O(N²)、dynamic loading：排入 v0.7.5 Performance & Architecture Cleanup。
- fuzzy duplicate、AI context、`grammar_combinations`、romaji/origin 呈現等功能依上方 0.7.6／0.8.x+ 排程。

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
- 每次成功 dev gate／release 固定清理 obsolete patch/script/SHA/snapshot/temp/失敗 log；保留最新成功 log、DB safety backup 與 rollback/release artifact。失敗 gate 的診斷檔保留到後續成功清理。
