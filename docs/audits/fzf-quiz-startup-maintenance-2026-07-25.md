# fzf／Quiz startup maintenance checkpoint audit

日期：2026-07-25（Asia/Taipei）
基線：`15698ff`
正式版本：`jpnote 0.7.0`

## 範圍

- 修正 installed 版 `jpnote browse` 的 fzf reload/filter helper 子程序找不到 `jpnote_app`。
- Quiz 開始 session 前加入立即可見的準備畫面。
- Quiz session 初始 question-event 寫入改用 SQLite `executemany()`。
- 不修改 core schema v5、Quiz schema v2 或 public import JSON schema。

## 安全設計

- helper 使用 `python -I`，忽略 cwd 與 `PYTHONPATH`。
- helper 只插入目前 `ui_fzf.py` 所在安裝樹的 app root，再以 `runpy.run_module()` 啟動固定模組。
- search reload 與 filter panel 共用同一 bootstrap，避免兩條路徑再次分歧。
- Quiz loading 畫面只在 setup 的「開始」與 shortage 的「接受」動作前 refresh，不改 controller/session lifecycle。
- batch insert 仍位於原本的 `BEGIN IMMEDIATE` transaction，錯誤仍完整 rollback。

## 驗證計畫

- `python -m compileall -q jpnote_app tests`
- `git diff --check`
- `pytest -q tests/test_fzf_helper_path_isolation.py tests/test_v062.py`
- `pytest -q tests/test_quiz_startup_feedback.py tests/test_quiz_phase2_session_store.py tests/test_quiz_phase5_tui_foundation.py`
- isolated install 後，從 repository 外且帶 shadow `PYTHONPATH` 執行 helper smoke。
- installed `jpnote browse` 實際輸入搜尋與 Ctrl-F filter panel smoke。
- installed `jpnote quiz` 確認開始時會先顯示「正在準備題目……」。

## 已知限制

- 本 checkpoint 的 Quiz 優化是第一版：改善 UI 回應並降低初始 SQLite 呼叫次數；尚未加入各階段耗時 telemetry。
- 若實際卡頓仍明顯，下一步才量測 source snapshot、question generation、session persistence 與 first-question load 的分段耗時。
