# jpnote 專案交接紀錄

最後更新：2026-07-24（Asia/Taipei）
目前程式基準：`jpnote v0.6.6.4`
用途：讓新的 ChatGPT 對話或新的開發工作階段，不依賴舊聊天內容也能直接接續工作。

---

## 1. 目前唯一可信基準

### 程式碼

- repository：本文件所在 Git repository
- release branch：`main`
- release tag：`v0.6.6.4`
- SQLite schema：`5`
- public import JSON schema：本版未新增欄位

### 使用者真實資料庫快照

本輪另以使用者提供的 `jpnote.db` **隔離副本**驗證：

- entries：240（grammar 93、vocabulary 147）
- senses：314
- attempts：27
- resolved grammar relations：22
- pending grammar relations：0
- `PRAGMA quick_check`：`ok`
- `PRAGMA foreign_key_check`：0 issues
- 內建 audit：0 non-info issues

任何健檢、migration、repair 或破壞性測試都必須先複製資料庫；不得直接修改使用者的真實 `~/.local/share/jpnote/jpnote.db`。

---

## 2. v0.6.6.4 Stability gate 結論

v0.6.6.3 廣域健檢找到的 Quiz 前 blocker 已集中修正，並完成 targeted regression、完整測試、coverage、安裝／升級 smoke 與真實 DB 副本驗證。

```text
pytest -q                             165 passed, 1 skipped, 12 subtests passed
python -m compileall -q jpnote_app    PASS
bash -n install.sh                    PASS
app-only coverage                     72%
```

唯一 skipped 項目是需要真實 `fzf` 的 integration test；不屬於本版修改範圍。

**Stability gate：通過。**

除非後續出現新的 blocking correctness／recovery regression，下一步不再做同規模廣域健檢，而是開始 Quiz 核心。

完整報告：

```text
docs/audits/v0.6.6.4-stability-gate.md
```

---

## 3. v0.6.6.4 已完成

### Relation edit 不再遺失資料

- manual edit 改為 logical diff/upsert。
- 不再用 `source_key OR target_key` 大範圍 delete/recreate。
- 未顯示在 editor payload 的 pending relations 會原樣保留。
- 未修改 relation 的 `source` 與 `created_at` 不會被洗掉。
- 使用者明確刪除一組 relation 時，只刪除該 logical pair 與必要的 reciprocal／inverse。

### SQLite connection lifecycle

- raw `sqlite3.connect()` helper 全部顯式 close。
- 關閉 GC 後重複 100 次 preflight，open file descriptors 不再線性成長。
- 這項修正是長駐 Quiz TUI／Web service 的必要前置條件。

### 共用 Safe Mutation Pipeline

新增 `jpnote_app.mutations.execute_safe_mutation()`，統一：

```text
pre-mutation snapshot
→ outer transaction
→ operation
→ commit
→ committed-state export
→ explicit close
→ publish/prune undo backup
```

已接入：

- CLI import／edit／delete
- attempt edit／delete／options migration
- repair／merge／romaji normalize
- public `JpnoteCore` mutation methods

Public import 會在實際 transaction connection 上重建 plan 並執行完整 preflight；blocking conflict 不可略過，疑似重複需明確 `accept_warnings=True`。若 DB 已 commit、之後 Markdown export 失敗，pre-mutation undo snapshot 仍會發布。

### Crash／undo／backup recovery

- `.pending-*` snapshot 名稱加入 owner PID。
- 下次 writable connect 會安全辨識 dead-process orphan snapshot 並提升為 active undo backup。
- 還活著的 process 所持有 snapshot 不會被誤收。
- corrupt pending snapshot 保留供人工檢查，不自動覆蓋資料庫。
- `jpnote undo --list` 可列出正常／損壞備份。
- `jpnote undo --backup NUMBER_OR_FILENAME` 可指定較舊版本。
- 預設 undo 會略過損壞的最新備份，選擇最新有效版本。
- 先驗證 target backup，再建立 recovery snapshot。
- active undo pool 與 recovery/restored auxiliary pool 各自受 50 MiB retention cap 管理。

### 其他 correctness 修正

- timestamp 改用 ISO-8601 microseconds，降低同秒新增／更新誤分類。
- 明確指定不存在的 `--item-key`、負數或超出範圍的 `--attempt-index` 會直接報錯，不再靜默 no-selection。

---

## 4. 已知但不阻塞 Quiz core 的 backlog

### P2：多 writer concurrency

單人 CLI transaction correctness 正常，但多程序同時寫入仍可能得到 `database is locked`。在 Web、GUI、背景同步或多 writer 模式推出前，必須加入 busy timeout、retry 或 serialization policy。

### P2：attempt identity matching 效能

大量既有 attempts 與大批 incoming attempts 的 identity comparison 仍可進一步索引化。使用者目前只有 27 筆 attempts，不阻塞 Quiz v1。

### P3：產品與操作改善

- relation／entry delete impact preview。
- 更完整的 backup 管理介面。
- Radar chart、response timing、熟悉度與間隔複習。

以上不得在沒有 blocking regression 的情況下延後 Quiz 核心。

---

## 5. 下一步：Quiz core

依 `docs/QUIZ_V1_SPEC.md` 執行：

1. 建立 optional、fault-isolated Quiz package/module。
2. 定義 stable public read services 與 capability model；禁止直接讀 SQLite table、internal CLI 或 row ID。
3. 建立獨立 Quiz session/history store，保存 immutable question snapshot。
4. 實作 capability-based generators 與安全 distractor／fallback 規則。
5. 建立 CLI/debug adapter。
6. 核心與 history 通過 contract、fault-isolation、resume／abandon、retention／export tests 後，再做 Python-native TUI。

第一版先完成題目生成與歷史紀錄；熟悉度／間隔複習低優先。

---

## 6. Quiz 硬性架構原則

- Quiz absent、disabled 或 broken 時，core jpnote 仍能 install、start、browse、import、audit、repair、export。
- Quiz code、commands、models/migrations、history、generators、renderers 與 tests 盡量隔離。
- Quiz 只能依賴 stable public/core service interfaces。
- Quiz schema/data 必須 optional、additive；停用或移除 Quiz 不得破壞 grammar／vocabulary／attempts。
- 使用 stable entry key、session ID、question-event ID，不使用 SQLite row ID。
- 既有 `attempts` 是可重播題目來源；live Quiz response 另存於獨立 history。
- 文法類學習練習不建立既有 jpnote `attempts`。

---

## 7. 每版強制交付與紀錄

每次 release 必須同步更新：

1. `CHANGELOG.md`
2. `README.md`
3. `docs/USER_GUIDE.md`
4. `docs/PROJECT_HANDOFF.md`
5. `docs/ROADMAP.md`
6. `docs/audits/vX.Y.Z-*.md`
7. `docs/CHATGPT_CONTINUATION_PROMPT.md`
8. `docs/RELEASE_CHECKLIST.md`
9. 若 Quiz 行為有變，更新 `docs/QUIZ_V1_SPEC.md`
10. Git commit、release tag、可套用更新檔與 SHA-256

交付物固定分為：

- **必須下載**：正常只提供一個可套用更新檔。
- **僅供參考／備援**：audit、SHA、bundle、單獨文件。
- **新聊天續接用**：最新版 continuation prompt。

詳見 `docs/DELIVERY_GUIDE.md`。

---

## 8. 新對話接手時的最短流程

```bash
git status
git log --oneline --decorate -5
git tag -n
python -m compileall -q jpnote_app
bash -n install.sh
pytest -q
```

接著依序閱讀：

```text
README.md
CHANGELOG.md
docs/PROJECT_HANDOFF.md
docs/ROADMAP.md
docs/QUIZ_V1_SPEC.md
docs/audits/v0.6.6.4-stability-gate.md
docs/CHATGPT_CONTINUATION_PROMPT.md
```

不要重新詢問已在 Quiz 規格中定稿的需求，也不要在沒有 blocking regression 時再用廣域健檢無限延後 Quiz。
