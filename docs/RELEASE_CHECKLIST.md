# jpnote Release Checklist

每次正式 release 至少確認：

## 版本與文件

- [ ] 更新 `jpnote_app/config.py` VERSION
- [ ] 更新 `install.sh` VERSION
- [ ] 更新 `CHANGELOG.md`
- [ ] 更新 `README.md`
- [ ] 更新 `docs/USER_GUIDE.md`：指令、參數、合法操作、validation、workflow、debug
- [ ] 更新 `docs/PROJECT_HANDOFF.md`：目前版本、已修問題、未解風險、stability gate、下一步
- [ ] 更新 `docs/ROADMAP.md`
- [ ] 新增或更新 `docs/audits/vX.Y.Z-*.md`：範圍、結果、coverage、已修／新發現／未解、gate
- [ ] 更新 `docs/CHATGPT_CONTINUATION_PROMPT.md`
- [ ] 若 Quiz 規格／行為有變，更新 `docs/QUIZ_V1_SPEC.md`
- [ ] 檢查 `docs/DELIVERY_GUIDE.md` 是否仍符合實際交付流程

## Automated validation

- [ ] `python -m compileall -q jpnote_app`
- [ ] `pytest -q`
- [ ] app-only coverage 已測量並記錄
- [ ] `bash -n install.sh`
- [ ] `git diff --check`
- [ ] fresh install/init smoke test
- [ ] 前一版 → 新版 upgrade smoke test，確認 stats／核心查詢／資料庫不被破壞
- [ ] `jpnote --version`、`jpnote --help`、`jpnote manual` 正常
- [ ] `jpnote manual --path` 指向 bundled USER_GUIDE
- [ ] 若 fzf 行為有變，另跑 real-fzf integration 或實機確認
- [ ] 若 import workflow 有變，驗證完整 preflight 先於寫入、取消不改 DB、`--yes` 不繞過 validation/conflict、safe fix 後重新 preflight
- [ ] 若 mutation／backup 有變，驗證 no-op、operation failure、post-commit export failure、corrupt backup、undo fallback
- [ ] 若資料層有變，以真實 DB **副本**跑 quick_check、foreign_key_check、audit、stats

## Git 與交付

- [ ] working tree 乾淨
- [ ] release commit 已建立
- [ ] annotated release tag 已建立
- [ ] push `main` 與 tag 到 GitHub
- [ ] 產生一個「必須下載」更新檔，並提供精確套用指令
- [ ] 產生 SHA-256；標為選用
- [ ] 視需要產生 source tar.gz／Git bundle；標為備援而非必載
- [ ] 獨立匯出最新版 continuation prompt；標為只有新聊天才需要
- [ ] 最終回覆以「必須下載／僅供參考／新聊天續接用」分類
