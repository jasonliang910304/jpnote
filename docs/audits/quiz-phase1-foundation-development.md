# jpnote Quiz Phase 1 foundation 開發驗證

日期：2026-07-24（Asia/Taipei）
基準：`main@5c2ecef` / jpnote v0.6.6.4 / SQLite schema v5
狀態：Phase 1 實作候選，尚未建立正式 release tag

## 範圍

本 patch 只建立 Quiz 的契約與故障隔離骨架：

1. core-side stable read service：immutable entry snapshots、attempt replay sources、capabilities、source catalog。
2. optional `jpnote_app.quiz` package 與最小 runtime shell。
3. explicit lazy loader；只有呼叫 optional loader 時才 import Quiz。
4. contract tests：stable IDs、SQLite row ID 隔離、immutable snapshots、malformed data fail-soft、import/runtime failure containment、forbidden internal import scan。

本 patch 不包含：

- Quiz session/history schema 或 migration
- question generators
- CLI/debug adapter
- `jpnote quiz` command
- TUI
- 對既有 `attempts` 的任何寫入

SQLite schema 維持 v5；既有 CLI 行為與 public import JSON schema 不變。

## 本次隔離驗證

```text
python -m compileall -q jpnote_app/study_sources.py jpnote_app/optional_features.py jpnote_app/quiz tests/test_quiz_phase1.py
PASS

pytest -q tests/test_quiz_phase1.py
12 passed
```

覆蓋的 contract：

- Entry snapshot 使用 stable entry key，且不暴露 SQLite `id`。
- Attempt replay source 使用 stable `event_key`，且不暴露 SQLite `id`。
- 所有 snapshot 使用 frozen dataclass 與 tuple，避免 source 後續修改影響已取得的 view。
- source／JLPT filter 透過 public metadata 處理。
- malformed attempt 以 capability=false／warning 表示，不向 Quiz 偽裝成安全題源。
- Quiz import failure 與 runtime construction/probe failure 被限制在 optional feature boundary。
- Quiz package 靜態禁止 import `sqlite3`、`jpnote_app.db`、`jpnote_app.repository`、`jpnote_app.cli`。
- 一般 core modules 不靜態 import Quiz。

## 套用後本機必跑

此開發環境無法直接取得完整 Git checkout，因此正式合併前仍需在使用者的 `main@5c2ecef` repository 執行：

```bash
python -m compileall -q jpnote_app tests
pytest -q
bash -n install.sh
git diff --check
```

只有完整 regression 通過後，才將 Phase 1 標記完成並整理成 v0.7.0 release；若失敗，先修本 patch，不應跳進 Phase 2。

## 下一步

完整 regression 通過後：

1. 補上真實 `JpnoteCore` + 臨時資料庫 integration test。
2. 更新 VERSION、CHANGELOG、README、USER_GUIDE、PROJECT_HANDOFF、ROADMAP 與 continuation prompt。
3. 建立 v0.7.0 release commit/tag。
4. 進入 Phase 2：獨立 Quiz session/history core 與 immutable generated-question snapshots。
