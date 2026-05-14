#!/bin/bash
# ============================================================
# Creekstone Intelligence Brief — 自动发布脚本
# 用法：bash publish.sh "第004期 · 2026-05-15"
# Token 从 ~/.config/x-cli/.env 同目录的 .github_token 读取
# 或者 export GH_TOKEN=xxx 后运行
# ============================================================
set -e

DASH_DIR="$(cd "$(dirname "$0")" && pwd)"
PAGES_URL="https://garyz13intheloop.github.io/creekstone-intelligence/"

# 读取 token（从环境变量或 .github_token 文件）
if [ -z "$GH_TOKEN" ]; then
  TOKEN_FILE="$HOME/.config/gh_token"
  if [ -f "$TOKEN_FILE" ]; then
    GH_TOKEN=$(cat "$TOKEN_FILE")
  else
    echo "❌ GH_TOKEN not set. Run: export GH_TOKEN=your_token"
    exit 1
  fi
fi

MSG="${1:-$(date '+📰 Brief update %Y-%m-%d %H:%M')}"

echo "📂 Dir: $DASH_DIR"
echo "📝 Commit: $MSG"

cd "$DASH_DIR"
git config user.name "Gary Zhang"
git config user.email "gary13intheloop@gmail.com"
git remote set-url origin "https://${GH_TOKEN}@github.com/garyz13intheloop/creekstone-intelligence.git"

git add -A
CHANGED=$(git diff --cached --name-only | wc -l | tr -d ' ')

if [ "$CHANGED" = "0" ]; then
  echo "⚠️  Nothing changed, skip"
  exit 0
fi

echo "📄 Changed: $(git diff --cached --name-only | tr '\n' ' ')"
git commit -m "$MSG"
git push origin main

echo ""
echo "✅ Live: $PAGES_URL"
echo "⏱  Pages updates in ~60s"
