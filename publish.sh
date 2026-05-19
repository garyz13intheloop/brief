#!/bin/bash
# ============================================================
# Creekstone Intelligence Brief — 自动发布脚本 v2
# 同时发布到：
#   GitHub Pages: https://garyz13intheloop.github.io/brief/
#   Netlify:      https://creekstone-brief.netlify.app/
#
# 用法：bash publish.sh "第007期 · 2026-05-21"
# ============================================================
set -e

DASH_DIR="$(cd "$(dirname "$0")" && pwd)"
PAGES_URL="https://creekstone-brief.netlify.app/"
NETLIFY_SITE_ID="f08316b5-d2b4-451e-8a75-b2edad9b2a14"

# 读取 tokens
GH_TOKEN=$(cat ~/.config/gh_token 2>/dev/null || echo "")
NETLIFY_TOKEN=$(cat ~/.config/netlify_token 2>/dev/null || echo "")

MSG="${1:-$(date '+📰 Brief update %Y-%m-%d %H:%M')}"

echo "📂 Dir: $DASH_DIR"
echo "📝 Commit: $MSG"
echo ""

cd "$DASH_DIR"

# ── 1. GitHub Pages ─────────────────────────────────────────
if [ -n "$GH_TOKEN" ]; then
  echo "📡 Pushing to GitHub Pages..."
  git config user.name "Gary Zhang"
  git config user.email "gary13intheloop@gmail.com"
  git remote set-url origin "https://${GH_TOKEN}@github.com/garyz13intheloop/brief.git"

  git add -A
  CHANGED=$(git diff --cached --name-only | wc -l | tr -d ' ')
  if [ "$CHANGED" = "0" ]; then
    echo "  ⚠️  No changes, skipping GitHub push"
  else
    echo "  📄 Changed: $(git diff --cached --name-only | tr '\n' ' ')"
    git commit -m "$MSG"
    git push origin main
    echo "  ✅ GitHub Pages updated"
  fi
else
  echo "  ⚠️  No GH_TOKEN, skipping GitHub push"
fi

# ── 2. Netlify ───────────────────────────────────────────────
if [ -n "$NETLIFY_TOKEN" ]; then
  echo ""
  echo "🚀 Deploying to Netlify..."

  # 打包
  TMPZIP=$(mktemp /tmp/creekstone_XXXXXX.zip)
  cd "$DASH_DIR"
  zip -j "$TMPZIP" *.html > /dev/null 2>&1

  # 上传
  RESULT=$(curl -s -X POST \
    "https://api.netlify.com/api/v1/sites/${NETLIFY_SITE_ID}/deploys" \
    -H "Authorization: Bearer $NETLIFY_TOKEN" \
    -H "Content-Type: application/zip" \
    --data-binary @"$TMPZIP")

  rm -f "$TMPZIP"

  DEPLOY_URL=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('deploy_ssl_url','?'))" 2>/dev/null)
  STATE=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state','?'))" 2>/dev/null)

  echo "  State: $STATE"
  echo "  ✅ Netlify updated"
else
  echo "  ⚠️  No NETLIFY_TOKEN, skipping Netlify deploy"
fi

echo ""
echo "✅ Published!"
echo "   🌐 $PAGES_URL"
echo "   ⏱  Netlify updates in ~30s, GitHub Pages in ~60s"
