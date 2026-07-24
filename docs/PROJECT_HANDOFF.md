# jpnote 專案交接紀錄

最後更新：2026-07-24（Asia/Taipei）
正式 release 基準：`jpnote v0.6.6.4`
目前開發 checkpoint：Quiz Phase 5 互動式篩選／history navigation 完成

用途：讓新的 ChatGPT 對話或新的開發工作階段，不依賴舊聊天內容也能直接接續工作。

---

## 1. 目前可信基準

### 正式 release

- branch：`main`
- release tag：`v0.6.6.4`
- core SQLite schema：`5`
- public import JSON schema：v0.6.6.4 相容，Quiz 開發未新增欄位
- stability gate：通過

### Quiz 開發 checkpoint

目前 repository 已依序完成：

1. Phase 1：optional Quiz package、stable read contracts、fault isolation。
2. Phase 2：獨立 `quiz.db`、session/history、pause/resume/abandon、100 MiB detail retention、JSON export。
3. Phase 3：安全 generators、distractor/fallback、question pool、mixed/vocabulary/mistake modes。
4. Phase 4：headless service/debug adapter、lifecycle recovery、source detail feedback、Quiz schema v2。
5. Phase 5：Python-native curses TUI、usability/question-quality、正式 `jpnote quiz` CLI／config，以及互動式 JLPT/source filters 與 history navigation。

目前已驗證：

```text
python -m compileall -q jpnote_app tests    PASS
pytest -q                                  365 passed, 18 subtests passed
bash -n install.sh                          PASS
git diff --check                           PASS
```

Quiz 使用獨立 SQLite：

```text
core data:  ${JPNOTE_DATA_DIR:-~/.local/share/jpnote}/jpnote.db   schema v5
quiz data:  ${JPNOTE_QUIZ_DB:-~/.local/share/jpnote/quiz.db}      schema v2
```

Quiz history 不寫入既有教材 `attempts`。

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

---

## 3. 下一個正確工作項目

### Phase 5 安裝整合與 release readiness

下一個 checkpoint 應完成：

1. source-tree `python -m jpnote_app quiz` smoke。
2. 使用隔離安裝前綴的 installer/package smoke。
3. installed `jpnote quiz`、core command 與 Quiz failure-isolation smoke。
4. TUI history per-question view、export/delete 入口是否納入 v1 的最後範圍確認。
5. 同步 README、USER_GUIDE、CHANGELOG、release checklist 與 health-check；暫不建立正式 `v0.7.0` tag。

進行正式安裝／升級 smoke 前，必須先明確提醒使用者短暫停止日常資料匯入。負分／猜題扣分仍屬後期 optional scoring backlog，不阻塞 v1。

---

## 4. 日常資料匯入與開發並行規則

使用者會持續匯入日文文法與單字資料。預設情況下可以正常使用：

```bash
jpnote paste
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

### Quiz v1 尚待完成

- TUI history per-question view，以及 export/delete 是否納入首版的最後決策。
- 正式安裝／升級流程與 package smoke。
- release 文件、coverage、fresh install/upgrade smoke、真實 DB 副本驗證。

### 低優先

- 可選負分／猜題扣分。
- response timing、streak、熟悉度、spaced repetition。
- radar chart／長期趨勢。
- 多 writer busy timeout/retry/serialization。

---

## 6. 每個 checkpoint 與 release 的紀錄規則

每個會改變「目前完成範圍、下一步、schema、測試基線或重要規格」的開發 checkpoint，至少同步更新：

1. 對應 `docs/audits/quiz-*-development.md`
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
