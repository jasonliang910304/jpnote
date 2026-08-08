# jpnote 使用者操作手冊

本手冊對應 jpnote v0.7.2。`jpnote --help` 提供精簡指令索引；`jpnote manual` 會輸出這份完整手冊，`jpnote manual --path` 會顯示手冊檔案位置。

> 原則：任何會修改資料的操作都應先確認輸入與備份；`--check` 是真正 read-only 的預檢，不會建立、升級、修復或改寫實體資料庫。

> v0.7.2：Windows 遠端匯入使用 repository 內的正式 PowerShell client；一般本機流程仍以 `jpnote import FILE` 為主。

---

# Part 1：安裝與升級

## 1.1 需求

- Python 3
- SQLite（Python 標準函式庫內建支援即可）
- fzf：選配；提供互動 browse／選擇器。沒有 fzf 仍可使用非互動 CLI。
- Wayland `wl-paste` / `wl-copy`：只有預設剪貼簿模式的 `jpnote paste` 與 `--copy-report` 需要；`jpnote paste --stdin` 不需要。
- `$EDITOR`：編輯命令使用；未設定時預設 `nvim`。

## 1.2 安裝 release 壓縮包

```bash
mkdir -p /tmp/jpnote-install
tar -xzf jpnote-v0.7.2.tar.gz -C /tmp/jpnote-install --strip-components=1
/tmp/jpnote-install/install.sh
rehash
jpnote --version
jpnote init
```

安裝器會把程式放在：

```text
~/.local/lib/jpnote/<version>/
```

啟動器放在：

```text
~/.local/bin/jpnote
```

若啟動器已存在，安裝器會先備份舊啟動器，再以原子替換方式安裝新版。

## 1.3 升級

直接執行新版 `install.sh`，然後：

```bash
rehash
jpnote --version
jpnote init
```

`jpnote init` 會建立或升級資料庫並重新產生 Markdown 匯出。

## 1.4 版本與路徑

```bash
jpnote --version
jpnote config path
jpnote manual --path
```

預設資料位置：

```text
~/.local/share/jpnote/jpnote.db
~/.local/share/jpnote/quiz.db
~/.local/share/jpnote/backups/
~/.local/share/jpnote/exports/
~/.config/jpnote/config.json
```

可用 `JPNOTE_DATA_DIR` 改變資料目錄；設定檔遵循 `XDG_CONFIG_HOME`，也可使用 `JPNOTE_CONFIG_FILE` 指定。

---

# Part 2：快速開始

最常見流程：

```bash
# 1. 初始化
jpnote init

# 2. 從剪貼簿匯入；程式會自動完整預檢、詢問安全整理，再詢問是否正式匯入
jpnote paste

# SSH／pipe 情境可從標準輸入預檢
cat import.json | jpnote paste --stdin --check

# 4. 日常瀏覽
jpnote browse

# 5. Quiz
jpnote quiz

# 6. 健檢
jpnote audit

# 7. 套用所有可確定的安全修正，並列出剩餘人工確認項目
jpnote repair --yes
```

`browse` 內可直接輸入日文、假名、羅馬拼音、alias、stable key、意思／例句、來源與 relation note/source 等內容搜尋。v0.6.5 起，`search` 與 `browse` 共用同一份 searchable document。

---

# Part 3：匯入與資料檢查

## 3.1 從檔案匯入

一般學習流程以檔案匯入為主：

```bash
jpnote import FILE
```

完整 validation、preflight、確認、SQLite commit、undo backup 與 Markdown refresh 成功後，互動終端才會顯示：

```text
是否刪除匯入來源檔？
/path/to/FILE
[y/N]
```

Enter 預設保留。也可明確指定：

```bash
jpnote import FILE --delete-source
jpnote import FILE --keep-source
```

非互動與 `--format json` 在未指定旗標時一律保留，避免 SSH／script 卡在提示。`--check`、`--dry-run`、取消、no-selection 或任何匯入失敗都不會刪檔。正式 apply 前會在 writer lock 內重新確認目前 DB 的 preflight；若確認後已有其他 writer 改變結果，會拒絕匯入並要求重跑。刪除前會驗證來源仍是同一 regular file；symlink、替換或內容修改會拒絕。DB 已成功但刪檔失敗、提示收到 EOF 或 Ctrl-C 時，只會保留來源，匯入仍維持成功。

## 3.2 Windows PowerShell client

repository 的 `clients\windows` 提供正式 Windows client。它需要既有 SSH host／alias（預設 `jpnote`）能連到已安裝 jpnote 0.7.2 以上的 Arch 主機。

安裝會把版本化 module 同時放到 Windows PowerShell 5.1 與 PowerShell 7 的使用者模組路徑：

```powershell
.\clients\windows\Install-JpnoteWindowsClient.ps1
```

預檢與正式匯入：

```powershell
Test-JpnoteFile
Import-JpnoteFile

# 或直接指定檔案
Test-JpnoteFile "$HOME\Downloads\jpnote.json"
Import-JpnoteFile "$HOME\Downloads\jpnote.json"
```

`Import-JpnoteFile` 會先執行遠端完整預檢，顯示結果後要求輸入大寫 `IMPORT`。Windows client 將預檢回傳的 `preflight_token` 帶入正式匯入；若 JSON、normalized plan 或相關 DB outcome 已改變，Arch 會拒絕過期確認。仍有 review／conflict 時，Windows client 也會停止，不會自動加 `--accept-warnings`。

Arch 回傳明確成功後，才詢問是否刪除 Windows 本機來源檔，預設 `[y/N]` 保留。亦可使用 `-DeleteSource`／`-KeepSource`。刪除前重新比對大小、建立／修改時間與 SHA-256；來源消失、被修改、替換或變成 reparse point 時只保留，不影響已成功的 DB transaction。

傳輸使用 `jpnote import --stdin --protocol 1`，直接把 strict UTF-8 JSON bytes 寫入 SSH stdin；上限 16 MiB，不使用剪貼簿、Base64 或遠端 `/tmp` 檔案。

移除目前版本：

```powershell
.\clients\windows\Uninstall-JpnoteWindowsClient.ps1
```

## 3.3 從 Wayland 剪貼簿或標準輸入匯入

預設仍從 Wayland 剪貼簿讀取：

```bash
jpnote paste
```

需要 `wl-paste`。SSH、遠端 shell 或 pipe 情境優先使用正式 import stdin：

```bash
cat import.json | jpnote import --stdin --check
cat import.json | jpnote import - --yes
```

`jpnote paste --stdin` 保留相容性。需要自行建立 machine client 時，使用 versioned protocol，而不是解析人類可讀文字：

```bash
jpnote import --stdin --check --yes --protocol 1 < import.json
jpnote import --stdin --yes --protocol 1 --preflight-token TOKEN < import.json
```

`--stdin` 不需要 `wl-paste`。它只改變文字輸入來源，之後仍和剪貼簿模式進入完全相同的 JSON 解析、schema 驗證、重複偵測、完整預檢、安全整理、確認、備份與正式匯入流程。

因為標準輸入已用來承載 JSON，正式 pipe／SSH 匯入應加 `--yes`；否則程式在讀完 JSON 後沒有剩餘 stdin 可回答確認提示。先用 `--check` 檢查，再用相同檔案搭配 `--yes` 正式匯入。

檔案輸入不需要 `paste --file`；既有指令已提供相同 importer 流程：

```bash
jpnote import FILE
```

v0.6.6.3 起，正常 `import`／`paste` 預設處理整批 payload；`--all` 仍可寫出來作為明確標示與舊腳本相容，但不再是必要參數。

每次正式匯入都會先執行完整、read-only preflight，接著依序詢問：

```text
是否先套用安全修正並重新檢查？[y/N]
是否正式匯入？[y/N]
```

第一個提示只在偵測到 deterministic safe fixes 時出現。選擇 no 不會修改本次 payload；第二個提示選擇 no 時，資料庫與 backup pool 都不會改變。安全整理後一定重新 preflight。

非互動腳本使用：

```bash
jpnote import FILE --yes
jpnote paste --yes
cat import.json | jpnote paste --stdin --yes
```

`--yes` 只略過上述確認並同意安全整理，**不會跳過 validation 或 preflight**。attempt identity conflict、缺少 linked entries、pending relation note conflict 等 blocking 問題，即使加 `--yes` 仍會拒絕匯入。疑似不同 stable key 的 duplicate warning 仍需 `--map-key`、`--skip-item` 或明確 `--accept-warnings`。

## 3.4 真正 read-only 預檢

```bash
jpnote paste --check --all
cat import.json | jpnote paste --stdin --check --all
jpnote import FILE --check --all
```

v0.6.4 起，`--check`：

- 不建立實體 DB
- 不升級實體 DB schema
- 不正規化實體 DB 舊 relation
- 不 prune backup
- 不寫入任何資料
- 使用記憶體快照模擬目前版本的讀取／migration 狀態

JSON 報告：

```bash
jpnote paste --check --all --format json
```

複製報告：

```bash
jpnote paste --check --all --format json --copy-report
```

輸出到檔案：

```bash
jpnote paste --check --all --format json --output report.json
```

## 3.4.1 v0.6.6.3 自動預檢與安全整理

正常正式匯入會顯示與 `--check --all` 相同的完整報告。可安全整理的範圍刻意保守，且只限本次選取項目與同 stable key 的直接相關資料：

- alias 和 display、reading、stable-key 主體完全相同：移除冗餘 alias。
- 本次 payload 內完全相同的 sense：只保留一份。
- 同 meaning 有完整例句與空白例句：保留完整版本。
- 既有資料已有同 meaning 完整例句，而本次只帶空白 sense：略過空白版本。
- 既有資料只有空白 sense，本次帶入完整例句：加入完整版本並移除同 meaning 空白版本。

同 meaning 但有多組**不同的非空例句**不會自動刪除；`audit` 會列為 review。正常 import 不會順便修復其他無關 entry。

只讀檢查仍可明確執行：

```bash
jpnote paste --check --all
cat import.json | jpnote paste --stdin --check --all
jpnote import FILE --check --all
```

這些命令只輸出報告，不顯示正式匯入確認，也不套用 safe fixes。

## 3.4.2 v0.6.6.2 匯入正確性規則

在 v0.6.6.2 中，同一批匯入若出現相同 logical relation identity（`source + target + relation_type`）但不同非空 `note`，會直接拒絕；reciprocal／inverse 兩端若 note 互相矛盾也同樣拒絕，不再採最後一筆覆蓋。`--check` 會依同批 relation 的套用順序模擬狀態，因此同一 reciprocal relation 被兩端重複描述時，後一筆可正確判為 `unchanged`。

若匯入某個 target entry 會讓既有 pending relation 轉為 resolved，preflight 也會模擬這個副作用。舊 pending note 與既有／本次 resolved note 都非空且不同時，會回報 `pending_relation_note_conflict`；正式 import 會完整 rollback，`repair` 也不會自動挑選其中一個。文法不能建立指向自己的 relation。

作答日期可使用正式欄位 `date`；舊資料相容欄位 `attempt_date` 仍可讀取。若兩者同時存在，內容必須相同。`_event_key_generated` 是 jpnote 內部欄位，不可出現在匯入 JSON。

- 同一段文字若包含兩份以上「內容不同」的合法 jpnote JSON，會拒絕匯入；請一次只提供一份 payload。
- 不支援／拼錯的欄位會直接報錯，不再靜默忽略。例如 `readng`、`reslut` 都不會被當成合法欄位。
- `event_key` 會做 NFKC 正規化；zero-width／bidi 等 Unicode format controls 仍會拒絕。
- 文法 relation 的 logical identity 是 `source_key + target_key + relation_type`；`note` 是 metadata。重新匯入同一 relation 的新 note 會更新舊 note，不會再累積另一列。
- `--check` 會顯示 relation 的 new/update/unchanged outcome，和正式匯入採用同一套判定。

## 3.5 選擇部分資料

```bash
jpnote import FILE --item-key 'vocab:猫'
jpnote import FILE --attempt-index 0
```

可重複指定。

## 3.6 key 映射與跳過

```bash
jpnote import FILE --map-key 'vocab:噛む=vocab:かむ'
jpnote import FILE --skip-item 'vocab:噛む'
```

`--map-key` 表示本次資料沿用另一個既有 stable key；`--skip-item` 只跳過本批指定項目。

## 3.7 duplicate warning

正式非互動匯入遇到疑似重複時，需：

- 使用 `--map-key`
- 使用 `--skip-item`
- 或確認確實為不同項目後加 `--accept-warnings`

```bash
jpnote import FILE --accept-warnings
```

## 3.8 dry-run

```bash
jpnote import FILE --dry-run --format json
```

只輸出正規化後的匯入計畫；不寫入資料。

## 3.9 匯入 outcome

項目可能為：

- `new`：新增
- `update`：同 stable key 將更新／補充
- `unchanged`：完全無變更
- `review`：有 duplicate warning，需人工決策

作答可能為：

- `new`：新增
- `duplicate`：同 identity、同內容，正式匯入略過
- `conflict`：同 identity、內容不同，正式匯入拒絕自動覆蓋
- `invalid_links`：引用不存在的 linked entry

同 identity 的 attempt 修正目前採保守策略：**不自動覆蓋歷史紀錄**。請先人工確認，再使用 `jpnote attempts edit` 修改既有資料。

---

# Part 4：日常使用

## 4.1 browse

```bash
jpnote browse
```

支援：

- 日文名稱
- 假名
- 羅馬拼音及常見長音輸入變體
- aliases
- stable key
- 錯題題幹／選項等 metadata

CLI 預先搜尋：

```bash
jpnote browse --query kiseki
```

### Filter

```bash
jpnote browse --type vocab --level N4
jpnote browse --type grammar --level N3
jpnote browse --type mistake --result wrong
```

`--type`、`--level`、`--result` 可重複。

fzf filter 面板快捷鍵：

```text
1 文法
2 單字
3 錯題
4 N5
5 N4
6 N3
7 N2
8 N1
9 wrong
0 partial
```

`未分類` 使用游標 + Space。

其他操作：

```text
Ctrl-F  篩選
Ctrl-R  回到設定檔預設篩選
Space   切換目前 filter 項目
Enter   套用／查看
Esc     取消／離開
```

不使用 fzf：

```bash
jpnote browse --all
jpnote browse --no-fzf
```

JSON：

```bash
jpnote browse --all --format json
```

## 4.2 search

```bash
jpnote search QUERY
jpnote search QUERY --format json
jpnote search QUERY --select
```

`search` 與 `browse` 的 entry 搜尋欄位一致；結果排序仍優先 exact stable key／display／reading／原始 romaji，再到寬鬆 romaji 與一般內容命中。

## 4.3 list

```bash
jpnote list grammar
jpnote list vocab
jpnote list vocab --level N4
jpnote list vocab --select
```

## 4.4 recent

```bash
jpnote recent
jpnote recent --date 2026-07-19
jpnote recent --since 2026-07-01
jpnote recent --type vocab
jpnote recent --source 'TRY! N4'
jpnote recent --all
jpnote recent --no-fzf
```

`--source` 會用完整來源標籤做精確比對，只顯示具有該來源的項目。

## 4.5 編輯項目

```bash
jpnote edit
jpnote edit 'vocab:猫'
jpnote edit 猫
```

使用 `$EDITOR`，預設 `nvim`。目前 edit 不允許直接改 stable key；需要更換 key 時使用明確 merge／重新匯入流程。v0.6.5 起，內容完全未變更的 manual edit 是真正 no-op，不會更新 `updated_at`。

v0.6.6.2 起，edit JSON 也採嚴格欄位清單；例如把 `reading` 拼成 `readng` 會直接拒絕，不會把原 reading 清空。完全 no-op 的 edit/import/repair 不會發布新的 undo backup。

## 4.6 刪除項目

```bash
jpnote delete 'vocab:猫'
jpnote delete 'vocab:猫' --yes
```

沒有 `--yes` 時會要求確認。

## 4.7 Quiz

```bash
jpnote quiz
jpnote quiz --mode mixed --count 10
jpnote quiz --mode vocabulary --count 20 --level N3
jpnote quiz --mode mistake --source 'TRY! N3'
```

Quiz 是 optional、lazy-loaded 的 Python-native TUI。Quiz 套件缺失或故障時，其他 core 指令仍可正常使用。

資料位置：

```text
core: ~/.local/share/jpnote/jpnote.db   schema v5
Quiz: ~/.local/share/jpnote/quiz.db     schema v2
```

可用 `JPNOTE_QUIZ_DB` 指定 Quiz DB。Quiz history 不會寫入教材 `attempts`。

設定畫面：

```text
↑/↓       移動
←/→       調整模式或題數
1–3       直接選模式
Enter     模式 → 題數 → 開始測驗
f         JLPT 多選
o         來源多選
Shift+H   recent history
q         離開
```

作答畫面：

```text
↑/↓       移動選項
Space     選取
Enter     送出
1–4       直接作答
s         跳過
d         顯示來源詳情
q         暫停／退出
```

`reorder_4` 使用 Space 或 1–4 依序加入片段，Backspace 退回上一個片段，選滿四個後 Enter 送出。

History 可查看 recent summary、各題型表現與逐題題目／選項／使用者答案／正解／來源詳情，也能繼續 active、paused 或 interrupted session。若 details 已依 retention 清除，只保留永久 summary。

首版未提供 history export/delete 的 TUI 按鈕；底層 store/API 已支援，之後再補介面。Skip 視為 incorrect。負分／猜題扣分尚未啟用。

---

# Part 5：錯題與作答紀錄

## 5.1 快速查看錯題

```bash
jpnote mistakes
jpnote mistakes --entry 'grammar:のに'
jpnote mistakes --level N4
jpnote mistakes --format json
```

## 5.2 列出所有 attempts

```bash
jpnote attempts list
jpnote attempts list --result wrong
jpnote attempts list --result wrong --result partial
jpnote attempts list --entry 'vocab:猫'
jpnote attempts list --level N4
```

## 5.3 查看／編輯／刪除單筆 attempt

```bash
jpnote attempts show
jpnote attempts show EVENT_KEY
jpnote attempts show EVENT_KEY --no-fzf
jpnote attempts edit EVENT_KEY
jpnote attempts delete EVENT_KEY
jpnote attempts delete EVENT_KEY --yes
```

作答編輯同樣拒絕未知欄位；結構化 `parts`／`options`／order 若因舊資料損壞，show/export 會安全降級並提示先執行 `jpnote audit`，不會直接 traceback。

## 5.4 舊錯題 options migration

預覽：

```bash
jpnote attempts migrate-options
```

套用高信心安全轉換：

```bash
jpnote attempts migrate-options --apply
```

只會修改能安全辨識的舊資料；可疑但無法高信心修正的項目會列出供人工檢查。

## 5.5 attempt identity

未提供 `event_key` 時，jpnote 會為歷史作答產生 stable identity。v0.6.4 會對來源／章節／題號做 NFKC 與空白正規化，因此：

```text
問題3
問題 3
問題３
```

可視為同一 locator。

identity 相同但內容不同時會報 conflict，不會自動改寫既有學習歷史。

---

# Part 6：資料維護

## 6.1 羅馬拼音 audit

```bash
jpnote romaji audit
jpnote romaji audit --include-ok
jpnote romaji audit --format json
```

## 6.2 羅馬拼音安全正規化

預覽：

```bash
jpnote romaji normalize
```

套用：

```bash
jpnote romaji normalize --apply
```

只有 reading 能完整、安全解析且 stored romaji 可證明等價時才自動處理。無法完整解析的小促音、長音等異常組合會 fail closed，不會產生看似正常但漏字的 romaji。

## 6.3 audit

```bash
jpnote audit
jpnote audit --include-info
jpnote audit --format json
jpnote audit --export
```

會檢查 SQLite integrity、foreign keys、JSON 結構、relation enum、控制字元、attempt 日期／時間戳、reorder_4 結構、romaji、duplicate candidates 等。

## 6.4 repair

```bash
jpnote repair
jpnote repair --yes
```

`repair` 只套用 deterministic 修正，包含可安全合併的 legacy relation rows、缺少 reciprocal relation、可安全 NFKC 正規化的 event_key、舊錯題選項高信心 migration、romaji 安全正規化，以及以下資料品質整理：

- alias 去重、去除空白，並移除和 display／reading／stable-key 主體完全相同的 alias。
- 完全相同的 sense 只保留一筆。
- 同 meaning 已有非空例句時，移除空白例句版本。
- 同 meaning 的多組不同非空例句全部保留，並由 audit 列為 review。

完成後會重新 audit；仍有不同非空 relation note、pending／resolved note 衝突、attempt identity 衝突、event_key 正規化撞 key、同 meaning 多組不同非空例句等無法判定的情況會保持原樣並逐筆列出。單筆損壞的 attempt 結構不會再阻斷其他安全 repair 或 Markdown export。

建議升級到 v0.6.6.3 後依序執行：

```bash
jpnote audit --export
jpnote repair --yes
jpnote audit --export
```

只做可確定、安全的修復，不猜測日文語言資料。

## 6.5 duplicate 檢查與 merge

```bash
jpnote duplicates
jpnote duplicates --format json
jpnote merge SOURCE_KEY TARGET_KEY
jpnote merge SOURCE_KEY TARGET_KEY --yes
```

merge 必須是相同 entry type。v0.6.5 起，來源項目既有的 source `added_at` 會保留到合併後的目標項目，不會因 merge 被重設成現在時間。

v0.6.6.1 起，grammar merge 會先模擬所有 resolved／pending relation 的 key remap。若 source 與 target 原本的 relation 在合併後會收斂成同一 logical identity，但存在不同非空 note，或 reciprocal／inverse 兩端 note 衝突，merge 會在寫入前直接拒絕；不會自動挑一筆，也不會留下半套合併結果。

## 6.6 Markdown export

```bash
jpnote export
jpnote export --format json
```

---

# Part 7：備份與復原

## 7.1 手動備份

```bash
jpnote backup
jpnote backup my-label
```

## 7.2 查看 undo 備份

```bash
jpnote backups
```

Undo backup 使用總容量 50 MiB 上限，從最舊開始清理；至少保留最新 snapshot。Recovery snapshot 與 undo pool 分開。

## 7.3 undo

```bash
jpnote undo
jpnote undo --list
jpnote undo --backup 2
jpnote undo --backup undo-20260724T120000-000000-edit.db
```

`--backup` 可使用 `jpnote backups` 顯示的 1 起算編號或完整檔名。沒有指定時，jpnote 會選擇最新且通過 SQLite integrity check 的 backup；若最新一份已損壞，會提示並退回較舊的有效版本。指定損壞 backup 時會在建立 recovery snapshot 之前拒絕。

會修改資料的 CLI／public API 工作流程都經過共用 safe mutation pipeline：先建立 pending snapshot，只有資料庫確實發生變更時才正式發布成 undo backup。完全相同的 re-import、no-op edit 或沒有任何可修項目的 repair 不會占用 undo pool。若 process 在 snapshot 建立後異常終止，下次 writable 啟動會把可確認為 orphan 的有效 `.pending-*` 提升為 undo backup；活著 process 的 snapshot 不會被拿走。

Active undo pool 與 recovery/restored history 各自有 50 MiB 上限，超過時從最舊開始清理，且至少保留最新一份。

---

# Part 8：設定與自訂

```bash
jpnote config show
jpnote config show --format json
jpnote config path
jpnote config edit
jpnote config reset
```

預設 config：

```json
{
  "browse": {
    "types": ["grammar", "vocab"],
    "levels": [],
    "results": []
  },
  "quiz": {
    "mode": "mixed",
    "count": 10,
    "levels": [],
    "sources": [],
    "transparent_background": true,
    "history_detail_cap_mib": 100,
    "prune_after_session": true
  }
}
```

Browse 的 `types: []`、Quiz 的空 `levels`／`sources` 都表示不限制。`transparent_background` 使用終端預設背景；實際透明比例由 Kitty 等終端設定控制。

## 顏色

全域：

```bash
jpnote --color auto browse
jpnote --color always browse
jpnote --color never browse
```

也支援 `JPNOTE_COLOR`、`NO_COLOR`、`TERM=dumb`。

---

# Part 9：進階功能

## 9.1 JSON output

許多讀取／報告指令支援：

```bash
--format json
```

JSON 模式 stdout 維持單一合法 JSON 文件；warning／note 使用 stderr，方便串接 `jq` 或腳本。

## 9.2 非互動使用

沒有 fzf 時，使用：

```bash
--all
--no-fzf
--item-key
--attempt-index
```

## 9.3 architecture check

```bash
jpnote architecture
jpnote architecture --format json
```

用於確認核心與 fzf/UI 耦合情況。

## 9.4 stats

```bash
jpnote stats
jpnote stats --format json
```

---

## 9.x 搜尋與效能行為

v0.6.5 起：

- `search`、`browse --query` 與互動 browse 的 entry searchable fields 共用同一份資料。
- `browse` 會批次載入 entry details 與 attempt links，避免逐筆查詢。
- duplicate candidate 掃描使用 normalized identity index；一般無衝突資料不再做全項目 O(n²) 比對。
- `recent` 的 source metadata 也以批次方式載入。

這些是內部效能改善，不改變 stable key、SQLite schema 或合法 JSON 欄位。

---

# Part 10：除錯與故障排查

## fzf 搜尋異常

先比較：

```bash
jpnote search kiseki --format json
jpnote browse --query kiseki --all --format json
jpnote browse
```

若前兩者正常、互動 browse 異常，記錄：

```bash
fzf --version
```

v0.6.2 起 interactive browse 使用 reload-on-change 搜尋架構，不依賴 `--nth` + `--with-nth` 隱藏 metadata matching。

## 剪貼簿失敗

```bash
command -v wl-paste
command -v wl-copy
```

沒有 Wayland clipboard 工具時改用：

```bash
jpnote import FILE ...
```

## JSON 匯入失敗

先跑：

```bash
jpnote import FILE --check --all --format json
```

v0.6.4 起輸入型別較嚴格：字串欄位不能用 array/object/number 代替；`options.id`、`parts.id`、reorder order 必須是真正整數，boolean 不視為 1/0。

## Quiz 無法啟動

```bash
jpnote quiz --help
jpnote config show
```

Quiz 採 lazy loading。若 optional Quiz package 或 curses 無法載入，`jpnote quiz` 會乾淨失敗而不影響其他 core 指令。可用獨立測試 DB 排查：

```bash
JPNOTE_QUIZ_DB=/tmp/jpnote-quiz-test.db jpnote quiz
```

不要把正式 `jpnote.db` 當作 Quiz DB。

## schema 太新

較舊 jpnote 遇到較新的 DB schema 會拒絕開啟，避免 downgrade 破壞資料。請安裝相同或更新版本。

## 資料品質問題

```bash
jpnote audit --include-info
```

只在 deterministic 情況下執行：

```bash
jpnote repair --yes
```

---

# Part 11：完整指令參考

```text
jpnote init
jpnote manual [--path]

jpnote config show [--format text|json]
jpnote config path
jpnote config edit
jpnote config reset

jpnote import [FILE|-|--stdin] [--protocol 1] [--preflight-token TOKEN]
                   [--all] [--item-key KEY ...] [--attempt-index N ...]
                   [--map-key SOURCE=TARGET ...] [--skip-item KEY ...]
                   [--accept-warnings] [--yes] [--dry-run] [--check]
                   [--copy-report] [--output FILE] [--format text|json]
                   [--delete-source|--keep-source]

jpnote paste [與 import 相同選項]

jpnote list grammar|vocab [--level LEVEL] [--select] [--format text|json]

jpnote browse [--type grammar|vocab|mistake ...]
              [--level N5|N4|N3|N2|N1|unclassified ...]
              [--result wrong|partial ...] [--query QUERY]
              [--all] [--no-fzf] [--format text|json]

jpnote recent [--type grammar|vocab] [--source SOURCE]
              [--date YYYY-MM-DD] [--since YYYY-MM-DD]
              [--all] [--no-fzf] [--format text|json]

jpnote search QUERY [--select] [--format text|json]
jpnote edit [QUERY]
jpnote delete [QUERY] [--yes]

jpnote mistakes [--entry KEY] [--level LEVEL] [--format text|json]

jpnote attempts list [--result correct|wrong|partial|unknown ...]
                     [--entry KEY] [--level LEVEL] [--format text|json]
jpnote attempts show [QUERY] [--no-fzf] [--format text|json]
jpnote attempts edit [QUERY]
jpnote attempts migrate-options [--apply] [--format text|json]
jpnote attempts delete [QUERY] [--yes]

jpnote romaji audit [--include-ok] [--format text|json]
jpnote romaji normalize [--apply] [--format text|json]

jpnote duplicates [--format text|json]
jpnote merge SOURCE TARGET [--yes] [--format text|json]
jpnote audit [--export] [--include-info] [--format text|json]
jpnote repair [--yes] [--format text|json]
jpnote export [--format text|json]
jpnote stats [--format text|json]
jpnote backup [LABEL]
jpnote backups
jpnote undo [--list] [--backup NUMBER_OR_FILENAME]
jpnote architecture [--format text|json]
```

所有子命令都可使用 `--help` 查看目前版本的 argparse 參考。

---

# Part 12：匯入 JSON 格式與規則

最外層必須是 JSON object，至少包含 `items` 或 `attempts` 陣列之一。

```json
{
  "source": "來源",
  "items": [],
  "attempts": []
}
```

## Entry 基本欄位

常用欄位：

```text
key              必填字串
 type             必填；grammar 或 vocabulary
 display          必填字串
 reading          字串
 romaji           字串
 level            字串
 review_group     字串
 aliases          字串陣列
 senses           物件陣列
 meanings         字串陣列（簡寫）
 source           字串
 suggested        boolean
```

Vocabulary 的 stable key 使用：

```text
vocab:<辭典見出し語>
```

一般動詞使用辭書形。名詞與サ變名詞使用不帶 `する` 的名詞形式；完整 `～する` 可放 alias。

Grammar stable key：

```text
grammar:<文法名稱>
```

stable key / event key 禁止控制字元與不可見 Unicode format controls（例如 zero-width space、bidi override）。

## related_grammar

每筆必須同時有：

```json
{
  "key": "grammar:...",
  "relation": "意思相近",
  "note": ""
}
```

合法 relation：

```text
意思相近
對比
容易混淆
前置文法
延伸
替代表達
語氣比較
```

## Attempts

常用欄位：

```text
event_key        可省略；歷史資料由 jpnote 產生
result           correct / wrong / partial / unknown
date             空字串或 YYYY-MM-DD
source
section
question
question_type
prompt
user_answer
correct_answer
options
reason
before
after
linked_entries
```

`linked_entries` 必須使用 `grammar:` 或 `vocab:` stable key。

### options

可使用：

```json
[
  {"id": 1, "text": "A"},
  {"id": 2, "text": "B"}
]
```

或簡寫：

```json
["A", "B"]
```

明確提供 id 時必須是真正正整數；float 與 boolean 不接受。

### reorder_4

必須提供四個非空 parts：

```json
"parts": [
  {"id": 1, "text": "..."},
  {"id": 2, "text": "..."},
  {"id": 3, "text": "..."},
  {"id": 4, "text": "..."}
]
```

`correct_order` 必須是 1、2、3、4 各一次。

`user_order`：

- 已知：1、2、3、4 各一次
- 忘記原答案：可為 `[]`，但 result 不能是 `correct`

---

# Part 13：安全與資料完整性

## Read-only

以下主要是讀取／報告操作：

```text
browse
search
list
recent
mistakes
attempts list/show
romaji audit
duplicates
audit（未加 repair）
stats
backups
architecture
manual
import/paste --check
```

## 會修改資料

```text
init（可能 migration）
import / paste 正式匯入
edit / delete
attempts edit/delete/migrate-options --apply
romaji normalize --apply
merge
repair
undo
```

這些工作流程依功能建立 undo backup 或在 transaction 中執行。Atomic write 用於設定／匯出等檔案；使用者指定的任意 output 父目錄不會被 jpnote 擅自 chmod。

---

# Part 14：版本變更

v0.7.2 新增正式 stdin import protocol 與 repository-owned Windows PowerShell client；protocol preflight token 會拒絕過期確認。Core／Quiz／public import schema 均未變。

v0.7.1 新增 multi-process writer／undo serialization，以及 import-first 的來源檔安全清理流程；成功後可互動選擇刪除，並提供 `--delete-source`／`--keep-source`。Core schema 維持 v5，Quiz schema 維持 v2，public import JSON schema 不變。

v0.7.0 新增 optional Quiz、獨立 `quiz.db` schema v2、session/history、safe generators、正式 `jpnote quiz` CLI/config 與 Python-native TUI。Core schema 維持 v5，public import JSON schema 不變。

版本差異請查看套件根目錄：

```text
CHANGELOG.md
```

每次 release 應同步更新：

- 程式版本
- CHANGELOG
- README
- `docs/USER_GUIDE.md`
- 測試／release smoke test

