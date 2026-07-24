# jpnote 開發路線圖

最後更新：2026-07-24（Asia/Taipei）
目前基準：v0.6.6.3

## 現在的位置

v0.6.6.3 廣域健檢已完成。一般 CLI、真實資料庫、migration、匯入與 relation 隨機 invariant 均穩定，但 stability gate 尚未通過。

## 下一個 maintenance patch

### 必修

1. relation edit 改為 logical diff/upsert，保留 pending relation 與 provenance。
2. 修正 raw SQLite connection leak，長駐程序不得依賴 GC 關閉 connection。
3. 收斂 public mutation API 到共用 safe mutation pipeline。
4. 定義 SIGKILL 後 orphan `.pending-*` snapshot 的 recovery policy。

### 建議同版處理

5. timestamp microseconds 或明確 recent action。
6. undo 可列出／指定較舊 backup，且先驗證再建立 recovery snapshot。
7. recovery/restored backups 容量或數量上限。
8. explicit selector no-match/out-of-range error。

### 延後

- concurrent writer serialization：Web／GUI／background writer 前。
- attempts identity indexing：資料量成長後。

## Maintenance patch 驗收

- targeted regression 全部通過。
- full pytest、compileall、install smoke 通過。
- 真實 DB 副本 audit 與 invariants 維持 clean。
- audit report 更新 stability gate 為通過。

## Stability gate 後

1. 建立獨立、optional、fault-isolated Quiz package/module。
2. 實作 read-only question source public services。
3. 實作獨立 Quiz session/history store。
4. 實作 capability-based question generators 與 safety rules。
5. 建立 CLI/debug adapter。
6. 建立 Python-native TUI。
7. 補 session resume／abandon、history pruning/export、fault isolation tests。
8. 最後再討論熟悉度／間隔複習與視覺化統計。

完整 Quiz v1 行為規格見 `docs/QUIZ_V1_SPEC.md`。
