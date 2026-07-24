# jpnote ChatGPT 續接提示詞

> 使用時機：只有在新的聊天無法取得舊對話脈絡時，將本文件連同最新版 repository／source package 提供給 ChatGPT。

請接續開發 jpnote。不要重新詢問已定稿需求，先閱讀 repository 內：

1. `README.md`
2. `CHANGELOG.md`
3. `docs/PROJECT_HANDOFF.md`
4. `docs/ROADMAP.md`
5. `docs/QUIZ_V1_SPEC.md`
6. `docs/audits/v0.6.6.3-wide-bruteforce-audit.md`
7. `docs/audits/v0.6.6.4-stability-gate.md`
8. `docs/RELEASE_CHECKLIST.md`
9. `docs/DELIVERY_GUIDE.md`

目前可信版本是 **jpnote v0.6.6.4**，SQLite schema v5。v0.6.6.3 廣域健檢找到的 Quiz 前 blockers 已在 v0.6.6.4 修正：

- relation edit 改為 logical diff/upsert，不遺失 pending relation 或 provenance。
- raw SQLite connection 全部顯式關閉。
- CLI 與 public API 寫入共用 safe mutation pipeline；public import 不可略過 blocking preflight。
- crash orphan `.pending-*` snapshot 可在下次 writable 啟動恢復。
- timestamp microseconds、undo fallback／select、auxiliary backup retention、selector diagnostics 已完成。

v0.6.6.4 驗證結果：

- `165 passed, 1 skipped, 12 subtests passed`
- app-only coverage 72%
- 真實 `jpnote.db` 副本：240 entries、27 attempts、22 relations、0 pending；`quick_check=ok`、0 foreign-key issues、0 non-info audit issues。
- stability gate 已通過。

下一步不是再做一次同規模廣域健檢，而是開始 Quiz 核心：

1. optional、fault-isolated Quiz package/module。
2. 只透過 stable public/core read services 取得題目來源，不直接讀 SQLite table 或 row ID。
3. 獨立 Quiz session/history store 與 immutable question snapshot。
4. capability-based generators、安全 distractor/fallback 規則。
5. CLI/debug adapter 後再做 Python-native TUI。

硬性原則：

- 核心 jpnote 在 Quiz absent/disabled/broken 時仍可 install、start、browse、import、audit、repair、export。
- 文法類學習練習不建立既有 jpnote `attempts`；Quiz live history 使用獨立資料。
- 不直接修改使用者真實 `~/.local/share/jpnote/jpnote.db`；健檢先複製。
- 只修 blocking correctness/recovery 問題才能延後 Quiz；非 blocking finding 排 backlog。
- 每版更新 `CHANGELOG.md`、PROJECT_HANDOFF、ROADMAP、audit report、USER_GUIDE、續接提示詞、Git tag、release package、SHA。
- 使用者環境是 Arch Linux + Hyprland，文字編輯器預設 `nvim`。
- 交付檔案必須分類成「必須下載／僅供參考／新聊天續接用」。

先回報你讀到的版本、stability gate、下一項實作工作，再開始修改。
