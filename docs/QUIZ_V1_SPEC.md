# jpnote Quiz v1 功能規格

狀態：第一版必要規格已確認；實作已進入 Phase 5 TUI／CLI 整合
最後更新：2026-07-24（Asia/Taipei）

---

## 1. 範圍與優先順序

Quiz v1 先完成：

- 安全出題
- TUI 作答
- session pause／resume／abandon
- 獨立 Quiz history
- 結果摘要與歷史查看／匯出

第一版不做：

- 熟悉度評分
- spaced repetition／下次複習排程
- 每題作答時間紀錄
- 長期趨勢圖
- 題型正確率雷達圖／多邊形圖
- 動畫、連勝等娛樂性功能

上述項目可在核心穩定後再加入。

---

## 2. 架構與故障隔離

- Quiz 是 optional、isolated、plugin-style extension。
- Quiz 未安裝、停用、import failure、runtime failure、migration failure 時，core 仍須正常：
  - install/start
  - browse/search
  - import/paste
  - audit/repair
  - export
- Quiz code、commands、storage/migrations、history、generators、renderers、tests 盡量隔離。
- Quiz 不直接查 SQLite internal tables，也不依賴 CLI private handlers。
- Quiz 只能透過穩定 public core services 讀取：
  - entries
  - replayable attempts
  - filters/source metadata
- 對外引用使用 stable entry key、attempt event_key、quiz session/event IDs；禁止依賴 SQLite autoincrement row ID。
- Quiz history 與既有 `attempts` 分離：
  - `attempts`：教材錯題／可重播題目來源。
  - Quiz history：每次 live 作答的新獨立事件。
- 同一道題重做兩次，也保存兩筆 Quiz events。
- Quiz storage 必須 optional/additive；實作已選擇獨立 `quiz.db`（目前 schema v2），不得成為 core 啟動條件。

---

## 3. 入口與設定畫面

執行：

```bash
jpnote quiz
```

進入 Python-native TUI，不以 fzf 為主要 Quiz UI。

### 必選

- 混合測驗（預設游標）
- 單字測驗
- 錯題測驗

### 本場設定

- 題數：預設 10 題，可在開始前調整。
- config 可自訂預設模式與題數。
- 設定畫面 Enter／Space 依序移動「模式 → 題數 → 開始」，左右鍵修改目前值。
- config 可切換是否使用 terminal default background；預設保留終端原有透明背景。

### 選填篩選

- JLPT 等級
- 來源

未設定選填條件時，使用全部安全可用題池。

### Mixed mode

- 不使用固定題型比例。
- 從安全可用題池隨機抽取。
- 單字與錯題都有時，盡量讓兩者都出現，但不以 quota 犧牲安全性。

---

## 4. Quiz v1 題型

### Vocabulary

1. 日文／讀音 → 中文四選一；漢字詞在同音不歧義時優先以假名作 prompt，避免中文字形直接提示。
2. 中文 → 日文四選一
3. 日文 ↔ 中文意思是非題
4. 日文 ↔ reading 是非題
5. 讀音陷阱是非題
   - 長音
   - 促音 `っ`
   - 撥音 `ん`

### Mistake

6. 原始 multiple-choice 重考
7. `reorder_4` 重考
8. 原題＋候選答案是非題
   - 只有可安全還原為單一、明確句子的 attempt 才能生成。
   - 多空格、無法可靠插入、結構不完整或語意不明者跳過。

未來題型只能新增，不應要求修改既有 core schema 才能啟動。

---

## 5. Capability-based generation

每一種 generator 必須先回答：

```text
這筆 source 是否具備安全生成此題型所需的資料？
```

- 可以：產生題目。
- 不可以：跳過此 generator/source pair。
- 禁止所有資料強制支援所有題型。

例：

- multiple choice 需有 prompt、唯一正解、可用選項。
- reorder_4 需有四個合法 parts 與有效 correct order。
- mistake true/false 需能安全還原完整句子。

---

## 6. Distractor 與 false-candidate 安全規則

### 四選一

- 需要三個安全、不同、且不會形成多重正解的干擾選項。
- 選項顯示文字不得重複。
- 同音詞、同義／近義詞不得因形式不同就直接當錯誤選項。
- 找不到三個安全干擾項：
  1. 嘗試 fallback 為是非題。
  2. 是非題也無法安全生成時跳過。

### 是非題

- false statement 必須能高信心判定為錯。
- 禁止把可能是合理近義、上位／下位概念或語境可成立的配對硬判錯。
- 正確／錯誤答案不強制 50/50，也不刻意交替。
- 題數足夠大時，使用 soft anti-extreme constraint：單一答案盡量不要超過約 80%。
- 找不到安全 false candidate 時，內容正確性優先，允許比例失衡。

---

## 7. Session 出題與重複規則

- 優先讓一個 vocabulary entry 在同一 session 只出現一次。
- unique eligible entries 用完後，可用同一 entry 的另一種題型補充安全題池。
- 禁止重複完全相同的 generated question。
- vocabulary question 與 linked mistake question 可以同場出現，因為測量能力不同。
- 若安全題池仍少於使用者指定題數：
  - 顯示「要求題數」與「可安全生成題數」。
  - 由使用者決定是否開始。
  - 若開始，只出所有安全題目。
  - 禁止用模糊、重複或低品質題目硬湊。

---

## 8. 作答與回饋

### Skip

- 允許 skip。
- skip 視為答錯，不是中立結果。
- 保存一筆 Quiz history event。
- 同一 session 不再重出該題。
- 立刻顯示正解，與一般答錯使用相同回饋。

### 答錯／skip 的預設回饋

只顯示必要資訊，例如：

```text
× 錯誤

正解：
軌跡（きせき）
行進後留下的路徑、軌道
```

另提供展開詳細資訊：

- examples
- sources
- aliases
- 其他 entry metadata

### 答對

保持節奏簡潔，但仍顯示實際正解（例如詞彙、讀音、意思或完整重組句），讓猜對者也能確認；完整詳細內容不強制展開。

---

## 9. TUI 操作

正式使用介面為 TUI；CLI adapter 可保留給測試、除錯與自動化。

必要鍵盤操作：

```text
↑ / ↓       移動選項
Space       選取
Enter       確認
1–4         直接選答案
s           skip
d           展開詳細資訊
q           暫停／退出選單
```

- 是非題同樣可用方向鍵／Space／Enter。
- TUI framework 與 terminal 支援時，提供滑鼠左鍵點選。
- 滑鼠只是便利功能；完整功能必須只靠鍵盤可操作。
- TUI framework 尚未最終定案；優先評估 Python-native framework，Textual 是候選之一。
- Quiz core 不得依賴 TUI，必須可單元測試與 headless 測試。

---

## 10. Session 狀態與恢復

建議狀態至少包含：

- `active`
- `paused`
- `interrupted`
- `completed`
- `abandoned`

### 強制中斷

- 保存已完成作答、剩餘題目與 session state。
- 標記為 `interrupted`，可恢復。
- 下次啟動 Quiz 先詢問是否繼續。
- 選擇不繼續：立即標記 `abandoned`，不再保留 resumable state。

### 主動退出

提供：

1. 暫停並保留下次繼續。
2. 結束本次 Quiz。

結束未完成 session 時，使用 `abandoned`，以免產生另一套含糊狀態。

### 持久化

- 已答題目應逐題安全保存，不能等整場結束才一次寫入。
- 當前尚未提交答案的題目不算已作答。
- resume 必須使用原本已生成的剩餘題目快照，不能重新隨機生成導致 session 改變。

---

## 11. Quiz history schema 要求

每次實際顯示的題目至少保存：

- `session_id`
- `question_event_id`（每次作答唯一）
- question/generator type
- generator version
- source kind（vocabulary／mistake）
- stable source key（entry key 或 attempt event_key）
- exact prompt snapshot
- exact choices snapshot
- exact correct answer snapshot
- user answer
- result（correct／incorrect／skipped）
- shown/answered ordering or timestamps needed for event order

第一版不保存每題 response duration。

Snapshot 用途：

- 原始 entry／attempt 日後修改後，舊紀錄仍能忠實重現。
- 題目生成出錯時可還原當時 prompt、choices、correct answer 與 generator version 進行除錯。

---

## 12. History 查看與管理

第一版提供：

- 最近測驗列表
- 單場測驗摘要
- 單場逐題紀錄
- 只看答錯／跳過
- abandoned session 顯示明確狀態
- 可用 filter 隱藏 abandoned sessions

### 手動刪除

- 刪除單場
- 清除全部 Quiz history
- destructive action 前都必須確認

---

## 13. History 儲存限制

### 永久保留

Session summary 永久保留：

- 日期／狀態
- 題數
- 答對／答錯／跳過
- overall accuracy
- 各題型摘要

### Detailed snapshots

- 預設上限：100 MiB。
- config 可修改上限。
- 超過上限時，從最舊 session 的逐題詳細 snapshot 開始清理。
- 預設靜默自動清理，不跳提示。
- config 可切換成清理前警告／確認。
- 即使 details 被清理，session summary 仍留在 history。
- 進入已清理 session 時顯示：

```text
詳細作答紀錄已依容量限制清理
```

- 實作時需考慮 SQLite page reclaim／VACUUM 策略，但不能在每場 Quiz 後昂貴地 VACUUM。

---

## 14. History JSON 匯出

支援範圍：

1. 全部歷史（預設；直接按 Enter）
2. 指定單場
3. 指定日期範圍

預設包含：

- completed
- interrupted
- abandoned

提供選項排除 interrupted／abandoned。

匯出內容：

- session summaries
- 尚未被 retention policy 清除的 per-question snapshots
- question/generator type and version
- source identifiers
- session status

已被清理的詳細紀錄不能假造；匯出摘要中需標記 details 已被 prune。

---

## 15. 測驗結束摘要

第一版顯示：

- 完成題數
- 答對數
- 答錯數
- 跳過數
- 正確率
- 各題型表現

不顯示／不計算：

- response speed
- streak
- familiarity
- spaced-repetition score

各題型正確率的雷達圖／多邊形圖是未來非必要美化功能。

---

## 16. 必要測試

### Core isolation

- Quiz package/module 完全不存在時，core tests 通過。
- Quiz import failure 不阻止 core CLI 啟動。
- Quiz runtime failure 不破壞 core process/data。
- Quiz migration/storage failure 只停用 Quiz。

### Generators

- property/fuzz tests：不得重複選項、不得多重正解。
- false-candidate semantic safety boundary tests。
- four-choice → true/false → skip fallback。
- homophone／same-reading cases。
- malformed/incomplete entry 或 attempt 必須 skip/fail-soft。
- deterministic random seed 支援測試重現（可為 internal test hook，不一定公開）。

### Sessions

- pause/resume 保留完全相同剩餘題目。
- SIGINT/exception/crash 後可恢復。
- 拒絕 resume 後標記 abandoned。
- skip 記為 incorrect 並顯示正解。
- 完成、暫停、放棄的 history 一致性。

### History

- snapshot 不隨 source entry 修改而改變。
- 100 MiB cap pruning oldest details、保留 summaries。
- auto prune 與 confirm-before-prune config。
- pruned sessions 顯示正確標記。
- single/all delete confirmation。
- JSON export scopes and statuses。

### Performance

- 大量 entries／attempt sources 的 pool construction。
- 大量 Quiz history 的 recent list／single-session detail。
- pruning 不阻塞或損壞 active session。

---

## 17. 尚未定案但不阻塞 v1 核心的事項

- Quiz storage 已定案為獨立 SQLite `quiz.db`。
- Python-native TUI 已採 curses foundation；core 不依賴 TUI。
- config key 命名與檔案格式細節。
- 是否公開 response-time 支援（第一版不記錄）。
- 熟悉度／間隔複習演算法。
- optional negative scoring／guess penalty（低優先，不阻塞 v1）。
- 雷達圖與其他統計美化。
