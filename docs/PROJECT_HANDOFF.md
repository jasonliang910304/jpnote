# jpnote 專案交接紀錄

最後更新：2026-08-08（Asia/Taipei）
正式 release/tag：`jpnote v0.7.2`；annotated tag 固定指向 release commit `46644a1ea329d15c85f35b897485763278aa0787`
正式安裝版本：`jpnote 0.7.2`
目前開發 checkpoint：v0.7.2 已發布；post-release Windows CI maintenance 已完成並全綠，release tag 維持指向 `46644a1`；下一步是 bounded safety/stability gate

用途：讓新的 ChatGPT 對話或新的開發工作階段，不依賴舊聊天內容也能直接接續工作。

---

## 1. 目前可信基準

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
- release tag：`v0.7.2`
- core SQLite schema：`5`
- public import JSON schema：v0.7.1 相容，v0.7.2 未新增欄位
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

## 3. 下一個正確工作項目

### v0.7.2 release completion

- actual Arch repository gate：`421 passed, 18 subtests passed`。
- versioned isolated install／stdin protocol smoke：PASS。
- 正式安裝 `jpnote 0.7.2`；安裝前後正式 DB SHA-256 相同；當次資料 486 entries／27 attempts，copy audit critical 0／needs_input 0。
- Windows PowerShell 5.1＋既有 SSH alias `jpnote`：實機 check/import/source cleanup 通過，且後續兩日使用正常。
- core schema v5、Quiz schema v2、public import JSON schema 均未變。

### v0.7.2 後近期高優先／使用回饋

1. 有邊界的安全／穩定性 gate：優先檢查 atomic revisioned installer／真正 rollback、read-only command side effects、CI／版本相容、backup/undo/Quiz DB 權限與已知高風險 failure paths；通過後停止同規模廣域健檢。
2. 匯入預檢更新明細：只要 preflight 有同 stable key 更新／合併，摘要後逐筆列 type、display、stable key，必要時顯示主要欄位變更；適用本機 `--check`、一般 import 內建 check、Windows `Test-JpnoteFile` 與 `Import-JpnoteFile`。
3. Quiz 題數支援直接輸入自訂數字，避免從預設 10 題反覆按到 50；需驗證正整數並清楚處理超過可用題數。
4. Quiz 是非題 presentation 改為 `○／×`；底層 `true／false` ID 維持不變，並同步即時回饋與 history。
5. `reorder_4` 回饋顯示包含固定題幹的完整句子；可重組片段使用 ANSI 高亮，並提供 `NO_COLOR` fallback。
6. 單字意思題降低漢字洩題；假名 prompt 必須排除所有同讀音詞條的意思，確保唯一答案。
7. 手機 Quiz 介面架構 spike：SSH/TUI 僅作臨時／備援，優先評估 Tailscale-only Web／PWA、受限 API、認證、session／斷線恢復與多裝置安全邊界。
8. Quiz 啟動效能／動態 loading、TUI history polish 與 grammar 詳細頁 hanging indent。

### 一般優先

8. 單字意思題降低漢字洩題；改用假名 prompt 時必須排除所有同讀音詞條的意思，確保選項只有一個可能正解。無法保證唯一答案時 fallback 顯示漢字、改題型或跳過。
9. fuzzy duplicate candidate／確認流程改善。
10. AI context 精簡匯出流程。
11. `grammar_combinations` 等結構化搭配資訊。
12. romaji 分隔與外來語語源欄位改善。
13. fzf 多選、未分類顯示與 mistake level 空值處理。
14. multi-writer busy timeout/retry/serialization 與 attempt identity index optimization。

### 低優先／不阻塞正常 Quiz

15. optional negative scoring／guess penalty。
16. response timing、streak、familiarity、spaced repetition。
17. radar chart／長期趨勢。

除非出現 blocking regression，不要重新啟動同規模 release audit；以針對性測試與一般維護為主。

---

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

完整順序以第 3 節為準；摘要如下：

- 已完成 maintenance：installed fzf helper path isolation、Quiz 開始前準備畫面與 batch session insert；v0.7.2 post-release CI 三個 jobs 已全綠。
- 高優先：是非題 `○／×`、重組完整句子／高亮、history export/delete、TUI polish、release/install 自動化。
- 一般優先：單字漢字洩題與同音詞唯一答案、fuzzy candidate、AI context、grammar combinations、romaji／語源、fzf／未分類／mistake level、多 writer／identity index。
- 低優先：負分制、response timing、streak、familiarity、spaced repetition、radar chart／長期趨勢。
- `paste --file PATH` 非必要；現有 `jpnote import FILE` 已提供檔案輸入，只有在能保持介面簡潔時才增加 alias。

---

## 6. 每個 checkpoint 與 release 的紀錄規則

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
