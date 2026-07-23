# jpnote 專案交接紀錄

最後更新：2026-07-24（Asia/Taipei）  
目前程式基準：`jpnote v0.6.6.3`  
用途：讓新的 ChatGPT 對話或新的開發工作階段，不依賴舊聊天內容也能直接接續工作。

---

## 1. 目前唯一可信基準

### 程式碼

- 本地 Git repository：本文件所在 repository
- 分支：`main`
- v0.6.6.3 release baseline commit：`f3a95b2`
- release tag：`v0.6.6.3`
- 原始發布包 SHA-256：
  - `65a87294f8c703d580ddae692b4aec800ed8da2e273af74dbb2abf9ce1c6972e`

### 真實資料庫快照

本次交接時另有一份使用者實際資料庫快照：`jpnote.db`。

- SHA-256：`98f6cadfed28fd4541457df199be964c0dde772c436c69b3a5b71761c73270f3`
- metadata schema version：`5`
- entries：240
  - grammar：93
  - vocabulary：147
- attempts：27
- resolved grammar relations：22
- pending grammar relations：0
- `PRAGMA quick_check`：`ok`
- `PRAGMA foreign_key_check`：0 issues

注意：任何健檢或修復都先複製資料庫，在隔離副本上執行；不得直接修改使用者提供的原始快照。

---

## 2. v0.6.6.3 已驗證基線

2026-07-24 重新在解包後的 source tree 執行：

```text
python -m compileall -q jpnote_app    PASS
bash -n install.sh                    PASS
pytest -q                             150 passed, 1 skipped, 12 subtests passed
```

目前沒有已知、已重現的 SQLite corruption。

尚未完成：針對 v0.6.6.3 的完整 wide/bruteforce audit。現有完整廣域報告是 v0.6.6.1，已保存於：

```text
docs/audits/v0.6.6.1-wide-bruteforce-audit.md
```

---

## 3. 最近已完成的安全與正確性工作

### v0.6.6.1 廣域健檢找到的八項 blocker

下列問題已在 v0.6.6.2 修正並有 regression tests：

1. 舊 pending relation note 無聲覆蓋新 relation note。
2. attempt identity normalization 與 content comparison 不一致。
3. manual edit 拼錯欄位可能清空原資料。
4. malformed nested JSON 可能噴 Python traceback。
5. 損壞 structured attempt 可能讓 show/export/repair crash。
6. no-op mutation 仍發布 backup，可能擠掉真正可 undo 的備份。
7. legacy relation label 的 preflight/apply 行為不一致。
8. self relation 在 preflight 顯示新增、apply 卻靜默忽略。

另外已完成 pending resolution side-effect simulation、fail-soft presentation/export、strict unknown-field validation 等相關修正。

### v0.6.6.3 完成的資料品質與匯入安全工作

- 正常 `jpnote paste`／`jpnote import FILE` 在任何寫入前自動執行完整 read-only preflight。
- safe fix 與正式匯入採兩階段確認。
- `--yes` 只能略過確認，不能繞過 validation 或 blocking conflict。
- deterministic safe fixes：
  - 移除冗餘 alias。
  - 略過或清理可安全判定的空白／重複 sense。
- audit 新增：
  - `redundant_sense`
  - `same_meaning_multiple_examples`
- repair 可處理完全重複 sense 與部分安全的同 meaning 空白 sense。
- 使用者真實資料中曾有一筆特殊資料需要手動修正；目前使用者已確認資料修補完成。
- SQLite schema 仍為 v5；public import JSON schema 未新增欄位。

---

## 4. 尚待確認或修正的安全 backlog

以下來自 v0.6.6.1 廣域報告，CHANGELOG 未顯示已處理。必須先在 v0.6.6.3 重新重現，不能直接假設仍存在，也不能直接刪除 backlog。

### P1：Review／Quiz 開始前優先確認

1. **Relation edit provenance**
   - 修改一條 relation note 時，可能 delete/recreate 同 entry 的其他 relation。
   - 可能洗掉未修改 relation 的 `source` 與 `created_at`。
   - 目標：改為 logical relation diff/upsert，只改真的有變化者。

2. **Timestamp precision / recent 分類**
   - 秒級 timestamp 可能讓同秒 create→update 仍有 `created_at == updated_at`。
   - `recent` 可能把實際更新誤判成 added。
   - 需評估 microseconds 或明確事件語意。

3. **SIGKILL orphan `.pending-*` backups**
   - `kill -9` 可能留下 hidden pending snapshot。
   - 目前可能不列入 backup list 與 50 MiB cap。
   - 需設計保守的 orphan cleanup policy。

4. **Undo 選擇與損壞 fallback**
   - 最新 backup 損壞時，需能列出／選擇較舊有效 backup。
   - 候選介面：`jpnote undo --list`、`jpnote undo --backup NAME`。
   - 應先驗證目標，再建立 recovery snapshot。

5. **Explicit selector typo diagnostics**
   - `--item-key` 不存在或 `--attempt-index` 越界，不應靜默變成 no-selection。
   - 明確 selector 沒命中時應回報 error。

### P2：可以與 Quiz 初期並行評估

6. **Attempt identity matching 效能**
   - 舊 benchmark：5000 existing × 100 classifications 約 7.69 秒。
   - 大量歷史後需避免每筆 incoming attempt 線性重掃。

### P3：GUI／Web／background writer 前必須完成

7. **Concurrent writer policy**
   - 舊測試 20 processes：18 success、2 `database is locked`；無 corruption。
   - 未來多介面前需 busy timeout、有限 retry、writer serialization/process lock。

以上問題若 v0.6.6.3 無法重現，需在新 audit report 中記錄測試方法與結果，再標記 closed。

---

## 5. Stability gate

不得用反覆、無限期的廣域健檢拖延 Quiz 開發。建議只做一次 v0.6.6.3 完整健檢，之後依以下門檻決策：

### 必須修正後才能進 Quiz

- 可能錯改／遺失資料。
- preflight 與 apply 行為不一致。
- relation invariant 被破壞。
- backup／undo 無法可靠復原。
- 單筆壞資料阻斷 audit／repair／export。
- transaction 邊界或 migration 有 correctness 問題。

### 可排入後續 backlog，不阻塞 Quiz 核心

- 純效能問題，且目前資料量仍可接受。
- 顯示、美化、便利性改善。
- 單人 CLI 不會觸發的多 writer 問題，但必須在 Web/GUI/background writer 前完成。

---

## 6. 下一步執行順序

1. **完成本地 Git 與交接文件**（本次工作）。
2. **對 v0.6.6.3 做最後一次 wide/bruteforce audit**：
   - baseline tests／coverage
   - migration matrix
   - import/preflight/apply/repair/export cross-path
   - malformed payload fuzz
   - relation/merge/pending randomized invariants
   - attempt identity fuzz
   - backup/undo/no-op/cap/corrupt backup
   - SIGTERM/SIGKILL
   - concurrent writer
   - large-data performance
   - CLI JSON/ANSI/control/path safety
3. **對真實 `jpnote.db` 副本做唯讀健檢**：
   - quick_check／foreign_key_check
   - audit
   - relation invariants
   - aliases/senses/sources
   - attempts/event identity/structured fields
4. 若發現 blocking correctness/recovery 問題，做集中 maintenance patch，跑 targeted regression。
5. 通過 stability gate 後，開始 Quiz 核心與 TUI。
6. 熟悉度／間隔複習排程最後再討論與加入。

---

## 7. 每次版本更新的強制交接流程

每次 release 必須同時更新：

1. `CHANGELOG.md`
2. `docs/PROJECT_HANDOFF.md`
   - 目前版本與 commit/tag
   - 已完成項目
   - 未解問題與風險
   - 下一步開發順序
3. `docs/QUIZ_V1_SPEC.md`（若 Quiz 規格或行為有變）
4. `docs/audits/vX.Y.Z-*.md`
   - 測試範圍
   - 結果與 coverage
   - 新發現／已修／未解問題
   - stability gate 判定
5. `docs/RELEASE_CHECKLIST.md`
6. Git commit 與 release tag
7. release tar.gz 與 SHA-256
8. 可還原的本地 Git bundle

交接文件的主要讀者是「沒有舊聊天內容的新 ChatGPT 對話」，因此禁止只寫「如前面討論」或只列模糊標題。

---

## 8. 開發硬性原則

- 使用者環境以 Arch Linux + Hyprland 為主；文字編輯指令預設使用 `nvim`。
- 核心功能不能因 Quiz 未安裝、停用或故障而無法啟動。
- Quiz 不直接依賴 SQLite internal row IDs 或 CLI private implementation。
- mutation 必須經共用 validation／preflight／conflict gate／backup／transaction 流程。
- 對真實資料採 fail-safe／fail-soft：可拒絕，不可猜測後覆寫。
- 自動修復只處理 deterministic safe fix；語意不確定者列 review。
- 文法類練習不建立既有 jpnote `attempts`；Quiz live history 使用獨立紀錄。

---

## 9. 新對話接手時的最短檢查清單

```bash
# 1. 確認 Git 狀態
git status
git log --oneline --decorate -5
git tag -n

# 2. 確認版本
grep -R "VERSION" jpnote_app/config.py install.sh

# 3. 基線測試
python -m compileall -q jpnote_app
bash -n install.sh
pytest -q

# 4. 先讀交接與規格
nvim docs/PROJECT_HANDOFF.md
nvim docs/QUIZ_V1_SPEC.md
```

不要在尚未讀完這兩份文件前，重新詢問使用者已經定稿的 Quiz 規則。
