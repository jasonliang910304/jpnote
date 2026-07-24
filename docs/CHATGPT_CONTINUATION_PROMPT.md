# jpnote ChatGPT 續接提示詞

> 使用時機：新聊天無法取得舊對話脈絡時，連同最新版 repository 提供給 ChatGPT。

請接續開發 jpnote。先閱讀：

1. `docs/PROJECT_HANDOFF.md`
2. `docs/ROADMAP.md`
3. `docs/QUIZ_V1_SPEC.md`
4. `docs/audits/quiz-development-handoff-2026-07-24.md`
5. `docs/RELEASE_CHECKLIST.md`
6. `docs/DELIVERY_GUIDE.md`
7. README、CHANGELOG、USER_GUIDE

## 目前基準

- 正式 release：`jpnote v0.6.6.4`
- core SQLite schema：v5
- Quiz SQLite：獨立 `quiz.db`，schema v2
- stability gate：通過
- Quiz 開發已完成 Phase 1–4，以及 Phase 5 TUI foundation＋第一輪 usability/question-quality 修正
- 最新完整測試：`346 passed, 12 subtests passed`

啟動新工作階段先執行：

```bash
git status
git log --oneline --decorate -10
git tag --sort=-creatordate | head -n 15
jpnote --version
python -m compileall -q jpnote_app tests
bash -n install.sh
pytest -q
```

## 已完成 Quiz 功能

- optional/fault-isolated package 與 stable read contracts。
- independent Quiz history、immutable snapshots、resume/abandon、retention/export。
- safe generators、question pools、shortage reporting。
- headless service/debug adapter 與 lifecycle recovery。
- curses TUI foundation。
- 設定 Enter 流程、reorder Backspace 提示、正確答案回饋、terminal default background。
- 漢字意思題在安全時優先以假名作 prompt。
- 讀音 false trap 只使用長音／促音／撥音等細微變化，不使用無關詞讀音。

## 下一個正確工作項目

Phase 5 正式 CLI／config 整合：

1. `jpnote quiz` lazy loader，Quiz broken 時 core CLI 仍正常。
2. JLPT/source filters。
3. config default mode/count、transparent background、history cap/prune policy。
4. TUI history/recent/resume 與 shortage confirmation。
5. installer/package smoke；完成後再準備 v0.7.0 release。

負分／猜題扣分是低優先 optional scoring backlog，不阻塞當前工作。

## 日常資料匯入

使用者會持續匯入文法與單字。預設不需停止 `jpnote paste/import`。只有當回覆明確標示「先暫停匯入」時才停止，通常是正式 core DB migration/repair/restore、固定 DB 快照、正式 install/upgrade smoke 或可能同時寫入 core DB 的測試。純 repository、Quiz 或 temporary DB 測試可並行。

## 硬性原則

- core 在 Quiz absent/disabled/broken 時仍可 install/start/browse/import/audit/repair/export。
- Quiz 不直接查 core SQLite tables，不使用 row ID 或 CLI private handlers。
- Quiz live history 不寫入既有教材 attempts。
- 文法類學習練習不建立既有 jpnote attempts。
- 破壞性、migration、repair、fuzz 測試不得直接使用正式 `jpnote.db`。
- 不因非 blocking finding 重啟廣域健檢或延後 Quiz。
- 每次狀態/下一步/schema/測試基線變更都同步 handoff、roadmap、continuation prompt 與 audit。
- 使用者環境是 Arch Linux + Hyprland；編輯器預設 nvim。
