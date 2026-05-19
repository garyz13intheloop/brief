#!/bin/bash
# ============================================================
# Creekstone Intelligence Brief — 自动发布脚本 v2
# 同时发布到：
#   Netlify (主):     https://creekstone-brief.netlify.app/
#   GitHub Pages:     https://garyz13intheloop.github.io/brief/
#
# 用法：bash publish.sh "第007期 · 2026-05-21"
# ============================================================
set -e

DASH_DIR="$(cd "$(dirname "$0")" && pwd)"
NETLIFY_SITE_ID="f08316b5-d2b4-451e-8a75-b2edad9b2a14"

GH_TOKEN=$(cat ~/.config/gh_token 2>/dev/null || echo "")
NETLIFY_TOKEN=$(cat ~/.config/netlify_token 2>/dev/null || echo "")
MSG="${1:-$(date '+📰 Brief update %Y-%m-%d %H:%M')}"

echo "📝 $MSG"
echo ""

cd "$DASH_DIR"

# ── 1. Netlify（主） ─────────────────────────────────────────
if [ -n "$NETLIFY_TOKEN" ]; then
  echo "🚀 Deploying to Netlify..."
  TMPZIP=$(mktemp /tmp/creekstone_XXXXXX.zip)
  zip -j "$TMPZIP" "$DASH_DIR"/*.html > /dev/null
  RESULT=$(curl -s -X POST \
    "https://api.netlify.com/api/v1/sites/${NETLIFY_SITE_ID}/deploys" \
    -H "Authorization: Bearer $NETLIFY_TOKEN" \
    -H "Content-Type: application/zip" \
    --data-binary @"$TMPZIP")
  rm -f "$TMPZIP"
  STATE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state','?'))" 2>/dev/null)
  echo "  ✅ Netlify: $STATE → https://creekstone-brief.netlify.app/"
fi

# ── 2. GitHub Pages（备份） ──────────────────────────────────
if [ -n "$GH_TOKEN" ]; then
  echo "📡 Pushing to GitHub..."
  git config user.name "Gary Zhang"
  git config user.email "gary13intheloop@gmail.com"
  git remote set-url origin "https://${GH_TOKEN}@github.com/garyz13intheloop/brief.git"
  git add -A
  CHANGED=$(git diff --cached --name-only | wc -l | tr -d ' ')
  if [ "$CHANGED" != "0" ]; then
    git commit -m "$MSG"
    git push origin main
    echo "  ✅ GitHub Pages updated"
  else
    echo "  ⚠️  No changes"
  fi
fi

echo ""
echo "✅ Live: https://creekstone-brief.netlify.app/"
