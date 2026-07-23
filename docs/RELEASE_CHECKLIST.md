# jpnote Release Checklist

每次正式 release 至少確認：

- [ ] 更新 `jpnote_app/config.py` VERSION
- [ ] 更新 `install.sh` VERSION
- [ ] 更新 `CHANGELOG.md`
- [ ] 更新 `docs/PROJECT_HANDOFF.md`：目前狀態、已修問題、未解風險與下一步
- [ ] 若 Quiz 規格／行為有變，更新 `docs/QUIZ_V1_SPEC.md`
- [ ] 新增或更新 `docs/audits/vX.Y.Z-*.md`：測試範圍、結果、coverage、已知風險與 stability gate
- [ ] 更新 `README.md`
- [ ] 更新 `docs/USER_GUIDE.md`：新增／移除指令、參數、合法操作、validation、workflow、debug
- [ ] `python -m compileall -q jpnote_app`
- [ ] `pytest -q`
- [ ] 若 import workflow 有變更，驗證：完整 preflight 先於任何寫入、no 取消不改 DB、`--yes` 不略過 validation/conflict、safe fix 後重新 preflight
- [ ] shell syntax check
- [ ] fresh install/init smoke test
- [ ] 前一版 → 新版 upgrade smoke test，確認 stats／核心查詢
- [ ] 若 fzf 行為有變更，跑 real-fzf integration 或在實機確認
- [ ] 驗證 `jpnote manual` 可讀取 bundled USER_GUIDE
- [ ] 驗證 `jpnote --help` 與 USER_GUIDE 指令清單無明顯漂移
- [ ] 建立 tar.gz 與 SHA-256

- [ ] 建立可還原的本地 Git bundle
