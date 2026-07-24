# Changelog

## 0.7.0

- 新增 optional、fault-isolated Quiz 子系統；core 在 Quiz 套件缺失、匯入失敗、runtime 或 storage 錯誤時仍可正常使用 browse/import/audit/repair/export。
- 新增獨立 `${JPNOTE_QUIZ_DB:-~/.local/share/jpnote/quiz.db}`，Quiz schema v2；不寫入既有教材 `attempts`，並保存 immutable question snapshots、active/paused/interrupted/completed/abandoned session、逐題結果與永久題型摘要。
- Quiz history 支援 resume/abandon、100 MiB details retention、oldest-first pruning、JSON export 與安全刪除；TUI 首版提供 recent history、結果摘要與逐題檢視。Export/delete 的 TUI 入口延後，不阻塞 v1。
- 新增 capability-based generators 與 question pool：vocabulary/mistake/mixed modes、日中四選一、意思／讀音是非、歷史 multiple-choice 與 `reorder_4` replay、安全 distractor/fallback、固定 seed 與題數不足回報。
- 漢字詞的意思題在不造成同音歧義時優先以假名出題；錯誤讀音只使用長音、促音、撥音等細微陷阱，不再使用無關詞彙讀音。
- 新增 Python-native curses TUI：方向鍵、Space、Enter、1–4、skip、details、pause/resume、Backspace 重組退回、滑鼠支援，以及 terminal default background／透明背景相容。
- 新增正式 `jpnote quiz` lazy-loaded CLI 與 Quiz config；支援 mode/count、JLPT/source filters、透明背景、history detail cap 與 session 後 pruning，CLI 可用 `--mode`、`--count`、`--level`、`--source` 單次覆寫。
- TUI 支援互動式 JLPT/source 多選、題庫不足確認、recent history、wrong/skipped 與 abandoned filters、未完成 session 繼續，以及每題題目／選項／使用者答案／正解／來源詳情。
- 新增隔離安裝與 release-readiness audit；驗證 fresh install、reinstall launcher backup、manual path、Quiz package 缺失時的 core failure isolation、tracked secret/database guard 與 lazy loader。
- 修正 installed launcher 可能被目前工作目錄或 `PYTHONPATH` 中的同名 `jpnote_app` 遮蔽；新版以 `python3 -I` 與明確 versioned app path 啟動，在 repository 內外都會載入正式安裝版本。
- 正式 release gate：`378 passed, 18 subtests passed`；app-only coverage `76%`；正式 DB 副本 quick/foreign-key/audit/stats/read-only Quiz planning、v0.6.6.4 → v0.7.0 隔離升級、真實安裝與 TUI smoke 全部通過。
- core SQLite schema 維持 v5；public import JSON schema 未新增 Quiz 欄位。Quiz 使用獨立 schema v2。
- 延後項目：TUI history export/delete 按鈕、可選負分／猜題扣分、response timing、spaced repetition 與長期趨勢。

## 0.6.6.4

- grammar manual edit 改為 relation logical diff/upsert；不再以 `source_key OR target_key` 整批刪除，保留未顯示的 pending relation、未修改 relation 的 `source` 與 `created_at`，刪除時也只移除指定 logical pair 與 reciprocal/inverse。
- 新增 `jpnote_app.mutations.execute_safe_mutation()`；CLI import/edit/delete/attempt/repair/merge/romaji 與 `JpnoteCore` 寫入共用 backup、transaction、commit、export 邊界。
- `JpnoteCore.apply_import()` 會在同一 transaction connection 上重建 plan、執行完整 preflight，blocking conflict 不可略過；疑似重複需明確 `accept_warnings=True`。
- raw `sqlite3.connect()` helper 全部使用顯式 close；100 次 preflight 的 file descriptor 不再線性增加。
- pending backup filename 加入 owner PID；下次 writable connect 會提升 dead-process orphan snapshot，保留 corrupt snapshot供人工檢查，並跳過仍存活 process 的 snapshot。
- `jpnote undo --list`／`--backup` 支援指定較舊 backup；預設跳過損壞的最新 backup，且先驗證目標再建立 recovery snapshot。
- recovery/restored history 新增獨立 50 MiB retention cap。
- entry/source timestamp 改用 ISO-8601 microseconds，降低同秒新增／更新誤判。
- `--item-key` 找不到或 `--attempt-index` 超出範圍時直接報錯，不再靜默顯示 no selection。
- 新增 v0.6.6.4 regression tests；完整測試 165 passed、1 skipped、12 subtests，app-only coverage 72%。
- SQLite schema 維持 v5；public import JSON schema 未新增欄位。

## 0.6.6.3

- 正常 `jpnote paste`／`jpnote import FILE` 預設選取整批 payload，並在任何寫入前自動執行與 `--check --all` 相同的完整 read-only preflight。
- preflight 顯示後，以 `是否先套用安全修正並重新檢查？[y/N]` 與 `是否正式匯入？[y/N]` 兩階段確認；選擇 no 時不修改資料庫。
- 新增 `--yes` 供非互動／腳本使用；只略過確認並同意 deterministic safe fixes，仍強制 validation/preflight，且不能越過 attempt conflict、missing linked_entries 或 pending relation note conflict。
- 新增 import-plan safe fixes：移除本次或同 key 既有的冗餘 alias；略過已被既有完整 sense 涵蓋的空白 sense；完整 sense 到達時可移除同 meaning 的既有空白 sense。所有修正只作用於本次相關項目，之後重新 preflight。
- `audit` 新增 `redundant_sense` 與 `same_meaning_multiple_examples`；`repair --yes` 可刪除完全重複 sense，以及同 meaning 已有非空例句時的空白 sense，但保留不同的非空例句。
- alias repair 擴充為移除 alias=display、alias=reading、alias=stable-key 主體，以及重複／空白 alias。
- `ImportPlan.to_dict()` 不輸出內部 safe-fix marker。
- 新增 v0.6.6.3 regression tests，涵蓋 no-write confirmation、`--yes` 不繞過衝突、JSON stdout、safe sense/alias cleanup 與實際 audit/repair。
- SQLite schema 維持 v5；public import JSON schema 未新增欄位。

## 0.6.6.2

- pending relation 解析改為 conflict-aware：既有 resolved／reciprocal relation 的非空 note 與舊 pending note 不同時，import 會在 transaction 內拒絕並完整 rollback；`repair` 會保留衝突資料並列為人工確認，不再以舊 note 靜默覆寫新資料。
- preflight 會模擬 incoming entries／relations 觸發的 pending resolution，並回報 `pending_relation_note_conflict`、安全解析數量與受影響項目。
- attempt duplicate/content comparison 與 identity 使用相同的 locator NFKC／空白正規化，`第１課`／`第1課`、`問題 1`／`問題1` 不再誤報 conflict。
- `jpnote edit` 與 `jpnote attempts edit` 加入嚴格 unknown-field 檢查，欄位拼錯不再被忽略並清空原資料。
- 巢狀 public JSON 的 scalar/wrong-type 輸入改為精確 `ValueError`，不再於 unknown-field 掃描階段噴出 Python `TypeError` traceback。
- 損壞的 attempt `parts/options/order` JSON 在 show/list/mistakes/export/repair 路徑採 fail-soft：保留 audit 診斷、顯示資料警告並略過無效結構，不再讓單筆壞資料阻斷整體操作。
- mutation backup 改為 caller 明確標記資料真的變更後才發布；完全相同的 import/edit/repair 不再新增 undo backup 或擠掉舊的有效還原點。若 DB 已提交但後續 export 失敗，仍保留 pre-mutation backup。
- preflight 不再在記憶體 snapshot 中先正規化 legacy relation label，避免和 real apply 的分類語意不同。
- grammar self relation 在 validation 階段直接拒絕，不再 preflight 顯示 new、apply 卻靜默忽略。
- 新增 pending relation、repair、attempt normalization、strict edit、malformed JSON、fail-soft export/repair、no-op backup 與 legacy/self-relation regression tests。
- 同步更新 USER_GUIDE；SQLite schema 維持 v5。

## 0.6.6.1

- 修正 `merge` 在來源／目標項目帶有 grammar relation 時呼叫已移除 helper 而 crash 的問題；merge relation remap 全面改走 v0.6.6 logical relation helper。
- merge 會在寫入前先模擬 source→target key remap；若 resolved／pending relation 合併後出現不同非空 note，或 reciprocal／inverse note 衝突，整次 merge 直接拒絕且不修改資料。
- 同批 `related_grammar` 的 logical identity 相同但 note 不同時直接拒絕；跨項目的 reciprocal／inverse relation note 矛盾也會在 validation 階段拒絕，不再 last-write-wins。
- preflight 加入 relation batch state simulation；同批 reciprocal relation 已由前一筆建立時，後一筆會正確顯示 `unchanged`。
- attempt 同時提供 `date` 與相容欄位 `attempt_date` 時，兩者若不同直接拒絕；相同則接受。
- `_event_key_generated` 改為純內部欄位，不再接受於 public import JSON。
- 新增 merge × resolved relation、merge × pending relation conflict、batch reciprocal relation、date alias 等 regression tests。
- 同步更新 USER_GUIDE；SQLite schema 維持 v5。
## 0.6.6

- relation preflight/apply 共用 logical identity；note 修正改為更新，不再累積重複 relation rows。
- relation-only import 正確回報 update 並更新 entry `updated_at`。
- attempt auto identity 永遠納入 prompt，修正 reused locator 的碰撞風險。
- public import 拒絕未知欄位；同一輸入含多份不同 jpnote JSON 時拒絕歧義匯入。
- explicit event_key NFKC 正規化；audit/repair 支援既有資料安全修復與 conflict report。
- audit 增加 relation duplicate/conflicting note/reciprocal integrity、attempt identity conflict 與 legacy identity collision-risk。
- repair 整合安全 relation repair、event_key normalization、legacy option migration、romaji normalization，並列出剩餘人工確認項目。
- 一般 connect 不再默默改寫舊 relation label；Core preflight 改用 read-only snapshot。
- 更新 USER_GUIDE；schema 維持 v5。

## 0.6.5

- 統一 core search 與 browse/fzf searchable document；來源、relation note/source、意思與例句等欄位使用相同搜尋語意。
- 移除 raw aliases_json LIKE 搜尋，修正 JSON 標點假陽性。
- 批次載入 browse entry details、attempt links 與 recent sources，降低 N+1 查詢。
- duplicate candidates 改用 normalized identity index。
- manual edit 真正 no-op 不更新 updated_at；merge 保留 source added_at。
- `recent --source` 支援依來源標籤精確篩選。
- 更新 USER_GUIDE 與 browse help；不修改 SQLite schema。

## 0.6.4

Review 前 correctness hardening：

- `--check`／preflight 改用 in-memory DB snapshot；不建立、升級、正規化或 prune 真實資料庫／備份。
- entry upsert 與 attempt import 新增共用 outcome classifier，preflight 與 apply 使用相同判定。
- attempt 同 identity 同內容視為 duplicate；同 identity 不同內容改為 conflict 並拒絕自動覆蓋。
- auto attempt identity 對 source／section／question 做 NFKC 與空白正規化。
- strict JSON validation：字串、boolean、options.id、parts.id、reorder orders 不再接受危險的自動型別轉換。
- 同批相同 stable key 的 display／reading 衝突直接拒絕。
- stable key／event key 拒絕 Unicode Cf format controls（zero-width、bidi override 等）。
- audit 增加 reorder order 完整性、entry/source/attempt timestamp 與 future attempt date 檢查。
- romaji converter 對尾端促音、促音+ん、非法起始長音 fail closed。
- 新增 bundled `docs/USER_GUIDE.md`、`jpnote manual`、`docs/RELEASE_CHECKLIST.md`，安裝器同步安裝 docs。
- 新增 v0.6.4 regression tests；本版不修改 SQLite schema。

## 0.6.3

review queue 前的資料 identity／audit hardening：

- 自動產生的歷史作答 event_key 改為穩定 identity，排除 reason／before／after／linked_entries 等描述性欄位；linked_entries 順序與解析文字更新不再製造新作答 key。
- attempt date 只接受空值或嚴格 `YYYY-MM-DD`；audit 會列出既有不合法日期。
- audit 增加 `PRAGMA quick_check`、`PRAGMA foreign_key_check`、attempt JSON 元素型別、relation enum、來源／例句／alias 控制字元等完整性檢查，遇到壞資料維持 fail-soft。
- safe repair 可正規化舊 relation label，並用 insert-or-ignore + delete 避免唯一鍵碰撞。
- 完全相同的 entry 重新匯入改為真正 no-op，保留原 `updated_at`；ImportResult 新增 `unchanged_entries`。
- replace/edit entry 保留未移除來源原本的 `added_at`，只替新增來源建立時間戳。
- romaji normalize 與 safe repair 不再更新 user-facing `updated_at`，避免 maintenance 大量污染 `jpnote recent`。
- batch duplicate preflight 將同批衝突的兩端都標為 review。
- browse 取得 entry 詳細資料時不再預載完整 attempts history，降低不必要查詢與 payload。
- 新增 v0.6.3 identity/date/no-op/source timestamp/recent/audit/preflight/browse regression tests。
- 本版不修改 SQLite schema 或匯入 JSON schema。

## 0.6.2

深度健檢後的 maintenance release：

- `browse`／共用 fzf 選擇器不再依賴 `--nth` 搜尋被 `--with-nth` 隱藏的 metadata；改為 fzf `--disabled + change:reload(...)`，由 jpnote 自己以原始 token／可見文字／hidden metadata 做搜尋，再把結果 reload 回 fzf。
- 新增 `fzf_search_helper`，羅馬拼音的空格／長音正規化、aliases、stable key 與錯題 metadata 不再受 fzf 欄位顯示規則限制。
- fzf exit code 130／1 視為取消或無結果；真正錯誤（如 exit 2）會顯示 stderr，不再被吞成「使用者取消」。
- `atomic_write_text()` 不再 chmod 任意 `--output` 父目錄；明確指定 `JPNOTE_CONFIG_FILE` 時也保留使用者自訂父目錄權限。jpnote 自己管理的資料／設定／匯出目錄仍維持私有權限。
- import 的 `--format json` 成功輸出維持單一 JSON document；notes／duplicate warnings 改送 stderr。
- manual edit 的 `sources` 改走共用陣列與終端控制字元驗證，避免字串被拆成單字元或 ANSI 控制碼寫入。
- 同批 attempts 若 event_key 相同且內容完全相同會去重；若內容不同則拒絕匯入，不再 silent last-wins。
- `audit` 遇到 `aliases_json` 含非字串元素時改為 fail-soft 回報，不再 crash；`repair` 也不會自動把錯型別 aliases 改寫成字串。
- SQL LIKE 搜尋將 `%`、`_` 視為一般文字，不再意外當萬用字元。
- mutation undo backup 改為成功後才納入容量 pruning；操作失敗會刪除該次 snapshot，避免無效備份占用 50 MiB pool 或擠掉舊備份。
- 新增 `pytest.ini`，直接執行 `pytest -q` 即可。
- 本版不修改 SQLite schema 或匯入 JSON schema。

## 0.6.1.1

- 嘗試以 `--nth` 搭配 `--with-nth` 修正 hidden romaji metadata 搜尋。
- 後續在使用者的 fzf 0.74.0 真實環境與最小重現測試中確認此方案仍無法搜尋被 `--with-nth` 排除的欄位，因此由 v0.6.2 改為 reload-on-change 架構。
- 此版新增的 metadata 生成測試仍保留其價值，但不能代表真實 fzf matching 行為。

## 0.6.1

browse 搜尋修正與舊入口清理：

- 修正互動式 `jpnote browse` 直接輸入搜尋後錯誤變成 0 筆的問題。
- fzf 候選列仍只顯示乾淨的人類可讀欄位，但搜尋改為比對完整原始列，因此名稱、讀音、aliases、romaji 變體、stable key 與錯題 metadata 都可命中。
- browse header 明確顯示「直接輸入搜尋」。
- 移除已由 `jpnote browse` 取代的頂層 `jpnote show` 指令；`jpnote config show` 與 `jpnote attempts show` 保留。
- 本版不修改 SQLite schema 或匯入 JSON schema。

## 0.6

匯入預檢與羅馬拼音正規化：

- 新增 `jpnote import FILE --check --all` 與 `jpnote paste --check --all` 非破壞性批次預檢。
- 預檢共用正式 importer 的 parser、validator、normalize 與 duplicate detector，不修改資料庫。
- 預檢報告一次列出疑似名稱／aliases 衝突、同 stable key 更新、重複 event_key、缺少 linked_entries。
- 支援 `--format json`、`--copy-report` 與 `--output FILE`；只有明確指定 `--copy-report` 才覆蓋剪貼簿。
- 新增 `jpnote romaji audit` 與 `jpnote romaji normalize [--apply]`。
- 既有 romaji 只有在可由 reading 安全證明等價時才批次正規化；不一致資料只回報、不自動覆寫。
- 新匯入的 vocabulary 若 supplied romaji 與 reading 等價，會自動正規化成分拍 Hepburn；輸入格式仍可寬鬆。
- 擴充常見外來語組合轉寫，如 `デュアル → dyu a ru`、`クォーツ → kwō tsu`。
- 一般 `jpnote audit` 新增 `romaji_needs_normalization` 與 `romaji_mismatch` 類型。
- 本版不修改 SQLite schema；schema 仍為 v5。

## 0.5.7

儲存可靠性與互動小修：

- undo 備份由固定 20 份改為總容量 50 MiB，超過時從最舊開始清理；至少保留最新一份。
- SQLite undo／recovery snapshot 改為同目錄暫存檔完成後原子替換，並在保留前執行 `PRAGMA quick_check`。
- undo 復原前也會檢查備份完整性，損壞備份會拒絕覆蓋目前資料庫。
- config 與 Markdown／audit export 改為暫存檔＋`os.replace` 的 atomic write。
- jpnote 資料／備份／匯出／設定目錄盡量設為 `0700`，DB、backup、config、export 檔案盡量設為 `0600`。
- `jpnote backups` 顯示目前 undo 備份總容量與 50 MiB 上限。
- `attempts migrate-options --apply` 只有在存在「疑似有舊選項但無法高信心自動整理」的紀錄時才列警告，並顯示 event_key、來源與題目預覽。
- fzf 篩選面板新增 1–9／0 數字鍵快速切換常用條件；`未分類` 仍可用游標＋Space。
- 新增儲存可靠性、備份容量、權限、可疑舊選項與數字快捷鍵 regression tests。

## 0.5.6.1

- 擴充舊錯題的 inline/slash 選項解析，涵蓋 grammar、reading 等歷史格式。
- 清理已結構化 options 或 reorder parts 仍重複殘留在 prompt 的情況；只有內容完全吻合才自動處理。
- 改善終端換行，避免 `（2）` / `[2]` 等題目佔位符被拆行。
- audit 現在也會回報可安全清理的 prompt residue。
- 新增使用者截圖案例的 regression tests。

## 0.5.6

- attempts 新增結構化 `options_json` 欄位，schema 升級至 v5。
- 匯入 JSON 的 attempt 可提供 `options`，支援 `{id,text}` 物件陣列或簡寫字串陣列。
- 錯題詳細頁／fzf preview 將題幹與選項分開，長選項使用懸掛縮排。
- 顯示層可即時辨識高信心舊格式，因此未遷移資料也能先改善閱讀。
- 新增 `jpnote attempts migrate-options` 與 `--apply`，保守拆分舊 prompt 中的四個選項。
- 舊資料遷移不修改 event_key；無法高信心解析的題目保持原樣。
- `jpnote audit` 會標示可安全拆分的 legacy embedded options。

## 0.5.5

資料安全維護版：

- 同名／同讀音查詢不再以 `LIMIT 1` 任意選擇；只有唯一結果才自動解析。
- 重複 `event_key` 現在是真正 no-op，不會偷偷增加既有錯題的 linked entries。
- 巢狀 SQLite transaction 改用 SAVEPOINT，內層 context 不再提前 commit。
- stable key／event key 加入空值與控制字元驗證；一般文字拒絕危險終端控制碼。
- `related_grammar.key` 與 `relation` 改為必填，不再猜成 `grammar:` 或「意思相近」。
- `reorder_4` 四個 parts.text 必須都有內容。
- `repair` 不再無聲清空損壞 aliases JSON；不支援的假名組合不再寫入混合 kana/Latin 羅馬拼音。
- 安裝器改為原子替換 launcher，不再跟隨並覆寫既有 symlink 目標。
- 舊版 jpnote 遇到較新的 schema version 會拒絕開啟，不再把版本號降回舊版。
- 選擇性匯入會移除另一端未被選取的 batch duplicate warning。
- 修正錯題列表 `N4、`：未分類關聯現在顯示為 `N4、未分類`。

## 0.5.4.2

- 修正 checkbox 篩選群組語意：類型、等級或錯題結果未勾選時都表示「全部」，不再錯誤回傳零筆。
- 同一群組內採 OR、不同群組間採 AND；例如 N4＋N5 顯示兩個等級，單字＋N4 顯示 N4 單字。
- `wrong`／`partial` 只在「錯題」被明確勾選時顯示與生效。
- 取消勾選「錯題」時會清除暫存的 wrong／partial，避免隱藏條件殘留。
- 設定檔允許 `browse.types: []`，其語意為全部類型；預設值仍是文法＋單字。
- 本版不修改 SQLite schema、匯入 JSON schema 或 Markdown 格式。

## 0.5.4.1

- 修正選擇錯題但未勾 `wrong`／`partial` 時錯誤回傳零筆；空結果條件現在表示全部錯題。
- 錯題篩選摘要在全選或全不選時顯示「錯題＝全部」。
- 篩選面板改為單一 fzf 程序；Space 透過短期狀態檔、`execute-silent` 與 `reload` 局部更新，不再每次切換都重開 fzf。
- 新增 `~/.config/jpnote/config.json` 本機偏好設定，尊重 `XDG_CONFIG_HOME` 與 `JPNOTE_CONFIG_FILE`。
- 新增 `jpnote config show/path/edit/reset`；`jpnote init` 會在設定不存在時建立預設檔。
- browse 預設仍為文法＋單字；`Ctrl-R` 改為回到設定檔中的預設條件。
- 本版不修改 SQLite schema、匯入 JSON schema 或 Markdown 格式。

## 0.5.4

- 新增 `jpnote browse` 統一瀏覽文法、單字與錯題。
- 支援可重複的 `--type`、`--level`、`--result`、`--query` 與 JSON 輸出。
- fzf 主畫面固定顯示作用中條件與快捷鍵；`Ctrl-F` 開啟 checkbox 式多選面板。
- 錯題可依 JLPT 等級與 wrong／partial 篩選，並使用 B-Compact 即時預覽。
- 搜尋、browse 與 fzf 隱藏欄共用羅馬拼音正規化；支援省略長音符號、空格、大小寫與常見長音鍵盤寫法。
- 寬鬆羅馬拼音只用於搜尋，不影響 stable key、aliases、合併或重複判定。
- 本版不修改 SQLite schema、匯入 JSON schema 或 Markdown 格式。

## 0.5.3

- B-Compact 詳細頁與列表加入低干擾 ANSI 配色。
- 新增全域 `--color auto|always|never` 與 `JPNOTE_COLOR`。
- auto 模式尊重 `NO_COLOR`、`TERM=dumb` 與 TTY 狀態。
- JSON 輸出永遠不含 ANSI；管線與重新導向在 auto 模式保持純文字。
- fzf 選單與預覽在啟用配色時使用 `--ansi`，stable key 仍作為不可見選取 token。
- 本版只改 terminal presentation／CLI adapter；資料庫 schema、JSON 與 Markdown 不變。

## 0.5.2

- 詳細頁改為使用者確認的 B-Compact 緊湊卡片布局。
- 文法、單字、錯題以框線標頭顯示 display、等級與 stable key／event key。
- 主要區塊之間只保留一個空白行，同區塊內容不插入多餘空行。
- 新增 CJK 終端顯示寬度與自動換行處理。
- `attempts list` 改為緊湊摘要；`attempts show` 保留完整卡片。
- `recent --all` 依新增／更新分組呈現。
- fzf 項目、近期變更與作答選擇加入右側即時卡片預覽。
- 本版只修改 presentation／CLI adapter；資料庫 schema、JSON 與 Markdown 不變。

## 0.5.1

- 新增 `jpnote recent`，預設以本地日期查看今天新增／更新的項目。
- `jpnote recent` 在互動終端預設使用 fzf 篩選並可查看完整項目。
- 支援 `--type grammar|vocab`、`--date`、`--since`、`--all`、`--no-fzf` 與 JSON 輸出。
- 日期篩選改由 Python 解析 ISO-8601 時區，避免凌晨時被 UTC 日期排除。
- 修正文法關聯 enum：正式使用 `意思相近／對比／容易混淆／前置文法／延伸／替代表達／語氣比較`。
- 舊關聯名稱仍可匯入，並在開啟資料庫時安全正規化為正式名稱。
- `搭配使用` 等未定義類型仍會被拒絕。

## 0.5.0

- 疑似重複匯入可直接將 incoming key 映射至既有 stable key，不必手動修改 JSON。
- 新增 `--map-key SOURCE=TARGET` 與 `--skip-item KEY` 非互動匯入選項。
- key 映射會同步更新錯題關聯與文法關聯。
- 新增 `jpnote attempts list/show/edit/delete` 作答紀錄管理。
- 作答編輯與刪除使用 stable `event_key`，並在修改前自動備份。
- audit/repair 會移除和主要 display 完全相同的多餘 alias。
- 核心新增 `import_resolution` 與 `attempt_services`，仍不依賴 fzf。
- 修正 SQLite context manager 過去只提交但不關閉連線的問題；巢狀 transaction 仍安全運作。

## 0.4.2

- 修正有作答紀錄時 `jpnote show` 因重複傳入 `accuracy` 而崩潰。
- 作答統計新增嚴格正確率與加權正確率；`partial` 在加權正確率中以半分計算。
- Markdown 文法輸出同步顯示兩種正確率。
- 新增 `partial` 統計與 CLI 顯示的回歸測試。

## 0.4.1

- 允許登記忘記原始排列的歷史四格錯題：`user_order` 可留空，但不得標記為 correct。
- 四格題文字輸出會將空的 `user_order` 顯示為「未記錄」。
- 疑似重複匯入提示改成明確的 continue/cancel 語意，並強調繼續不等於合併。
- 更新相關測試與文件。

## 0.4.0

- 將單檔腳本拆成核心、儲存、匯出與可選 fzf adapter。
- 新增錯題／作答紀錄與四格重組題驗證。
- 新增文法關聯、未收錄關聯佇列與自動解析。
- 新增外來語語源資料。
- 新增 list、mistakes、duplicates、merge、audit、repair、architecture。
- 新增文字與 JSON 雙輸出。
- 新增 JLPT＋五十音排序。
- 新增 v0.3 → v0.4 自動 migration 與 migration 前備份。
