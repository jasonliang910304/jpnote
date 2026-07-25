# jpnote `paste --stdin` hotfix checkpoint（2026-07-25）

## 範圍

本 checkpoint 為出差前 SSH 使用情境加入標準輸入來源，不建立新的 importer，也不修改資料 schema。

- 功能 commit：`74fb82a`
- 前置顯示修正 commit：`a660950`
- 正式 release/tag 仍為：`v0.7.0`
- installed version 仍為：`jpnote 0.7.0`
- core schema：v5
- Quiz schema：v2
- public import JSON schema：無變更

## 實作

- `jpnote paste`：維持 `_read_clipboard()`。
- `jpnote paste --stdin`：使用 `sys.stdin.read()` 取得完整 JSON。
- `_read_paste_input()` 只負責選擇輸入來源。
- 兩種來源之後都呼叫既有 `_run_import_text()`，因此解析、validation、duplicate detection、完整 preflight、safe fixes、確認、backup、transaction 與 Markdown refresh 沒有分叉。
- `jpnote import FILE` 繼續提供檔案輸入；本 checkpoint 未增加 `paste --file PATH`。

## 驗證結果

### 套用與針對性 regression

```text
13 passed in 0.61s
git diff --check: PASS
```

涵蓋：

- 預設 `paste` 仍走剪貼簿。
- `--stdin` 讀取完整標準輸入。
- stdin 路徑不誤呼叫剪貼簿。
- `--check` 使用既有 read-only preflight。
- `--yes` 使用既有正式匯入與備份流程。

### installed-command smoke

```text
jpnote --version: jpnote 0.7.0
jpnote paste --help: 顯示 --stdin
temporary JPNOTE_DATA_DIR preflight: database_modified=false
temporary JPNOTE_DATA_DIR import: 新增 1 項
temporary JPNOTE_DATA_DIR stats: 總項目 1，單字 1
repository status: clean
```

測試使用 `mktemp -d` 與 temporary `JPNOTE_DATA_DIR`；沒有讀寫正式 `~/.local/share/jpnote/jpnote.db`。

## 已知限制與風險

- stdin payload 會一次讀入記憶體；與原本剪貼簿整段讀取的模型一致，適合目前 jpnote JSON 尺寸。
- stdin 已承載 JSON，因此正式 pipe／SSH 匯入需使用 `--yes`；預檢使用 `--check`。
- 已完成本機 pipe 與 installed launcher smoke，但尚未從 Windows 筆電跨網路執行真實 SSH 端到端測試。
- `paste --file PATH` 未實作；使用 `jpnote import FILE`。

## 出差前建議的最後 smoke

從 Windows 筆電選一份不含敏感資料的小型 JSON，先執行：

```bash
ssh user@arch-desktop '~/.local/bin/jpnote paste --stdin --check --format json' < import.json
```

確認 SSH、PATH、UTF-8 與輸出都正常後，再於真正匯入時使用：

```bash
ssh user@arch-desktop '~/.local/bin/jpnote paste --stdin --yes' < import.json
```

## 結論

此 hotfix 符合最小修改原則：只新增輸入來源選擇，既有安全匯入 pipeline 不變。針對性測試與隔離 installed-command smoke 通過，可作為出差前 SSH 匯入方案；仍應在出發前做一次真實 Windows → SSH → Arch 端到端預檢。
