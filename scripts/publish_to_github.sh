#!/usr/bin/env bash
set -euo pipefail

repo_name="${1:-jpnote}"
visibility="${2:-private}"

if [[ "$visibility" != "private" && "$visibility" != "public" ]]; then
  printf '用法：%s [repo-name或owner/repo] [private|public]\n' "$0" >&2
  exit 2
fi

if ! command -v gh >/dev/null 2>&1; then
  cat >&2 <<'MSG'
找不到 GitHub CLI（gh）。
Arch Linux 可安裝：
  sudo pacman -S github-cli
安裝後先執行：
  gh auth login
MSG
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo '尚未登入 GitHub，現在啟動登入流程。' >&2
  gh auth login
fi

if origin_url="$(git remote get-url origin 2>/dev/null)"; then
  case "$origin_url" in
    https://github.com/*|git@github.com:*)
      echo "已存在 GitHub origin：$origin_url"
      git push -u origin main
      git push origin --tags
      exit 0
      ;;
    /*|file://*|*.bundle)
      echo "移除本地 bundle origin：$origin_url"
      git remote remove origin
      ;;
    *)
      echo "origin 已存在且不是可辨識的 GitHub/bundle remote：$origin_url" >&2
      echo '請先人工確認後再執行。' >&2
      exit 1
      ;;
  esac
fi

gh repo create "$repo_name" "--$visibility" --source=. --remote=origin --push
git push origin --tags

echo 'GitHub repository 與 tags 已完成推送。'
