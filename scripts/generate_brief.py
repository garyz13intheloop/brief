#!/usr/bin/env python3
"""
Creekstone Intelligence Brief — 全自动生成脚本
在 GitHub Actions 里运行，每周一/三/五 SGT 09:00 自动触发

环境变量（GitHub Secrets）：
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
  NETLIFY_TOKEN, NETLIFY_SITE_ID
  SERPER_API_KEY  （用于 web search，可选，没有则用 DuckDuckGo 免费接口）
"""

import os, sys, json, time, re, zipfile, uuid
import urllib.request, urllib.parse
import hmac, hashlib, base64
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 配置 ─────────────────────────────────────────────────────────
DASH_DIR       = Path(__file__).parent.parent
STATE_FILE     = DASH_DIR / "scripts" / "state.json"
NETLIFY_SITE   = os.environ.get("NETLIFY_SITE_ID", "f08316b5-d2b4-451e-8a75-b2edad9b2a14")
NETLIFY_URL    = "https://creekstone-brief.netlify.app/"
WINDOW_HOURS   = 52   # 覆盖过去 52 小时（双日报，留一点 overlap）

ALL_KOLS = {
    "karpathy":"33836629","sama":"1605","DarioAmodei":"874126509245476864",
    "hwchase17":"2728439146","swyx":"33521530","simonw":"12497",
    "emollick":"39125788","eladgil":"6535212","saranormous":"339261041",
    "ttunguz":"10069172","steipete":"25401953","satyanadella":"20571756",
    "AndrewYNg":"216939636","fchollet":"68746721","nathanbenaich":"422388777",
    "mattturck":"247785677","OfficialLoganK":"284333988","ylecun":"48008938",
    "GaryMarcus":"232294292","alliekmiller":"39289455","gregisenberg":"14642331",
    "levelsio":"1577241403","vkhosla":"42226885","benthompson":"40273",
    "LinusEkenstam":"3888491","drfeifei":"130745589","DrJimFan":"1007413134",
    "yoheinakajima":"30439303","rowancheung":"1314686042",
}

# ── X API OAuth 1.0a ─────────────────────────────────────────────
def _oauth_header(method, url, params, creds):
    op = {
        'oauth_consumer_key':  creds['API_KEY'],
        'oauth_nonce':         uuid.uuid4().hex,
        'oauth_signature_method': 'HMAC-SHA1',
        'oauth_timestamp':     str(int(time.time())),
        'oauth_token':         creds['ACCESS_TOKEN'],
        'oauth_version':       '1.0',
    }
    ap  = {**params, **op}
    sp  = '&'.join(
        f"{urllib.parse.quote(str(k),'')}"
        f"={urllib.parse.quote(str(v),'')}"
        for k, v in sorted(ap.items())
    )
    base = f"{method}&{urllib.parse.quote(url,'')}&{urllib.parse.quote(sp,'')}"
    key  = (f"{urllib.parse.quote(creds['API_SECRET'],'')}&"
            f"{urllib.parse.quote(creds['ACCESS_TOKEN_SECRET'],'')}")
    sig  = base64.b64encode(
        hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    ).decode()
    op['oauth_signature'] = sig
    return 'OAuth ' + ', '.join(
        f'{k}="{urllib.parse.quote(str(v),"")}"' for k, v in sorted(op.items())
    )

def x_get(url, params, creds, retries=3):
    for i in range(retries):
        try:
            qs  = urllib.parse.urlencode(params)
            req = urllib.request.Request(
                f"{url}?{qs}",
                headers={"Authorization": _oauth_header("GET", url, params, creds)}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(60 * (i + 1))
            else:
                raise
        except Exception:
            time.sleep(5)
    return {"data": []}

# ── Web Search（无需 API key 的免费方案）────────────────────────
def web_search(query, num=5):
    """DuckDuckGo instant answer API，无需 key，简单可靠"""
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        results = []
        # Abstract
        if data.get('AbstractText'):
            results.append({
                "title": data.get('Heading', query),
                "snippet": data['AbstractText'][:300],
                "url": data.get('AbstractURL', '')
            })
        # Related topics
        for topic in data.get('RelatedTopics', [])[:num]:
            if isinstance(topic, dict) and topic.get('Text'):
                results.append({
                    "title": topic.get('Text', '')[:80],
                    "snippet": topic.get('Text', '')[:300],
                    "url": topic.get('FirstURL', '')
                })
        return results[:num]
    except Exception:
        return []

def web_search_serper(query, num=5):
    """Serper API（如果有 key 则用，效果更好）"""
    key = os.environ.get("SERPER_API_KEY", "")
    if not key:
        return web_search(query, num)
    try:
        req = urllib.request.Request(
            "https://google.serper.dev/search",
            data=json.dumps({"q": query, "num": num}).encode(),
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        return [
            {"title": r.get("title",""), "snippet": r.get("snippet",""), "url": r.get("link","")}
            for r in data.get("organic", [])[:num]
        ]
    except Exception:
        return web_search(query, num)

# ── 数据采集 ─────────────────────────────────────────────────────
def load_creds():
    return {
        'API_KEY':              os.environ['X_API_KEY'],
        'API_SECRET':           os.environ['X_API_SECRET'],
        'ACCESS_TOKEN':         os.environ['X_ACCESS_TOKEN'],
        'ACCESS_TOKEN_SECRET':  os.environ['X_ACCESS_TOKEN_SECRET'],
    }

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_issue": 8, "last_run": ""}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

def scan_kols(creds, start_time, end_time):
    """扫描所有 KOL 时间线，按 score 排序"""
    all_tweets = []
    active = 0
    for username, uid in ALL_KOLS.items():
        try:
            params = {
                "max_results": "20",
                "tweet.fields": "created_at,text,public_metrics",
                "exclude": "retweets,replies",
                "start_time": start_time,
                "end_time": end_time,
            }
            data = x_get(f"https://api.twitter.com/2/users/{uid}/tweets", params, creds)
            tweets = data.get('data', [])
            if tweets:
                for t in tweets:
                    pm = t.get('public_metrics', {})
                    t['score'] = pm.get('like_count', 0) + pm.get('retweet_count', 0) * 3
                    t['username'] = username
                    t['url'] = f"https://x.com/{username}/status/{t['id']}"
                tweets.sort(key=lambda x: x['score'], reverse=True)
                all_tweets.extend(tweets[:6])
                active += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  warn: @{username} – {e}")
            time.sleep(0.5)

    all_tweets.sort(key=lambda x: x['score'], reverse=True)
    print(f"  KOL scan: {len(all_tweets)} tweets / {active} active")
    return all_tweets

def gather_web_signals():
    """用 web search 补充产品发布、融资、技术前沿信号"""
    today = datetime.now().strftime('%B %Y')
    queries = [
        f"AI agent product launch release {today}",
        f"AI startup funding raised million {today}",
        f"OpenAI Anthropic Google AI announcement {today}",
        f"AI model release open source {today}",
        f"GitHub trending AI agent week {today}",
    ]
    results = {}
    for q in queries:
        r = web_search_serper(q, 4)
        results[q] = r
        time.sleep(0.5)
    return results

# ── HTML 生成 ─────────────────────────────────────────────────────
CSS_CACHE = None

def get_css():
    global CSS_CACHE
    if CSS_CACHE:
        return CSS_CACHE
    ref = DASH_DIR / "brief_003.html"
    if ref.exists():
        html = ref.read_text()
        start = html.find('<style>')
        end   = html.find('</style>') + 8
        if start > 0:
            CSS_CACHE = html[start:end]
            return CSS_CACHE
    return "<style></style>"

def fmt_tweet(t):
    pm   = t.get('public_metrics', {})
    like = pm.get('like_count', 0)
    user = t.get('username', '?')
    text = t.get('text', '')
    url  = t.get('url', '#')
    date = t.get('created_at', '')[:10]
    initials = user[:2].upper()
    return f"""
        <div class="kcard">
          <div class="kcard-head">
            <div class="kcard-av">{initials}</div>
            <div class="kcard-info">
              <div class="kcard-name">@{user}</div>
              <div class="kcard-handle">KOL · X</div>
            </div>
            <div class="kcard-nums">
              <div class="kcard-likes">♥ {like:,}</div>
              <div class="kcard-date">{date}</div>
            </div>
          </div>
          <div class="kcard-post">{text[:280].replace('<','&lt;').replace('>','&gt;')}</div>
          <a class="kcard-link" href="{url}" target="_blank">→ X 原帖</a>
        </div>"""

def fmt_web_result(r):
    title   = r.get('title', '')[:100].replace('<','&lt;')
    snippet = r.get('snippet', '')[:200].replace('<','&lt;')
    url     = r.get('url', '#')
    return f"""
        <div class="li" data-cat="web">
          <div class="lih">
            <div class="lcard-meta">
              <div class="lcard-name"><a href="{url}" target="_blank">{title}</a></div>
            </div>
          </div>
          <div class="lid">{snippet}</div>
        </div>"""

def build_html(issue_num, date_label, day_label, tweets, web_signals, date_range):
    css = get_css()

    # 侧边栏
    nav_items = ""
    for i in range(issue_num, max(issue_num - 6, 2), -1):
        active_cls = ' active' if i == issue_num else ''
        colors = ['#E05252','#52C47A','#5B8FE8','#9B7FE8','#C9A84C','#666']
        col = colors[issue_num - i] if (issue_num - i) < len(colors) else '#666'
        hot = ' 🔥' if i == issue_num else ''
        nav_items += f'    <a class="sb-item{active_cls}" href="brief_{i:03d}.html"><span class="sb-dot" style="background:{col}"></span>第{i:03d}期{hot}</a>\n'

    # 投资热点：取 top-4 tweets 做 tcard
    trend_cards = ""
    top4 = tweets[:4]
    for i, t in enumerate(top4):
        pm   = t.get('public_metrics', {})
        like = pm.get('like_count', 0)
        user = t.get('username', '?')
        text = t.get('text', '')[:300].replace('<','&lt;').replace('>','&gt;')
        url  = t.get('url', '#')
        cls  = "tcard hot" if i < 2 else "tcard"
        badge_cls = "b-hot" if i == 0 else "b-trend"
        badge_txt = "本期最强" if i == 0 else "高热"
        trend_cards += f"""
        <div class="{cls}">
          <div class="stars">♥{like:,}</div>
          <span class="tcard-badge {badge_cls}">@{user}</span>
          <div class="tcard-title">{text[:120]}</div>
          <div class="tcard-body">{text[120:280] or '—'}</div>
          <div class="tcard-impl"><a href="{url}" target="_blank" style="color:var(--blue)">→ X 原帖</a></div>
        </div>"""

    # KOL 卡片：tweets 5-20
    kol_cards = "".join(fmt_tweet(t) for t in tweets[4:20])

    # 产品发布：web signal 里抓到的
    launch_items = ""
    for q, results in web_signals.items():
        if "launch" in q or "announcement" in q or "release" in q:
            for r in results:
                launch_items += fmt_web_result(r)

    # 融资信号
    fund_items = ""
    for q, results in web_signals.items():
        if "funding" in q or "raised" in q:
            for r in results:
                fund_items += fmt_web_result(r)

    # 技术前沿
    tech_items = ""
    for q, results in web_signals.items():
        if "GitHub" in q or "model" in q.lower():
            for r in results:
                tech_items += fmt_web_result(r)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Creekstone Intelligence · 第{issue_num:03d}期 · {date_label}</title>
{css}
</head>
<body>
<div class="layout">
<nav class="sidebar">
  <div class="sb-logo">
    <a href="index.html" style="text-decoration:none">
      <div class="sb-brand">CREEKSTONE</div>
      <div class="sb-sub">Intelligence · 自动生成</div>
    </a>
  </div>
  <div style="padding:6px 0">
    <a class="sb-item" href="index.html"><span class="sb-dot" style="background:var(--gold)"></span>← 返回主看板</a>
    <hr style="border:none;border-top:1px solid var(--bd);margin:4px 0">
    <div class="sb-sec">本月期刊</div>
{nav_items}  </div>
</nav>
<div class="main">
<div class="topbar">
  <div>
    <div class="topbar-title">Creekstone Intelligence Brief</div>
    <div class="topbar-sub">第 {issue_num:03d} 期 · {date_range} · {day_label} · 自动生成 · {len(tweets)} 条 KOL 信号</div>
  </div>
  <div class="search">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg>
    <input id="si" type="text" placeholder="搜索…" oninput="doSearch(this.value)">
  </div>
</div>
<div class="content" id="mc">

<!-- 自动生成提示 -->
<div style="background:var(--s2);border:1px solid var(--bd2);border-radius:8px;padding:10px 14px;margin-bottom:18px;font-size:12px;color:var(--t3);display:flex;align-items:center;gap:8px">
  <span style="color:var(--green)">●</span>
  本期由 GitHub Actions 自动扫描生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')} SGT ·
  <a href="https://github.com/garyz13intheloop/brief/actions" target="_blank" style="color:var(--blue)">查看运行日志</a>
</div>

<div class="stats">
  <div class="stat"><div class="stat-n">{len(tweets)}</div><div class="stat-l">KOL 信号</div></div>
  <div class="stat"><div class="stat-n">{len([t for t in tweets if t.get('public_metrics',{}).get('like_count',0)>500])}</div><div class="stat-l">高热帖子</div></div>
  <div class="stat"><div class="stat-n">{sum(len(v) for v in web_signals.values())}</div><div class="stat-l">Web 信号</div></div>
  <div class="stat"><div class="stat-n">{issue_num:03d}</div><div class="stat-l">当前期号</div></div>
</div>

<!-- ① 投资热点 -->
<div class="section" id="trends">
<div class="sec-head">
  <div class="sec-title">🔥 本期高热信号</div>
  <div class="sec-desc">X OAuth1 扫描 {len(ALL_KOLS)} 个 KOL 账号，按互动量排序 Top 4</div>
</div>
<hr class="sec-rule">
<div class="trend-grid">
{trend_cards}
</div>
</div>

<!-- ② 产品发布 -->
<div class="section" id="launches">
<div class="sec-head">
  <div class="sec-title">🚀 产品发布 · Web 信号</div>
  <div class="sec-desc">来源：Web Search 自动抓取，需人工确认重要性</div>
</div>
<hr class="sec-rule">
<div class="launch-list" id="launchList">
{launch_items or '<div style="padding:12px;color:var(--t3);font-size:12px">本期 Web 抓取未发现明确产品发布信号，请手动补充</div>'}
</div>
</div>

<!-- ③ KOL 观点 -->
<div class="section" id="kols">
<div class="sec-head">
  <div class="sec-title">💬 KOL 核心观点</div>
  <div class="sec-desc">按互动量降序，{len(ALL_KOLS)} 个账号全扫</div>
</div>
<hr class="sec-rule">
<div class="kol-grid">
{kol_cards}
</div>
</div>

<!-- ④ 融资 -->
<div class="section" id="funding">
<div class="sec-head">
  <div class="sec-title">💰 融资动态</div>
  <div class="sec-desc">Web Search 自动抓取</div>
</div>
<hr class="sec-rule">
<div class="fund-list">
{fund_items or '<div style="padding:12px;color:var(--t3);font-size:12px">本期未检测到明确融资信号</div>'}
</div>
</div>

<!-- ⑤ 技术前沿 -->
<div class="section" id="tech">
<div class="sec-head">
  <div class="sec-title">🔬 技术前沿</div>
</div>
<hr class="sec-rule">
<div class="tech-list">
{tech_items or '<div style="padding:12px;color:var(--t3);font-size:12px">本期未检测到明确技术信号</div>'}
</div>
</div>

<div class="footer">
  Creekstone Intelligence Brief · 第 {issue_num:03d} 期 · {date_range}<br>
  ⚡ 由 GitHub Actions 自动生成 · 数据源：X OAuth1（{len(ALL_KOLS)} KOL）· Web Search<br>
  🌐 {NETLIFY_URL}
</div>
</div>
</div>
</div>
<script>
function doSearch(q){{document.querySelectorAll('.lcard,.kcard,.fcard,.tcard,.tcard2,.rcard').forEach(c=>{{c.style.display=(!q.trim()||c.textContent.toLowerCase().includes(q.toLowerCase()))?'':'none';}});}}
function toggleDetail(btn){{const d=btn.nextElementSibling;d.classList.toggle('open');btn.textContent=d.classList.contains('open')?'收起 ↑':'展开详细版 ↓';}}
</script>
</body>
</html>"""

# ── index.html 更新 ───────────────────────────────────────────────
def update_index(issue_num, date_range, day_label, top_tweets):
    idx_path = DASH_DIR / "index.html"
    if not idx_path.exists():
        return

    html = idx_path.read_text()

    # 更新侧边栏第一项
    top5 = [t for t in top_tweets[:5]]
    signal_lines = "\n".join(
        f'          <div class="ic-sig"><span class="ic-bull">▸</span>'
        f'@{t["username"]} ♥{t.get("public_metrics",{}).get("like_count",0):,}：'
        f'{t["text"][:80].replace("<","&lt;")}…</div>'
        for t in top5
    )

    new_card = f"""      <a href="brief_{issue_num:03d}.html" class="issue-card latest">
        <span class="ic-tag">最新 · 第 {issue_num:03d} 期 · {day_label} · 自动生成</span>
        <div class="ic-period">自动扫描：{date_range}</div>
        <div class="ic-date">{date_range}</div>
        <div class="ic-signals">
{signal_lines}
        </div>
        <div class="ic-footer">
          <span class="ic-sources">X×{len(ALL_KOLS)} · Web Search · GitHub Actions</span>
          <span class="ic-read">阅读全文 →</span>
        </div>
      </a>"""

    # 插入到 issue-grid 最前（找到第一个 issue-card）
    marker = '      <a href="brief_'
    pos = html.find(marker)
    if pos > 0:
        # 把旧的 latest 改为普通
        html = html.replace('class="issue-card latest"', 'class="issue-card"', 1)
        html = html[:pos] + new_card + "\n\n" + html[pos:]

    idx_path.write_text(html)
    print("  index.html updated")

# ── Netlify 发布 ──────────────────────────────────────────────────
def publish_netlify(token, site_id):
    zip_path = "/tmp/brief_auto.zip"
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for html in DASH_DIR.glob("*.html"):
            zf.write(html, html.name)
    with open(zip_path, 'rb') as f:
        data = f.read()
    req = urllib.request.Request(
        f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/zip"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        result = json.loads(r.read())
    os.remove(zip_path)
    state = result.get('state', '?')
    print(f"  Netlify: {state} → {NETLIFY_URL}")
    return state

# ── 主函数 ────────────────────────────────────────────────────────
def main():
    print(f"=== Creekstone Brief Auto-Generator ===")
    print(f"Time: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M SGT')}")

    # 读凭证
    creds = load_creds()
    netlify_token = os.environ.get('NETLIFY_TOKEN', '')

    # 读状态
    state      = load_state()
    issue_num  = state['last_issue'] + 1
    now_utc    = datetime.now(timezone.utc)
    start_utc  = now_utc - timedelta(hours=WINDOW_HOURS)
    start_time = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_time   = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    sgt        = timezone(timedelta(hours=8))
    now_sgt    = datetime.now(sgt)
    start_sgt  = now_sgt - timedelta(hours=WINDOW_HOURS)
    date_range = f"{start_sgt.strftime('%m-%d')}~{now_sgt.strftime('%m-%d')}"
    day_map    = {0:'周一',1:'周二',2:'周三',3:'周四',4:'周五',5:'周六',6:'周日'}
    day_label  = day_map[now_sgt.weekday()]

    print(f"Issue: {issue_num:03d} · Window: {date_range} ({WINDOW_HOURS}h)")

    # ① X 扫描
    print("\n[1/4] Scanning X KOLs...")
    tweets = scan_kols(creds, start_time, end_time)

    # ② Web 信号
    print("\n[2/4] Gathering web signals...")
    web_signals = gather_web_signals()

    # ③ 生成 HTML
    print("\n[3/4] Generating HTML...")
    html = build_html(issue_num, date_range, day_label, tweets, web_signals, date_range)
    out_path = DASH_DIR / f"brief_{issue_num:03d}.html"
    out_path.write_text(html)
    print(f"  Written: {out_path.name} ({len(html)//1024}KB)")

    # 更新 index
    update_index(issue_num, date_range, day_label, tweets)

    # ④ 发布
    print("\n[4/4] Publishing...")
    if netlify_token:
        publish_netlify(netlify_token, NETLIFY_SITE)
    else:
        print("  skip Netlify (no token)")

    # 更新状态
    state['last_issue'] = issue_num
    state['last_run']   = now_utc.isoformat()
    save_state(state)

    print(f"\n✅ Done: brief_{issue_num:03d}.html → {NETLIFY_URL}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
