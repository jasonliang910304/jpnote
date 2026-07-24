# jpnote 交付檔案分類規則

最後更新：2026-07-24

之後每次回覆都固定分成下列三類，避免檔案越堆越多卻不知道用途。

## 1. 必須下載

正常情況只會有 **一個**：

- `jpnote-vX.Y.Z-update.patch`：套用到 `~/Projects/jpnote` 的 Git 更新。

套用後直接從 repository 執行 `./install.sh`，因此已有本地 Git repository 時不需要另外下載 source tarball。

若 patch 因本地歷史分歧無法套用，才改用：

- `jpnote-vX.Y.Z-source.tar.gz`：完整獨立原始碼包。

## 2. 僅供參考／備援

不用每次下載：

- `docs/audits/...md`：完整健檢細節；聊天摘要已足夠時可不下載。
- `SHA256SUMS.txt`：想驗證下載完整性時才需要。
- `*.bundle`：災難復原或重建完整 Git 歷史才需要；GitHub 已正常備份時不必每版下載。
- 單獨的 README、ROADMAP、HANDOFF：已包含在 patch／source package 中，不必另外下載。

## 3. 給新聊天續接用

- `docs/CHATGPT_CONTINUATION_PROMPT.md`

只有在開新聊天、Project context 遺失，或需要把專案交給另一個 ChatGPT 工作階段時才使用。平常同一聊天不必下載或貼上。

若專案狀態、版本、已修 blocker、下一步或硬性規則有變，release 時必須同步更新這份提示詞，並在交付清單註明「續接提示詞已更新」。
