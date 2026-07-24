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

v0.6.6.3 的完整 wide/bruteforce audit 已完成，報告位於：

```text
docs/audits/v0.6.6.3-wide-bruteforce-audit.md
```

目前 stability gate **尚未通過**。主要 blocker：relation edit 會刪除 pending relations、raw SQLite helper connection leak，以及 public mutation API 未收斂到共用安全 pipeline。

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

## 4. v0.6.6.3 健檢後的安全 backlog

完整重現方式與測試數據見 `docs/audits/v0.6.6.3-wide-bruteforce-audit.md`。

### Quiz 前必修

1. **Relation edit pending-data loss**
   - 修改 resolved relation 時，該 entry 的 pending relations 會被整批刪除。
   - 同時會洗掉未修改 relation 的 provenance。
   - 必須改為 logical diff/upsert。

2. **Raw SQLite connection leak**
   - 多個 helper 使用 transaction context manager，但沒有顯式 close。
   - 長駐 TUI 會線性累積 file descriptors。

3. **Public mutation pipeline**
   - `JpnoteCore` 多個寫入方法繞過 CLI 的完整 preflight、backup、conflict gate 與 export。
   - TUI／Web／plugin 寫入前必須收斂到共用 Safe Mutation Service。

4. **SIGKILL orphan pending backup recovery**
   - commit 後、backup publish 前被 kill 時，唯一 undo snapshot 可能只剩 hidden `.pending-*`。
   - 需要啟動時 recovery/promotion policy。

### 建議 maintenance patch 同版處理

5. timestamp precision／recent 分類。
6. undo list、指定 backup、corrupt newest fallback。
7. recovery/restored backup retention cap。
8. explicit selector typo diagnostics。

### 可延後

9. concurrent writer serialization：Web／GUI／background writer 前。
10. attempt identity matching optimization：資料量成長後。

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

1. v0.6.6.3 wide/bruteforce audit 與真實 DB 唯讀健檢：**已完成**。
2. 做集中 maintenance patch：relation edit、SQLite connection lifecycle、safe mutation API、pending backup recovery。
3. 視修改風險同版處理 timestamp、undo fallback、backup retention、selector diagnostics。
4. 跑 targeted regression、完整 pytest、migration/install smoke、真實 DB 副本再驗證。
5. 通過 stability gate 後，開始 Quiz core 與獨立 history store。
6. 再建立 Python-native TUI。
7. 熟悉度／間隔複習排程最後再討論與加入。

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
