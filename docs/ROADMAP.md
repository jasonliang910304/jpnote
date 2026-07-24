# jpnote 開發路線圖

最後更新：2026-07-24（Asia/Taipei）
目前基準：v0.6.6.4
Stability gate：**通過**

## 現在的位置

v0.6.6.3 廣域健檢已完成；其發現的 relation data loss、SQLite connection leak、unsafe public mutation、orphan pending backup、undo fallback、timestamp 與 selector 問題已在 v0.6.6.4 集中修正。

完整 regression、coverage、install／upgrade smoke 與真實 DB 副本 audit 通過。除非出現新的 blocking correctness／recovery regression，下一項工作是 Quiz core，不再做同規模廣域健檢。

## Phase 1：Quiz 契約與隔離骨架

1. 建立 optional `quiz` package/module，core 不 import Quiz 才能啟動。
2. 定義 stable public read service：entry snapshot、attempt replay source、capabilities。
3. 建立 fault-isolation contract tests：Quiz import/runtime failure 不阻止 core CLI 啟動。
4. 禁止 Quiz 直接讀寫 core SQLite table、row ID 或 CLI private function。

## Phase 2：Quiz session 與 history core

1. 獨立、additive Quiz schema／store。
2. session 狀態：active、interrupted、paused、completed、abandoned。
3. force interruption 保存已完成作答與 resume state。
4. immutable question snapshot：prompt、options、correct answer、generator version、source IDs。
5. skip 記為 incorrect、保存事件、不在同 session 重出。
6. detailed history 100 MiB default cap；先刪最舊 detail，永遠保留 summary。
7. history JSON export：全部／單次／日期範圍。

## Phase 3：Capability-based question generation

第一版支援：

1. 日文→中文選擇
2. 中文→日文選擇
3. 日文↔中文是非
4. 日文↔讀音是非
5. 讀音陷阱
6. 重播 multiple-choice attempt
7. 重播 reorder_4
8. 原題＋候選答案是非

安全規則：

- MCQ 需要 3 個安全、相異 distractors；不足則 fallback true/false，再不足就 skip。
- false pair 必須明確錯誤，不用語意可能成立的配對。
- 題庫不足時警告並詢問是否以可安全生成數量繼續，禁止降低品質硬補。
- 同一 vocab entry 每 session 原則上一次；只有不同題型仍安全且使用者接受不足題庫流程時才考慮重用。
- true/false 自然隨機，只做 soft anti-extreme，不強制交替或 50/50。

## Phase 4：CLI/debug adapter

先提供可測試、可自動化的非互動 adapter：

- 建立 session
- 取下一題
- submit／skip
- pause／resume／abandon
- 查 history／export

它只呼叫 Quiz public services，不把 business logic 寫進 CLI。

## Phase 5：Python-native TUI

1. `jpnote quiz` 開啟模式與題數設定畫面。
2. 預設 mixed、10 題；可設定全域預設與 session override。
3. 必要模式：vocab、mistake、mixed。
4. 操作：↑/↓、Space、Enter、1–4、`s`、`d`、`q`；滑鼠僅作加分，鍵盤必須完整可用。
5. 答錯／skip 立即顯示精簡更正，可展開詳細資訊。
6. 結尾顯示完成、正確、錯誤、skip、accuracy 與題型統計。
7. recent sessions、per-question、wrong/skipped filter、abandoned label／hide filter。

## Stability gate 後仍保留的 backlog

以下不阻塞 Quiz core，但有條件：

- 多 writer busy timeout／retry／serialization：Web、GUI、background writer 前完成。
- attempt identity index：資料量明顯成長時處理。
- delete impact preview、進階 backup UI。
- response timing、radar chart、熟悉度、間隔複習：Quiz v1 穩定後再做。

## 每階段驗收

- core 在 Quiz absent/disabled/broken 時完整可用。
- 所有 Quiz 寫入只進 Quiz store，不污染 core attempts。
- public IDs 穩定，不使用 SQLite row ID。
- 每一階段有 contract、fault-isolation 與 regression tests。
- 每版同步更新 handoff、roadmap、audit、continuation prompt 與 release artifacts。
