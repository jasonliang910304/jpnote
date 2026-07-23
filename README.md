# jpnote v0.6.6.3

本版將原本 1,200 多行的單檔腳本拆成可重用的核心模組與可選介面層。


## v0.6.6.3 Import safety / data-quality patch

- 一般 `jpnote paste`／`jpnote import FILE` 現在會先自動執行整批、read-only 的完整 preflight，再以 yes/no 決定是否套用安全整理與正式匯入；不必再手動連續執行 `--check --all` 和正式匯入。
- 新增 `--yes` 給非互動腳本使用；它只略過確認提示，不能略過 validation、preflight、attempt conflict、missing links 或 pending relation note conflict。
- preflight 可列出並選擇性整理本次資料中的冗餘 alias 與重複 sense；套用後一定重新 preflight，尚未確認前不修改資料庫。
- `audit`／`repair` 新增安全 sense 去重：完全相同 sense 去重；同 meaning 的空例句版本若已有完整例句則移除；不同非空例句保留並列為 review。
- alias cleanup 現在也移除和 reading 或 stable-key 主體完全相同的 alias。
- 正常 import/paste 預設整批；`--all` 保留相容性。進階使用仍可用 `--item-key`／`--attempt-index` 部分匯入。
- SQLite schema 仍為 v5，public import JSON schema 沒有新增欄位。


## v0.6.6.2 Correctness / recovery patch

- Pending relation 解析改為 conflict-aware；舊 pending note 不會再覆寫較新的 resolved note。Import 遇衝突會 rollback，repair 則保留原資料並交由 audit 列出。
- Attempt duplicate comparison 與 identity generation 共用 locator normalization。
- Entry／attempt 手動 edit 拒絕未知欄位；巢狀 wrong-type import 會回傳清楚的 validation error，不再 traceback。
- 損壞的 attempt 結構在顯示、Markdown export 與 repair 採 fail-soft，同時仍由 audit 回報。
- 真正 no-op 的 mutation 不發布 undo backup，避免擠掉較早且有用的還原點。
- Legacy relation 的 preflight/apply 分類一致，self relation 直接拒絕。
- SQLite schema 仍為 v5。


## v0.6.6.1 Merge / relation consistency patch

- 修正帶有 grammar relation 的 entry 執行 `jpnote merge` 時可能 `NameError` crash。
- merge 先建立完整 relation remap plan，再一次寫入；resolved／pending relation 若因 merge 收斂成同一 logical identity 且 note 衝突，會在任何資料修改前拒絕。
- 同批匯入的相同 relation identity 與 reciprocal／inverse relation 不再允許不同非空 note 互相覆蓋。
- preflight 會模擬同批 relation 已建立的狀態，使 reciprocal 重複描述的 new／unchanged 判定與正式 import 更一致。
- `date` 與 legacy `attempt_date` 同時存在時必須一致；`_event_key_generated` 不再是合法 public JSON 欄位。
- SQLite schema 仍為 v5。

## v0.6.6 Correctness + legacy data reconciliation

- Relation import/preflight 共用邏輯 identity：`source + target + relation_type`；`note` 改為關聯 metadata，修正 note 時更新既有 relation，不再累積邏輯重複列。
- Relation-only import 會正確標為 entry update 並更新 `updated_at`；preflight 會列 relation new/update/unchanged。
- Attempt auto identity 永遠納入正規化 prompt，避免相同來源／題號／答案但不同題目文字互相碰撞。
- 匯入會拒絕未知欄位與同一段文字中的多份不同 jpnote payload，降低拼錯欄位或剪貼簿歧義造成的靜默資料遺失。
- Explicit event_key 會 NFKC 正規化；audit/repair 可檢查並安全修復既有可正規化 key。
- `audit` 新增 relation 邏輯重複、不同 note 衝突、缺 reciprocal、reciprocal note 衝突、attempt identity 重複／衝突與舊 identity collision-risk 檢查。
- `repair` 現在同時執行 deterministic relation repairs、event_key NFKC、舊錯題 options 高信心 migration 與 romaji 安全正規化；完成後重新 audit 並列出所有仍需人工確認的項目。
- 一般 `connect()` 不再默默正規化舊 relation label；資料值修復改由明確 `repair` 執行，讓 `audit` 能先看見歷史問題。
- `JpnoteCore.preflight_import()` 改用 read-only in-memory snapshot，與 CLI `--check` 一致。
- 本版不修改 SQLite schema；仍為 schema v5。匯入 JSON 欄位沒有新增，但未知欄位現在會直接拒絕。

## v0.6.5 Search / history / performance cleanup

- Core `search` 與 `browse` 共用同一份完整 searchable document，涵蓋名稱、讀音、romaji、aliases、意思／例句、來源與 grammar relation note/source；互動搜尋與 CLI 搜尋不再各自維護不同欄位。
- 不再搜尋 raw `aliases_json` serialization，避免 `[`、`]` 等 JSON 標點造成假陽性。
- `browse` entry hydration 與 attempt links 改為批次查詢，移除主要 N+1 查詢路徑。
- duplicate candidate 掃描改用 identity index；無衝突的大批資料不再做 O(n²) 全配對比較。
- 完全沒有內容變化的 manual edit 不更新 `updated_at`；merge 保留來源原本的 `added_at`。
- `jpnote recent` 新增 `--source` 精確來源篩選，recent sources 也改為批次載入。
- USER_GUIDE 同步更新本版所有合法操作與搜尋語意。

## v0.6.4 Review 前 correctness hardening

- `import/paste --check` 改為真正 read-only：不存在 DB 時不建立檔案，既有 DB 也只複製到記憶體快照後進行 schema/資料值 migration 模擬，不改寫真實 DB、relation 或 backup pool。
- preflight 與正式 import 共用 entry／attempt outcome classifier；`new`、`update`、`unchanged`、`duplicate`、`conflict`、`invalid_links` 的判定不再各做一套。
- attempt identity 相同但內容不同時改為 conflict，正式匯入拒絕靜默略過／覆蓋；相同內容仍維持 idempotent duplicate。
- 歷史 attempt locator 加入 NFKC 與空白正規化，`問題3`／`問題 3`／`問題３` 不再因純格式差異產生不同 auto event key。
- 匯入 JSON 改為較嚴格型別驗證：字串欄位不再自動 `str()` 任意資料；options/parts/order 的 id 必須是真正整數，boolean/float 不再偷偷轉成整數。
- 同批相同 stable key 若 `display`／`reading` 核心欄位互相矛盾，直接拒絕，不再 silent merge。
- stable key／event key 拒絕 zero-width、bidi override 等 Unicode format control，避免肉眼相同的隱形 key。
- `reorder_4` audit 補上 correct_order/user_order 的 1–4 完整排列檢查；audit 也新增 entry/source/attempt timestamp 與未來 attempt date 提醒。
- romaji converter 對不完整促音或不合法起始長音採 fail-closed，不產生漏字的看似正常 romaji。
- 新增完整 `docs/USER_GUIDE.md` 與 `jpnote manual`／`jpnote manual --path`；之後每個 release 都把手冊更新列入 release checklist。
- 本版不修改 SQLite schema，仍為 v5；沒有新增 JSON 欄位，但 validation 規則更嚴格。

## v0.6.3 資料 identity 與 audit hardening

- 自動產生的歷史作答 `event_key` 改用穩定 identity：日期、來源、章節、題號、題型與使用者作答為核心；解析文字與 linked_entries 順序不再造成不同 key。未來 live quiz 仍應使用明確 event_key。
- attempt `date` 匯入／編輯時只接受空值或 `YYYY-MM-DD`；既有不合法日期由 `jpnote audit` 回報。
- `audit` 加入 SQLite `quick_check`、`foreign_key_check`、作答 JSON 結構、relation enum、來源／例句／alias 控制字元與日期檢查，並維持 fail-soft。
- 完全相同的 entry 重新匯入現在是真正 no-op，不再更新 `updated_at`；匯入結果新增 `unchanged_entries`。
- edit／replace entry 保留既有 source 的原始 `added_at`，只替新來源建立新時間戳。
- romaji normalize 與 safe repair 屬 maintenance，不再改 entry `updated_at`，避免污染 `jpnote recent`。
- batch duplicate preflight 會把衝突兩端都標成 review，不再只標第一端。
- browse 不再為每個 entry 預先載入完整 attempt history，降低 review queue 前不必要的 N+1 負擔。
- 本版不修改 SQLite schema 或匯入 JSON schema。

## v0.6.2 深度健檢修正

- `jpnote browse` 的互動搜尋改由 jpnote 自己過濾候選資料，再透過 fzf `change:reload` 更新清單；fzf 只負責 UI、選擇與 preview。這避免 `--with-nth` 導致 hidden romaji／aliases metadata 無法被搜尋。
- 真正的 fzf 執行錯誤不再被當成 Esc 取消。
- 任意 `--output` 目錄與明確指定的 `JPNOTE_CONFIG_FILE` 父目錄不再被 jpnote 擅自 chmod 0700。
- JSON import 成功輸出保持純 JSON，warnings 送 stderr。
- `sources`、同批 event_key、audit 壞 aliases、LIKE `%`／`_`、失敗操作備份生命週期都加入安全修正。
- 本版 schema 仍為 v5，匯入 JSON schema 未變。


## v0.6 匯入預檢與羅馬拼音正規化

### 非破壞性匯入預檢

剪貼簿與檔案匯入共用正式 importer 的 JSON 解析、驗證與重複檢查：

```bash
jpnote paste --check --all
jpnote import data.json --check --all
```

預檢不修改資料庫，會一次列出：

- 疑似名稱／aliases 重複衝突
- 同 stable key（正式匯入時會更新／合併）
- 重複 event_key（正式匯入時會略過）
- 作答紀錄缺少 linked_entries

JSON 報告與剪貼簿輸出：

```bash
jpnote paste --check --all --format json
jpnote paste --check --all --format json --copy-report
```

`--copy-report` 只有明確指定時才覆蓋剪貼簿。也可用 `--output FILE` 另存報告。

### 羅馬拼音正規化

匯入時若假名 reading 可安全轉換，且 supplied romaji 與 reading 等價，會自動正規化成分拍 Hepburn：

```text
unten       → u n te n
kyoshitsu   → kyō shi tsu
shimbun     → shi n bu n
```

既有資料可先 audit：

```bash
jpnote romaji audit
jpnote romaji audit --include-ok
```

預覽安全可修項目：

```bash
jpnote romaji normalize
```

確認後套用：

```bash
jpnote romaji normalize --apply
```

只有「缺少 romaji」或「只是空格／長音／n-m 表記差異」等可證明等價的項目會自動修改。若現有 romaji 與 reading 推導結果不同，會標成需確認並保持原值。

本版也擴充常見外來語假名組合，例如 `デュアル → dyu a ru`、`クォーツ → kwō tsu`。


## v0.5.7 儲存可靠性與快捷篩選

- undo 備份改為 50 MiB 總容量管理，不再固定保留 20 份。
- backup 建立與 restore 加入 SQLite `quick_check`；備份檔先在同目錄完成後再原子替換。
- config、Markdown 與 audit export 使用 atomic write，降低中斷時留下半個檔案的風險。
- 本機資料目錄與個人資料檔案使用較嚴格的 `0700`／`0600` 權限（支援 POSIX 權限時）。
- `jpnote backups` 顯示目前容量與 50 MiB 上限。
- `attempts migrate-options --apply` 不再固定顯示模糊警告；只有真的有可疑未處理項目時才列出 event_key、來源與題目預覽。
- fzf filter 面板支援數字鍵直接切換常用條件：1 文法、2 單字、3 錯題、4 N5、5 N4、6 N3、7 N2、8 N1、9 wrong、0 partial。`未分類` 使用游標＋Space。


## v0.5.6.1 舊錯題解析與換行修正

- 擴充舊錯題選項辨識，可安全處理 `...。1 A／2 B／3 C／4 D` 與跨行 reading 選項。
- 若 `options` 已存在但題幹仍殘留同一組選項，預覽與 migration 會在內容完全吻合時清除重複尾巴。
- `reorder_4` 若題幹重複內嵌四格內容，且與 `parts` 完全吻合，會安全移除重複尾巴。
- `（2）`、`(2)`、`[2]` 等答題位置標記在終端換行時視為不可分割單位，避免括號與數字被拆到不同列。
- `jpnote attempts migrate-options --apply` 可再次執行，會處理新辨識到的舊資料與殘留文字；有歧義的資料維持不變。


## v0.5.6 錯題選項結構化與舊資料安全拆分

本版聚焦在錯題閱讀體驗與未來 quiz 的資料基礎：

- attempts 新增結構化 `options`／SQLite `options_json`。
- 新匯入資料可直接提供 `options: [{"id": 1, "text": "..."}, ...]`，也接受簡寫字串陣列。
- 錯題詳細頁與 fzf preview 將「題目」和「選項」分區顯示；長選項使用懸掛縮排。
- 舊資料即使尚未遷移，顯示層也會對高信心格式即時拆分，不再把 `選択肢：1 ... 2 ...` 全擠在題幹。
- 新增 `jpnote attempts migrate-options` 預覽可安全拆分的舊資料；加 `--apply` 才正式寫入。
- 遷移只處理能明確辨識完整 1～4 選項的題目；不確定的資料保持原樣。
- schema 升級到 v5，升級前會建立 undo 備份；event_key 不會因選項拆分而改變。

建議升級後先檢查：

```bash
jpnote attempts migrate-options
jpnote attempts migrate-options --apply
```

第二個指令會先建立備份，再把可安全辨識的舊題目拆成 `prompt + options`。

## v0.5.5 資料安全維護版

本版先處理完整健檢發現的高風險邊界問題，不新增資料 schema。重點包括：

- 同名／同讀音不再任意選第一筆，避免 edit/delete 指到錯誤 stable key。
- 重複 `event_key` 真正略過，不再修改既有錯題的 linked entries。
- 巢狀 SQLite transaction 改用 SAVEPOINT，內層不會提前 commit。
- stable key、event key 與終端控制字元驗證加強。
- `related_grammar.key`／`relation` 改為必填；`reorder_4` 四格不可為空。
- `repair` 遇到損壞 aliases JSON 只報告、不清空；無法完整轉寫的假名不自動寫入 romaji。
- 安裝器安全替換既有 symlink；舊版程式拒絕開啟較新的 schema。
- 選擇性匯入不再保留指向未選項目的 batch duplicate warning。
- 錯題列表的 `N4、` 改為明確的 `N4、未分類`。


## v0.5.4.2 篩選群組語意修正

篩選面板現在統一採用「同組 OR、跨組 AND、空白群組＝全部」：

```text
類型未勾選      → 全部類型
等級未勾選      → 全部等級
N4＋N5          → N4 或 N5
單字＋N4        → N4 單字
```

`wrong`／`partial` 只有在「錯題」被明確勾選時才顯示；取消錯題會一併清除暫存結果條件。設定檔仍預設文法＋單字，但可用 `"types": []` 表示全部類型。


## v0.5.4.1 篩選修正與可設定預設值

- 選擇錯題但沒有勾 `wrong`／`partial` 時，現在代表「全部錯題」，不再回傳空結果。
- 篩選面板在同一個 fzf 程序內透過 `execute-silent`＋`reload` 更新 checkbox，Space 不再反覆關閉並重開 fzf。
- `Ctrl-R` 回到使用者設定的預設條件。
- 新增本機設定檔，預設為文法＋單字、全部等級、全部錯題結果。

```bash
jpnote config show
jpnote config path
jpnote config edit       # 使用 $EDITOR，預設 nvim
jpnote config reset
```

預設設定檔位於 `~/.config/jpnote/config.json`（尊重 `XDG_CONFIG_HOME`）：

```json
{
  "browse": {
    "types": ["grammar", "vocab"],
    "levels": [],
    "results": []
  }
}
```

`levels: []` 表示全部等級；`results: []` 表示錯題結果不設限。這是 CLI 本機偏好，不屬於 jpnote 匯入 JSON schema。

## v0.5.4 統一瀏覽與羅馬拼音搜尋

```bash
jpnote browse
jpnote browse --type vocab --level N4 --all
jpnote browse --type mistake --result wrong --all
```

`Ctrl-F` 開啟 checkbox 式篩選；主畫面與面板都會顯示快捷鍵提示。一般搜尋與 fzf 可使用省略長音符號、空格的羅馬拼音，例如 `kyoshitsu`、`kyoushitsu`、`kyooshitsu` 都可找到 `kyō shi tsu`。

## v0.5.3 可選終端配色

B-Compact 排版加入低干擾 ANSI 配色：框線與區塊標題、JLPT 等級、stable key、近期新增／更新，以及 wrong／partial／correct 狀態。

```bash
jpnote --color auto browse              # 預設；TTY 自動開啟
jpnote --color always recent --all      # 強制顯示
jpnote --color never mistakes           # 關閉顏色
```

也可設定 `JPNOTE_COLOR=auto|always|never`。`NO_COLOR`、`TERM=dumb`、非 TTY 輸出會在 auto 模式關閉顏色；`--format json` 永遠不含 ANSI。fzf 選單與預覽在啟用顏色時會使用 `--ansi`。

## v0.5.2 緊湊卡片排版

文字詳細頁採用框線標頭與單一空白行分區；列表保持一行一筆。

- `browse` 預覽、`search`、`mistakes`、`attempts show` 使用 B-Compact 詳細布局
- `attempts list` 改為緊湊摘要
- `recent --all` 依新增／更新分組
- fzf 選擇器加入右側即時預覽
- JSON、SQLite 與 Markdown 格式完全不變

## v0.5.1 快速查看近期變更

```bash
jpnote recent                         # 今天，互動終端預設開 fzf
jpnote recent --type grammar          # 今天只看文法
jpnote recent --all                   # 不開 fzf，直接列出
jpnote recent --date 2026-07-17       # 指定本地日期
jpnote recent --since 2026-07-15      # 從指定日期起
jpnote recent --format json           # 結構化輸出
```


## 安裝

```bash
mkdir -p /tmp/jpnote-v0.6

tar -xzf ~/Downloads/jpnote-v0.6.tar.gz \
  -C /tmp/jpnote-v0.6 \
  --strip-components=1

/tmp/jpnote-v0.6/install.sh
jpnote init
```

`jpnote init` 會升級既有資料庫、重新產生 Markdown，並在設定檔不存在時建立預設設定；不會重建或清空資料。

## 架構

```text
jpnote_app/
├── api.py              未來 mimir Web API 可直接使用的 facade
├── attempt_services.py 作答紀錄編輯／刪除的核心流程
├── import_resolution.py stable key 映射與跳過規則
├── import_preflight.py 非破壞性匯入預檢報告
├── validation.py       JSON 解析、正規化、四格題驗證
├── repository.py       SQLite 查詢與資料讀寫
├── services.py         匯入、關聯、防重、合併等核心流程
├── audit.py            資料檢查與安全 repair
├── sorting.py          JLPT 與五十音排序
├── romaji.py           已知假名讀音的羅馬拼音轉換
├── romaji_maintenance.py 羅馬拼音 audit／安全正規化
├── export_markdown.py  Markdown 閱讀檔
├── db.py               migration、備份與復原
├── presentation.py     純文字卡片、列表與 CJK 寬度處理
├── browsing.py         統一 browse 查詢與結構化篩選
├── search_normalization.py 羅馬拼音寬鬆搜尋索引
├── preferences.py      XDG 本機偏好設定
├── fzf_filter_helper.py 單一 fzf session 的暫存篩選狀態
├── ui_fzf.py           可選的 Terminal 選擇與預覽 adapter
└── cli.py              CLI 參數與文字／JSON 路由
```

只有 `cli.py` 會載入 `ui_fzf.py`。核心模組不依賴 fzf，並回傳 Python dict、dataclass 或 JSON 可序列化資料。

## 主要新功能

- `jpnote list grammar|vocab [--level N3] [--format json]`
- 單字依 N5 → N1，再依假名五十音排序
- `attempts` 作答／錯題匯入
- `reorder_4` 保存完整正確順序；歷史錯題可將未知的 user_order 留空
- `jpnote mistakes`
- 單字作答次數、答對、答錯與正確率
- `related_grammar` 文法雙向關聯
- 未收錄相關文法暫存，日後自動補連結
- 外來語語源欄位與 `外來語.md`
- 同批與既有資料的保守重複警告
- `jpnote duplicates`
- `jpnote merge SOURCE TARGET`
- `jpnote audit [--export] [--include-info]`
- `jpnote repair`
- list/search/browse/stats/mistakes/audit 等非互動輸出支援 JSON
- `jpnote architecture --format json` 可檢查 fzf 耦合狀態

## 無 fzf 使用

```bash
jpnote import data.json --all
jpnote import data.json --item-key grammar:のに
jpnote list vocab --format json
jpnote search のに --format json
jpnote browse --query のに --format json --no-fzf
jpnote audit --format json
```

沒有安裝 fzf 時，只有需要互動選擇的操作不可用；核心與非互動指令都能正常執行。

## JSON 格式變更

v0.4 新增：

- 最外層 `attempts`
- 文法項目的 `related_grammar`
- 單字的 `origin_type`、`origin_language`、`origin_word`、`origin_note`

因此舊的生成提示詞需要更新。程式仍相容舊的 `items` 格式，但舊提示詞不會產生錯題、文法關聯與語源資料。

## 0.4.2 操作修正

- 歷史四格重組錯題若已忘記原始排列，可使用 `user_order: []` 並明確填 `result: "wrong"`。
- 有完整 `user_order` 時，程式仍會強制 1、2、3、4 各一次並自行判定結果。
- 疑似重複警告改為 `[c]` 繼續建立不同項目、`[x]` 取消，避免將 `yes` 誤解成自動合併。

## 0.4.2 統計修正

- `jpnote browse` 可直接搜尋並查看有作答紀錄的項目；舊的頂層 `jpnote show` 已在 v0.6.1 移除。
- v0.6.1.1 修正互動 browse 的羅馬拼音 hidden metadata 搜尋；日文、讀音、aliases、romaji 變體與 stable key 都可作為 fzf 搜尋目標。
- 嚴格正確率只把 `correct` 算作正確。
- 加權正確率把 `partial` 算作半分，適合記錄靠刪去法或低信心答對。

## 0.5.0 重複匯入處理

疑似重複時，互動介面可直接選擇：

- 沿用既有 stable key 並合併本次資料
- 確認為不同項目
- 跳過本次項目
- 取消整次匯入

非互動環境可使用：

```bash
jpnote import data.json --all \
  --map-key 'vocab:噛む=vocab:かむ'
```

映射會同步改寫本次 `attempts[].linked_entries` 與文法關聯，避免錯題仍指向舊 key。

也可跳過單一項目：

```bash
jpnote import data.json --all --skip-item 'vocab:噛む'
```

## 0.5.0 作答紀錄管理

```bash
jpnote attempts list
jpnote attempts list --result partial
jpnote attempts show
jpnote attempts edit
jpnote attempts delete
```

`edit` 使用 `$EDITOR`，預設為 Neovim。每次編輯與刪除前都會自動備份，並重新產生 Markdown。

`with connect()` 會在最外層 context 結束時真正關閉 SQLite 連線；核心內部的巢狀 transaction 使用 SQLite SAVEPOINT，不會由內層 context 提前提交外層交易，適合未來長時間運行的 mimir API。
