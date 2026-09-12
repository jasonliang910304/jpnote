# jpnote 專案交接紀錄

最後更新：2026-09-12（Asia/Taipei）
正式 release/tag：`jpnote v0.7.4`；annotated tag 固定指向 release commit `d6c847180e466439560769d1567048f7b382a4fb`
正式安裝版本：`jpnote 0.7.5` candidate（2026-09-12 actual Arch gate PASS；尚未 release/tag）
目前開發 checkpoint：正式 release/tag 仍是 v0.7.4；使用者本機 repository 仍以 `115ce7df2618e8e8b53be9d1f977a55700c9a65c` 為 HEAD，但已套用未 commit 的 v0.7.5 early-performance patch，且正式安裝版本已是 0.7.5 candidate。2026-09-12 actual Arch full regression／real-fzf／install／formal-DB immutability gate 全 PASS；post-gate data correction 也已完成。下一步只剩同步最終 docs、由使用者 review/commit/push，等待 CI 成功後再建立 v0.7.5 annotated tag。`v0.7.4` tag 不移動。AI 不修改 GitHub 遠端。

用途：讓新的 ChatGPT 對話或新的開發工作階段，不依賴舊聊天內容也能直接接續工作。

---

## 1. 目前可信基準

### 2026-09-12 v0.7.5 early-performance candidate（actual Arch PASS；尚未 release）

```text
exact parent/main=115ce7df2618e8e8b53be9d1f977a55700c9a65c
user bundle SHA-256=ee80c4279aa7aac4c9cd413e14e25745c608a71bd9f72ab4fe9f643b4bfe7300
source VERSION=0.7.5 candidate
formal installed version=0.7.5 candidate; formal release/tag=0.7.4
core schema=5
Quiz schema=2
public import JSON schema=unchanged
GitHub writes=none
```

本 candidate 先提前處理使用者已明顯感受到的 Quiz 啟動延遲，不等待整個 v0.7.5 architecture cleanup：

- vocabulary generator 對每個 entry 的 normalized names／reading／meaning／review-group features 只建一次；safe-pair 因為規則對稱，只檢查 unordered pair 一次並建立 exclusion sets；同一 source 的不同題型重用 candidates／meaning metadata。仍保留原 candidate 順序與 RNG/shuffle 語意。
- shortage confirmation 改為持久化第一次已呈現給使用者的 immutable `QuestionPoolPlan`，不再第二次讀 core source／重建題庫。
- 新增 `jpnote recent --days N`，以本機日曆日期計算並包含今天；`--days 2`＝今天＋昨天，且與 `--date`／`--since` 互斥。
- romaji converter 修正已形成長音後又吞掉下一個獨立 mora 的問題；equivalence 以 reading-derived canonical 單向判定，避免少 mora 值被 stored-side expansion 誤判為等價。無上下文助詞 `は` 仍 fail closed，不猜成 `wa`。

真實 869-vocabulary snapshot 的 assistant-isolated benchmark（同 Python/container、fixed seed）：

```text
source count   v0.7.4 builder   v0.7.5 candidate   identity SHA-256 equal
100            0.557s           0.058s              yes
200            2.867s           0.210s              yes
400            10.429s          0.530s              yes
869            old full run exceeded bounded tool window; candidate 0.948s
candidate 869 hydration + build ≈ 1.048s
```

100／200／400 的 selected question identity hash 與 baseline 完全一致；另有 prepared-vs-legacy variant regression、homophone/alias/meaning/review-group collision coverage 與 feature/pair-count scaling regression。assistant 分段 repository gate 已覆蓋全部 **495 collected tests**：`494 passed, 1 skipped, 36 subtests passed`；唯一 skip 是容器沒有 real fzf。Quiz 全模組 `205 passed, 6 subtests`；isolated installation/path tests 亦逐項 PASS。最終 patch 已在第二個由同 bundle 建立的 fresh checkout 上 `git apply --check`／實際 apply／`git diff --check` PASS，19 個變更檔與開發 worktree逐 byte 相同；clean-applied targeted regression `133 passed`、compileall／source version／Quiz help／`recent --days` help／isolated 0.7.5 install smoke 全 PASS。**2026-09-12 actual Arch gate 亦 PASS**：real fzf `0.74.3`；完整 repository `495 passed, 36 subtests passed`；read-only Quiz planning 為 897 vocabulary／27 attempts、available 4918、selected 10、hydrate 0.116s、build 0.800s、total 0.915s；0.7.4 → 0.7.5 formal install PASS。正式 DB 為 1050 items（153 grammar／897 vocabulary）、27 attempts，`quick_check=ok`、FK violations 0；gate 前後 SHA-256 `c0463ac4533cb691c92b1ca3ed0229ea3dc8551a537528a9621c275f136fba70`、size 1536000、mtime/mode 完全不變。

2026-09-07 正式 DB content correction 已由使用者在 v0.7.4 完成：16 個同-key updates，1019 items／150 grammar／869 vocab／27 attempts 維持不變。2026-09-12 actual DB 已成長至 1050 items／153 grammar／897 vocabulary／27 attempts；v0.7.5 gate 後又完成 8 個同-key corrections：`定員`、`経営方針`、`騒音` canonical romaji，以及 `アンケート`、`セーター`、`プラン`、`プレゼン`、`ボウリング` origin metadata。正式匯入後 `quick_check=ok`、FK violations 0、DB SHA-256=`bb4dbf7943a6d87f2ac73ed5db1c88dc7568556c26e63ce76a86ecdedc46b6d9`；audit 只剩 11 個 review：10 個已確認刻意保留的同-meaning不同非空例句，以及 `vocab:または` 的 `ma ta wa ↔ ma ta ha` fail-closed review。不要用無上下文 converter 自動把 `または` 覆寫成 `ma ta ha`。

Release tooling UX note（2026-09-12 使用者回饋）：raw `pytest -q` 的點狀 progress 會依測試批次長度造成不等寬／終端換行。未來產生 actual-gate script 時，保留完整原始 pytest output 到 log，但終端優先顯示固定寬度或分組式進度摘要；這是 gate tooling UX，不需要修改產品 runtime。

v0.7.5 本輪完整開發／benchmark／coverage／actual gate／data follow-up 記錄：`docs/audits/v0.7.5-performance-development.md`。

### 2026-09-06 v0.7.4 release baseline

```text
branch=main
release commit=d6c847180e466439560769d1567048f7b382a4fb
v0.7.4^{}=d6c847180e466439560769d1567048f7b382a4fb
release tag object=1c0cebf3a9d38e16b7027fd77e6f8a59c649efd6
post-release main=release commit + handoff-only documentation sync
working tree=clean after handoff commit
CI=release-commit Core regression PASS；Windows import client PASS；tag-triggered Core regression PASS；Windows import client PASS
```

Actual Arch release gate：`485 passed, 36 subtests passed`；0.7.3 → 0.7.4 installed upgrade PASS；正式 DB 安裝前後 SHA-256／size／mtime／mode 完全不變。真實 DB 副本 1019 items（150 grammar／869 vocabulary）、27 attempts，audit 29 review／0 critical；read-only Quiz planning、installed protocol import、SQLite quick_check／foreign_key_check 全部 PASS。

### 2026-08-09 v0.7.3 release baseline

```text
branch=main
release commit=6dc8e8729c64c64933a7ff6d568b321b5cb26889
v0.7.3^{}=6dc8e8729c64c64933a7ff6d568b321b5cb26889
current main=release commit + handoff-only documentation sync
working tree=clean
CI=Core regression PASS；Windows import client PASS
```

release log：`/home/jasonliang/Projects/jpnote-development-logs/v0.7.3-release-20260809T143136.log`。

### 2026-08-08 release／maintenance baseline

```text
branch=main
v0.7.2^{}=46644a1ea329d15c85f35b897485763278aa0787
post-release CI code checkpoint=28ba7efb68aede3ed6e27fa51bfe34431b4e708c
current main=以上 checkpoint ＋本次 handoff-only documentation sync
working tree=clean
```

上一個 release 基線：`v0.7.1`＝`e5ac8a800061c950f25586b28dd2c8c51c0d7850`。

狀態不明、因 Work 額度耗盡的工作一律視為失敗／未完成，不可算入基線。

### 0.7.2 completed release scope

- 高優先：把 Windows 遠端匯入改為 repository-owned、versioned client，而不是 PowerShell profile／聊天附件中的孤立 helper。
- core 新增 `jpnote import --stdin`／`jpnote import -`、16 MiB bounded strict UTF-8 transport 與 `jpnote.import.v1` JSON protocol。
- protocol check 以 SHA-256 `preflight_token` 綁定 normalized plan 與相關 DB outcome；正式 apply 前若 token 或 writer-lock 內重建結果不同便 fail closed。
- Windows module 支援 PowerShell 5.1／7、OpenFileDialog、SSH stdin、遠端 protocol validation、review/conflict fail closed，以及匯入成功後的本機來源安全刪除。
- module／installer／uninstaller 位於 `clients/windows/`；GitHub Actions 的 core/import protocol tests 跑 `ubuntu-latest`，Windows PowerShell 5.1／PowerShell 7 client 與 install/reinstall/uninstall tests 跑 Windows runner。
- 不使用剪貼簿、Base64 或遠端暫存檔；core schema v5、Quiz schema v2、public import JSON schema 均不變。
- 新功能 targeted：`20 passed`；完整 Arch regression：`421 passed, 18 subtests passed`；versioned isolated install 與正式 install/DB hash/read-only smoke PASS；Windows PowerShell 5.1＋SSH 實機匯入及後續兩日使用 PASS。
- release push 後 CI maintenance 已完成：`694b869` 將 PowerShell 5.1／7 拆成明確 jobs；`e0095ba` 同步舊 matrix contract test；`28ba7ef` 將依賴 POSIX `fcntl` 的 core/import protocol job 移到 Ubuntu。最終 `protocol`、Windows PowerShell 5.1、PowerShell 7 三個 jobs 全部 PASS；這些皆為 release 後 CI-only maintenance，`v0.7.2` tag 未移動。

### 0.7.1 completed release scope

- 高優先：core multi-process writer／undo lock。
- 高優先：一般學習改為 `jpnote import FILE`，成功後可選擇刪除來源檔。
- `paste --stdin` 保留 SSH／pipe 備用。
- 實作前固定做風險預演；本階段已特別處理 snapshot/commit ordering、undo race、確認後 DB drift、lock-file symlink/hard-link、來源替換、in-place modification、非互動卡住、cleanup prompt 中斷與 post-commit cleanup failure。
- 程式版本與正式安裝皆為 0.7.1；本文件所在 commit 為 v0.7.1 release commit。
- 桌機 targeted regression：`16 passed`；完整 regression：`401 passed, 18 subtests passed`。
- 隔離 installed smoke：launcher/manual/init、explicit keep/delete、noninteractive keep、check/failure no-delete、undo、backup/export/stats、writer-lock metadata 與互動 `[y/N]` 全部 PASS。
- 正式 DB SQLite 副本：quick check PASS、foreign-key violations 0、453 items、27 attempts；audit 342 info `missing_accent`＋1 review `possible_origin_missing`，無 critical／needs_input。

### 正式 release

- branch：`main`
- release tag：`v0.7.4` → `d6c847180e466439560769d1567048f7b382a4fb`
- core SQLite schema：`5`
- public import JSON schema：維持相容；v0.7.4 未新增欄位
- v0.7.0 release gate：通過
- post-release 功能 commit：`a660950`（是非題回饋標籤釐清）、`74fb82a`（`jpnote paste --stdin`）
- 最新 maintenance checkpoint：installed fzf helper 以 isolated bootstrap 啟動；Quiz 開始前立即顯示準備畫面，session 題目寫入改用 batch insert。

### Quiz v1／v0.7.0 release scope

目前 repository 已依序完成：

1. Phase 1：optional Quiz package、stable read contracts、fault isolation。
2. Phase 2：獨立 `quiz.db`、session/history、pause/resume/abandon、100 MiB detail retention、JSON export。
3. Phase 3：安全 generators、distractor/fallback、question pool、mixed/vocabulary/mistake modes。
4. Phase 4：headless service/debug adapter、lifecycle recovery、source detail feedback、Quiz schema v2。
5. Phase 5：Python-native curses TUI、usability/question-quality、正式 `jpnote quiz` CLI／config、互動式 JLPT/source filters、history navigation、逐題紀錄檢視與隔離安裝 smoke。

目前已驗證：

```text
python -m compileall -q jpnote_app tests    PASS
pytest -q                                  378 passed, 18 subtests passed
app-only coverage                          76%
isolated installed smoke                   PASS
release-readiness audit                    PASS
bash -n install.sh                          PASS
git diff --check                           PASS
```

Quiz 使用獨立 SQLite：

```text
core data:  ${JPNOTE_DATA_DIR:-~/.local/share/jpnote}/jpnote.db   schema v5
quiz data:  ${JPNOTE_QUIZ_DB:-~/.local/share/jpnote/quiz.db}      schema v2
```

Quiz history 不寫入既有教材 `attempts`。

### post-v0.7.0 匯入 hotfix

- `jpnote paste` 維持從 Wayland 剪貼簿讀取。
- `jpnote paste --stdin` 可從標準輸入讀取完整 JSON，適合 SSH／pipe。
- 剪貼簿與 stdin 只在輸入取得層分流；兩者之後都進入既有 `_run_import_text()`，共用解析、schema 驗證、重複偵測、完整預檢、確認、安全整理、備份與正式匯入流程。
- 沒有修改 core/Quiz schema，也沒有修改 public import JSON schema。
- 新增 `tests/test_paste_stdin.py`；針對性測試共 `13 passed`。
- installed-command smoke 已以 temporary `JPNOTE_DATA_DIR` 驗證 `--help`、read-only `--check --format json`、`--yes` 正式匯入與 `stats`。
- 實際網路 SSH 尚待出差前由 Windows 筆電做一次端到端 smoke；本機 pipe／installed launcher 路徑已通過。

### post-v0.7.0 搜尋／Quiz 回應 maintenance
- 修正 installed launcher 下 fzf reload/filter helper 以新的 Python 子程序啟動時找不到 `jpnote_app` 的 regression。
- helper 子程序現在比照主 launcher 使用 `python -I`、明確 installed app root 與 `runpy.run_module()`；不依賴 cwd 或 `PYTHONPATH`。
- 搜尋 reload 與 Ctrl-F filter panel 共用同一個 isolated helper bootstrap。
- Quiz 從設定或 shortage 確認開始 session 前，curses 會先 refresh「正在準備題目……」，避免同步建題期間看似凍結。
- Quiz session 的 question-event 初始寫入由逐筆 `execute()` 改為同一 transaction 內 `executemany()`，不改 schema 或 history snapshot 語意。
- 新增 path-isolation 與 loading-refresh regression tests；本 checkpoint 不接觸 core DB schema／public JSON schema。

---

## 2. 已完成的 Quiz 行為

### 資料與故障隔離

- core 啟動路徑不依賴 Quiz。
- Quiz 只透過 stable public read service 取得 entry snapshot 與 replayable attempts。
- 禁止依賴 core SQLite row ID、core repository internal 或 CLI private handler。
- Quiz import/runtime/storage failure 不應阻止 core browse/import/audit/repair/export。

### Session 與 history

- 狀態：`active`、`paused`、`interrupted`、`completed`、`abandoned`。
- 每題逐筆持久化；resume 使用原本 immutable question snapshot。
- skip 視為 incorrect，並保存事件。
- session summary 與各題型摘要永久保留；details 受 100 MiB cap 管理。
- 支援 history export、pruning 與安全刪除。

### 題目生成

- vocabulary：日文↔中文四選一、意思是非、讀音是非。
- mistake：multiple-choice replay、`reorder_4` replay、可安全還原時的 true/false replay。
- MCQ distractor 不足時 fallback true/false，再不足就 skip。
- 漢字詞的意思題在不造成同音歧義時優先以假名作 prompt，降低中文字形提示。
- 錯誤讀音只使用長音、促音、撥音等細微陷阱；禁止拿無關詞彙讀音充當假答案。

### TUI

- 設定畫面支援 mixed/vocabulary/mistake 與題數。
- Enter/Space 依序移動「模式 → 題數 → 開始」，不再直接修改目前值。
- 作答支援方向鍵、Space、Enter、數字鍵、skip、details、pause/quit。
- `reorder_4` 顯示 Backspace 退回提示。
- 答對、答錯、skip 都顯示實際正解；答對也能確認是否猜中。
- 使用 terminal default background，保留 Kitty 等終端原有透明度；已接入 config 開關。
- 正式 `jpnote quiz` 透過 lazy loader 啟動；Quiz import/runtime failure 不阻止其他 core CLI 指令。
- config 支援預設 mode/count、JLPT levels、sources、透明背景、history detail cap 與 session 後 pruning。
- CLI 可用 `--mode`、`--count`、`--level`、`--source` 覆寫單次 Quiz 設定。
- TUI 內可用多選畫面調整 JLPT／來源條件；空選擇代表全部。
- TUI history 可瀏覽 recent summaries、查看結果摘要、繼續未完成 session。
- history 可切換僅顯示答錯／跳過紀錄，並顯示或隱藏 abandoned session。
- history summary 可進入逐題清單，查看每題題目、選項、使用者答案、正解、結果與目前來源詳情；details 已 pruning 時明確只保留摘要。
- 隔離安裝 smoke 已驗證完整 Quiz package、lazy loader、fresh init/stats、reinstall launcher backup、manual path 與 Quiz 缺失時的 core failure isolation。
- installed launcher 使用 `python3 -I` 與明確 versioned app path；repository/current-directory 與 `PYTHONPATH` shadow regression 已通過。

---

## 3. 目前正確工作項目

### v0.7.4 Deep Audit correctness / safety — released

parent baseline：`851e77add870e2a19fcbe674860828ecccf81852`（v0.7.3 release 後 final handoff main）。release commit：`d6c847180e466439560769d1567048f7b382a4fb`；annotated `v0.7.4` 固定指向該 commit。2026-09-06 actual Arch 正式 install/data gate、release-commit CI 與 tag-triggered CI 全部 PASS。

Deep Adversarial Audit 已完成：Blocking 0、High 1、Medium 16、Low–Medium 2，共 19 findings；沒有證據顯示正式學習 DB 已損壞。v0.7.4 先處理 correctness/safety，不把 performance architecture 與 UI 全塞進同一版。

v0.7.4 completed scope：

1. restore/undo compatibility gate：future schema／foreign SQLite／migration 後不可用結構在 replace 前拒絕；restore 對 exact private copy 再驗一次，避免 precheck/path replacement race。
2. `JpnoteCore` 純讀 API 改用 `connect_readonly()`，Quiz default read facade 一併 side-effect-free。
3. post-commit Markdown export failure 以 `PostCommitExportError` 明確告知 DB 已提交；protocol additive 回報 `database_committed=true`。
4. attempt 同 event key 的 linked-entry set semantics 與 batch duplicate comparison 統一。
5. relation reciprocal/inverse audit 使用 directed logical identity。
6. duplicate remap scalar merge deterministic；existing/explicit target 有明確 precedence，無 canonical 可判定時 fail closed。
7. legacy paste clipboard/stdin 與正式 import 共用 16 MiB strict UTF-8 ingest boundary；parser 演算法效能留 v0.7.5。

此 release 不修改 core schema v5、Quiz schema v2 或 public import JSON schema。

Assistant-side clean-apply gate 已完成：patch 由 exact `851e77...` baseline 產生，並在另一份由 v0.7.3 bundle 重建的 clean checkout 通過 `git apply --check`、actual apply、`git diff --check`、compileall、shell syntax、targeted regressions與 isolated installer regressions；完整 collection 485 tests，分段 exhaustive run 為 484 passed、1 skipped（assistant 環境無 real fzf）、36 subtests passed。

2026-09-06 actual Arch gate 亦已完成：一次性 `pytest -q` 為 `485 passed, 36 subtests passed`，real-fzf integration 也 PASS。正式 0.7.3 → 0.7.4 install、version/help/manual/Quiz-help、isolated installed protocol import、quick_check／foreign_key_check 全 PASS；正式 DB fingerprint（SHA-256 `7bf1bd5b0f45eb7c67fe665573a900ddd2e89f31a272a09f2ee17b4a47b0f182`、size 1486848、mtime、mode）安裝前後完全不變。真實 DB 副本 stats：1019 items（150 grammar／869 vocabulary）、27 attempts；audit 29 review、0 critical；Quiz planning 869 vocabulary sources／27 attempt sources、available 4764、selected 10。

GitHub release 流程已完成；release 後只做 handoff-only documentation sync，`v0.7.4` tag 不移動。下一個 runtime 工作直接進 v0.7.5 Performance & Architecture Cleanup。

### v0.7.5+ 已整合 roadmap

- v0.7.5：Performance & Architecture Cleanup。功能等價/資料安全優先；shared snapshot/bulk hydration、attempt identity index、Quiz O(N²)/重複 hydration、export/preflight N+1、parser、fzf performance，並清除被新架構取代且可證明安全移除的 dead/obsolete code。若過大可拆 0.7.5.1/2/3/4，每個 checkpoint 都必須獨立可正常使用。
- v0.7.6：grammar romaji exact/ranking、core/fzf matcher 一致、Quiz `○／×`、`reorder_4` 完整句、history UI、grammar hanging indent 等 correctness/UI。現有 homophone guard 已有基本實作，只保留強化/regression。
- v0.7.7：parent-directory fsync、installer SIGKILL/stale lock、symlink chmod ownership、Windows CI trigger、Actions/dependency provenance、其他 storage hardening。
- v0.8.0：Tailscale-only Web/PWA/mobile architecture spike，再決定受限 API、認證、session/斷線、多裝置 concurrency 與 mimir 角色。
- v0.8.x+：grammar combinations、AI context、romaji/origin 呈現、SRS/timing/趨勢等學習功能。

詳細順序以 `docs/ROADMAP.md` 為準。

## 4. 日常資料匯入與開發並行規則

使用者會持續匯入日文文法與單字資料。預設情況下可以正常使用：

```bash
jpnote paste
jpnote paste --stdin --check
jpnote import FILE
jpnote browse
```

下列工作**不需要暫停匯入**：

- 純 repository 程式修改與 unit tests。
- 使用 temporary `JPNOTE_DATA_DIR` 或 temporary `JPNOTE_QUIZ_DB` 的測試。
- Quiz generator/TUI/debug 測試。
- 文件更新。

只有在回覆中明確標示「先暫停匯入」時才暫停，典型情況包括：

- 對正式 core DB 執行 migration、repair、restore 或 upgrade smoke。
- 複製正式 DB 前需要固定一致快照。
- 執行 `./install.sh` 並驗證正式安裝版本的短暫窗口。
- 任何可能同時寫入正式 `jpnote.db` 的多程序測試。

任何破壞性、migration、repair 或 fuzz 測試都必須使用隔離副本，不得直接修改正式 `~/.local/share/jpnote/jpnote.db`。

---

## 5. 已知 backlog

完整 backlog 已去重並整合到 `docs/ROADMAP.md` 的 v0.7.4 → v0.8.x 排程。特別注意：

- 不再把已完成的 atomic/revisioned installer、read-only connection helper、basic homophone guard、Quiz numeric count、static loading hint、session batch insert、writer serialization foundation 等舊資料重新列為待辦。
- performance findings 必須在 v0.7.5 以共用 architecture 解決，不以零散 query 微調取代 root-cause cleanup。
- dead code cleanup 僅在 caller 遷移與 contract/equivalence test 後進行；migration/public API/installer fallback 等 compatibility-sensitive 路徑需有保留理由或明確 deprecation。
- Deep Audit 其餘 durability/hardening findings照 v0.7.7 排程，不因沒有 Blocking 就遺忘。

## 6. 每個 checkpoint 與 release 的紀錄規則

每次開發的固定 hygiene：成功 gate／release 後，清理已失去用途的 patch、validation script、SHA sidecar、obsolete snapshot、stale temp dir 與已被成功結果取代的失敗 log；保留當前成功 validation log、正式 DB safety backup、active rollback artifact／release bundle。若 gate 失敗，先保留診斷所需檔案，修正後成功才清。

每個會改變「目前完成範圍、下一步、schema、測試基線或重要規格」的開發 checkpoint，至少同步更新：

1. 對應 `docs/audits/*-development.md` 或 checkpoint audit
2. `docs/PROJECT_HANDOFF.md`
3. `docs/ROADMAP.md`
4. `docs/CHATGPT_CONTINUATION_PROMPT.md`
5. 規格行為有變時更新 `docs/QUIZ_V1_SPEC.md`

正式 release 另必須同步更新：

- `CHANGELOG.md`
- `README.md`
- `docs/USER_GUIDE.md`
- `docs/RELEASE_CHECKLIST.md`
- release audit、version、install script、release tag、patch 與 SHA-256

---

## 7. 新對話接手流程

```bash
git status
git log --oneline --decorate -10
git tag --sort=-creatordate | head -n 15
jpnote --version
python -m compileall -q jpnote_app tests
bash -n install.sh
pytest -q
```

依序閱讀：

```text
README.md
CHANGELOG.md
docs/PROJECT_HANDOFF.md
docs/ROADMAP.md
docs/QUIZ_V1_SPEC.md
docs/audits/quiz-development-handoff-2026-07-24.md
docs/CHATGPT_CONTINUATION_PROMPT.md
```

不要重新詢問已定稿需求；不要在沒有 blocking regression 時重啟同規模廣域健檢。
