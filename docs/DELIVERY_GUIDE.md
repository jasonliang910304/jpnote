# jpnote 交付檔案分類規則

最後更新：2026-09-06

之後每次回覆都固定分成下列三類，避免檔案越堆越多卻不知道用途。

## GitHub 寫入邊界

- AI 對 GitHub 只做 read-only 查詢；不得建立／移動／刪除 branch/tag、commit/push、建立 PR、修改遠端檔案或操作 workflow。
- AI 在 exact baseline 的隔離 checkout 內準備 patch、測試與文件，完成 `git apply --check`＋clean-checkout actual apply 後才交付。
- 使用者親手把 patch 套到正式 repository，確認 gate 後自行 commit／push／tag。
- 儘量把可安全合併的修改整理成一次套用與一次 push；不要用 GitHub 遠端反覆提交實驗性小修來當測試環境。

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
