#!/usr/bin/env python3
"""
Creekstone Intelligence Brief — 全自动生成脚本 v4.0
改进：Serper/Jina 双路 web search、HN API、Substack API、
      GitHub REST 上传（跳过 git push 超时）、index 精确插入
"""

import os, sys, json, time, re, zipfile, uuid, base64, hmac, hashlib
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────
DASH_DIR   = Path(__file__).parent.parent
STATE_FILE = DASH_DIR / "scripts" / "state.json"
REPO       = "garyz13intheloop/brief"
NETLIFY_SITE = os.environ.get("NETLIFY_SITE_ID", "f08316b5-d2b4-451e-8a75-b2edad9b2a14").strip()
NETLIFY_URL  = "https://creekstone-brief.netlify.app/"
GH_PAGES_URL = "https://garyz13intheloop.github.io/brief/"
WINDOW_HOURS = 52

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

PODCASTS = {
    "Latent Space":  "https://latent.space/api/v1/posts?limit=4",
    "Import AI":     "https://importai.substack.com/api/v1/posts?limit=4",
    "Dwarkesh":      "https://www.dwarkeshpatel.com/api/v1/posts?limit=4",
}

# ── 工具函数 ──────────────────────────────────────────────────────────────────
def http_get(url, headers=None, timeout=15):
    h = {"User-Agent": "Mozilla/5.0 Creekstone/4.0"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def http_post(url, data, headers=None, timeout=15):
    h = {"User-Agent": "Mozilla/5.0 Creekstone/4.0", "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

# ── X OAuth 1.0a ──────────────────────────────────────────────────────────────
def _oauth_header(method, url, params, creds):
    op = {
        'oauth_consumer_key':      creds['API_KEY'],
        'oauth_nonce':             uuid.uuid4().hex,
        'oauth_signature_method':  'HMAC-SHA1',
        'oauth_timestamp':         str(int(time.time())),
        'oauth_token':             creds['ACCESS_TOKEN'],
        'oauth_version':           '1.0',
    }
    ap = {**params, **op}
    sp = '&'.join(
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
                headers={"Authorization": _oauth_header("GET", url, params, creds),
                         "User-Agent": "Creekstone/4.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(60 * (i + 1))
            else:
                raise
        except Exception as e:
            print(f"    x_get retry {i+1}: {e}")
            time.sleep(5)
    return {"data": []}

# ── Web Search ─────────────────────────────────────────────────────────────────
def web_search_serper(query, num=6):
    """Serper Google Search API（首选，需 SERPER_API_KEY secret）"""
    key = os.environ.get("SERPER_API_KEY", "").strip()
    if not key:
        return []
    try:
        payload = json.dumps({"q": query, "num": num, "gl": "us"}).encode()
        resp = http_post(
            "https://google.serper.dev/search",
            payload,
            headers={"X-API-KEY": key},
            timeout=12
        )
        data = json.loads(resp)
        return [
            {
                "title":   r.get("title", ""),
                "snippet": r.get("snippet", ""),
                "url":     r.get("link", ""),
                "date":    r.get("date", ""),
            }
            for r in data.get("organic", [])[:num]
        ]
    except Exception as e:
        print(f"    serper error: {e}")
        return []

def web_search_hn(query, num=5):
    """HN Algolia Search API（免费，无需 key）"""
    try:
        encoded = urllib.parse.quote(query)
        cutoff_ts = int((datetime.now() - timedelta(days=7)).timestamp())
        url = (f"https://hn.algolia.com/api/v1/search?query={encoded}"
               f"&tags=story&numericFilters=created_at_i%3E{cutoff_ts}&hitsPerPage={num}")
        data = json.loads(http_get(url, timeout=10))
        return [
            {
                "title":   h.get("title", ""),
                "snippet": h.get("story_text", "")[:200] if h.get("story_text") else "",
                "url":     h.get("url", f"https://news.ycombinator.com/item?id={h.get('objectID','')}"),
                "points":  h.get("points", 0),
                "source":  "Hacker News",
            }
            for h in data.get("hits", [])[:num]
            if h.get("title")
        ]
    except Exception as e:
        print(f"    HN search error: {e}")
        return []

def gather_web_signals(window_days=3):
    """多路并行采集：Serper + HN"""
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(sgt)
    month_str = now.strftime("%B %Y")
    week_str  = now.strftime("%Y-%m-%d")

    serper_queries = [
        f"AI agent product launch release {month_str}",
        f"AI startup funding raised million billion {month_str}",
        f"OpenAI Anthropic Google AI announcement {week_str}",
        f"LLM model benchmark release open source {month_str}",
        f"AI coding agent tool developer {month_str}",
        f"artificial intelligence venture capital {month_str}",
    ]
    hn_queries = [
        "AI agent",
        "LLM benchmark",
        "AI startup funding",
    ]

    signals = {"launches": [], "funding": [], "tech": [], "hn": [], "raw": {}}

    # Serper
    for q in serper_queries:
        results = web_search_serper(q, 5)
        signals["raw"][q] = results
        if results:
            if "launch" in q or "announcement" in q:
                signals["launches"].extend(results)
            elif "funding" in q or "raised" in q or "venture" in q:
                signals["funding"].extend(results)
            else:
                signals["tech"].extend(results)
        time.sleep(0.3)

    # HN
    for q in hn_queries:
        results = web_search_hn(q, 4)
        signals["hn"].extend(results)
        time.sleep(0.2)

    # 去重（按 url）
    for key in ["launches", "funding", "tech", "hn"]:
        seen = set()
        deduped = []
        for r in signals[key]:
            u = r.get("url", "")
            if u and u not in seen:
                seen.add(u)
                deduped.append(r)
        signals[key] = deduped

    total = sum(len(v) for k, v in signals.items() if k != "raw")
    print(f"    web signals: launches={len(signals['launches'])} "
          f"funding={len(signals['funding'])} tech={len(signals['tech'])} "
          f"hn={len(signals['hn'])} total={total}")
    return signals

# ── Substack / Podcast ────────────────────────────────────────────────────────
def fetch_podcasts(window_hours=72):
    """拉取最近 window_hours 内的 Substack 文章"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    episodes = []
    for name, api_url in PODCASTS.items():
        try:
            data = json.loads(http_get(api_url, timeout=10))
            posts = data if isinstance(data, list) else data.get("posts", [])
            for p in posts[:4]:
                pub_str = p.get("post_date") or p.get("publishedAt") or ""
                try:
                    pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                    if pub < cutoff:
                        continue
                except Exception:
                    pass
                episodes.append({
                    "source":   name,
                    "title":    p.get("title", ""),
                    "subtitle": p.get("subtitle", "")[:200],
                    "url":      p.get("canonical_url") or p.get("url", ""),
                    "date":     pub_str[:10],
                })
        except Exception as e:
            print(f"    podcast {name}: {e}")
    print(f"    podcasts: {len(episodes)} episodes")
    return episodes

# ── X KOL 扫描 ────────────────────────────────────────────────────────────────
def load_creds():
    """从环境变量读 X API 凭证，统一用不带 X_ 前缀的 key 供 OAuth 签名使用"""
    mapping = {
        'API_KEY':              'X_API_KEY',
        'API_SECRET':           'X_API_SECRET',
        'ACCESS_TOKEN':         'X_ACCESS_TOKEN',
        'ACCESS_TOKEN_SECRET':  'X_ACCESS_TOKEN_SECRET',
    }
    return {short: os.environ[env_key].strip() for short, env_key in mapping.items()}

def scan_kols(creds, start_time, end_time):
    all_tweets = []
    active = 0
    for username, uid in ALL_KOLS.items():
        try:
            params = {
                "max_results": "20",
                "tweet.fields": "created_at,text,public_metrics",
                "exclude": "retweets,replies",
                "start_time": start_time,
                "end_time":   end_time,
            }
            data   = x_get(f"https://api.twitter.com/2/users/{uid}/tweets", params, creds)
            tweets = data.get('data', [])
            if tweets:
                for t in tweets:
                    pm = t.get('public_metrics', {})
                    t['score']    = pm.get('like_count', 0) + pm.get('retweet_count', 0) * 3
                    t['username'] = username
                    t['url']      = f"https://x.com/{username}/status/{t['id']}"
                tweets.sort(key=lambda x: x['score'], reverse=True)
                all_tweets.extend(tweets[:6])
                active += 1
            time.sleep(0.25)
        except Exception as e:
            print(f"    warn @{username}: {e}")
            time.sleep(0.5)
    all_tweets.sort(key=lambda x: x['score'], reverse=True)
    print(f"    KOL scan: {len(all_tweets)} tweets / {active} active KOLs")
    return all_tweets

# ── CSS 提取 ──────────────────────────────────────────────────────────────────
_CSS_CACHE = None

def get_css():
    global _CSS_CACHE
    if _CSS_CACHE:
        return _CSS_CACHE
    # 优先从 brief_003（最大、最完整）提取
    for ref_name in ["brief_003.html", "brief_012.html", "brief_011.html"]:
        ref = DASH_DIR / ref_name
        if ref.exists():
            html = ref.read_text()
            m = re.search(r'(<style[\s>].*?</style>)', html, re.DOTALL)
            if m:
                _CSS_CACHE = m.group(1)
                return _CSS_CACHE
    return "<style>body{background:#0a0a0a;color:#ebebeb;font-family:sans-serif}</style>"

# ── HTML 生成 ─────────────────────────────────────────────────────────────────
def esc(s):
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def build_sidebar(issue_num):
    items = ""
    colors = ['#E05252','#52C47A','#5B8FE8','#9B7FE8','#C9A84C','#888']
    for i in range(issue_num, max(issue_num - 8, -1), -1):
        if i < 0:
            break
        c   = colors[min(issue_num - i, len(colors)-1)]
        hot = ' 🔥' if i == issue_num else ''
        ac  = ' active' if i == issue_num else ''
        items += f'    <a class="sb-item{ac}" href="brief_{i:03d}.html"><span class="sb-dot" style="background:{c}"></span>第{i:03d}期{hot}</a>\n'
    return items

def build_trend_cards(tweets):
    cards = ""
    for i, t in enumerate(tweets[:4]):
        pm   = t.get('public_metrics', {})
        like = pm.get('like_count', 0)
        user = t.get('username', '?')
        text = esc(t.get('text', ''))
        url  = t.get('url', '#')
        cls  = "tcard hot" if i < 2 else "tcard"
        bcls = "b-hot" if i == 0 else "b-trend"
        badge = "本期最强信号" if i == 0 else "高热讨论"
        title = text[:120]
        body  = text[120:320] or "—"
        cards += f"""
  <div class="{cls}">
    <div class="stars">♥{like:,}</div>
    <span class="tcard-badge {bcls}">@{user} · {badge}</span>
    <div class="tcard-title">{title}</div>
    <div class="tcard-body">{body}</div>
    <div class="tcard-impl"><a href="{url}" target="_blank" style="color:var(--blue)">→ X 原帖</a></div>
  </div>"""
    return cards

def build_kol_cards(tweets):
    cards = ""
    for t in tweets[4:18]:
        pm   = t.get('public_metrics', {})
        like = pm.get('like_count', 0)
        user = t.get('username', '?')
        text = esc(t.get('text', ''))
        url  = t.get('url', '#')
        date = t.get('created_at', '')[:10]
        init = user[:2].upper()
        cards += f"""
  <div class="kcard">
    <div class="kcard-head">
      <div class="kcard-av">{init}</div>
      <div class="kcard-info">
        <div class="kcard-name">@{user}</div>
        <div class="kcard-handle">KOL · X · {date}</div>
      </div>
      <div class="kcard-nums">
        <div class="kcard-likes">♥ {like:,}</div>
        <div class="kcard-date">{date}</div>
      </div>
    </div>
    <div class="kcard-post">{text[:320]}</div>
    <a class="kcard-link" href="{url}" target="_blank">→ X 原帖</a>
  </div>"""
    return cards

def build_signal_cards(items, empty_msg):
    if not items:
        return f'<div style="padding:12px;color:var(--t3);font-size:12px">{empty_msg}</div>'
    cards = ""
    for r in items[:6]:
        title   = esc(r.get('title', ''))[:120]
        snippet = esc(r.get('snippet', ''))[:240]
        url     = r.get('url', '#')
        src     = esc(r.get('source', 'Web'))
        date    = r.get('date', '')[:10]
        cards += f"""
  <div class="lcard" data-cat="web">
    <div class="lcard-head">
      <div class="lcard-icon">🔗</div>
      <div class="lcard-meta">
        <div class="lcard-name"><a href="{url}" target="_blank">{title}</a></div>
        <div class="lcard-who">{src}{' · ' + date if date else ''}</div>
      </div>
    </div>
    <div class="lcard-body">
      <div class="lcard-short">{snippet}</div>
      <a class="lcard-link" href="{url}" target="_blank">→ 阅读原文</a>
    </div>
  </div>"""
    return cards

def build_podcast_cards(episodes):
    if not episodes:
        return '<div style="padding:12px;color:var(--t3);font-size:12px">本期时间窗内暂无新播客发布</div>'
    cards = ""
    for ep in episodes:
        title    = esc(ep.get('title', ''))
        subtitle = esc(ep.get('subtitle', ''))[:200]
        url      = ep.get('url', '#')
        src      = esc(ep.get('source', ''))
        date     = ep.get('date', '')[:10]
        cards += f"""
  <div class="rcard">
    <div class="rcard-head">
      <div class="rcard-left">
        <div class="rcard-src">🎙 播客 · {src}</div>
        <div class="rcard-title"><a href="{url}" target="_blank">{title}</a></div>
      </div>
      <div class="rdate">{date}</div>
    </div>
    <div class="rb">
      <div class="rsh">{subtitle}</div>
      <a class="rcard-link" href="{url}" target="_blank">→ 播客原文</a>
    </div>
  </div>"""
    return cards

def build_html(issue_num, date_range, day_label, tweets, signals, episodes):
    css     = get_css()
    sidebar = build_sidebar(issue_num)
    n_hot   = len([t for t in tweets if t.get('public_metrics',{}).get('like_count',0) > 500])
    n_web   = sum(len(signals[k]) for k in ['launches','funding','tech','hn'])
    now_str = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')

    trend_cards   = build_trend_cards(tweets)
    kol_cards     = build_kol_cards(tweets)
    launch_cards  = build_signal_cards(signals['launches'], '本期 Web 抓取未发现明确产品发布，请手动补充')
    funding_cards = build_signal_cards(signals['funding'],  '本期未检测到明确融资信号')
    tech_cards    = build_signal_cards(signals['tech'] + signals['hn'], '本期未检测到明确技术信号')
    podcast_cards = build_podcast_cards(episodes)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Creekstone Intelligence · 第{issue_num:03d}期 · {date_range}</title>
{css}
</head>
<body>
<div class="layout">
<nav class="sidebar">
  <div class="sb-logo">
    <a href="index.html" style="text-decoration:none">
      <div class="sb-brand">CREEKSTONE</div>
      <div class="sb-sub">Intelligence · 自动 + 手工</div>
    </a>
  </div>
  <div style="padding:6px 0">
    <a class="sb-item" href="index.html">
      <span class="sb-dot" style="background:var(--gold)"></span>← 返回主看板
    </a>
    <hr style="border:none;border-top:1px solid var(--bd);margin:4px 0">
    <div class="sb-sec">近期期刊</div>
{sidebar}  </div>
</nav>
<div class="main">
<div class="topbar">
  <div>
    <div class="topbar-title">Creekstone Intelligence Brief</div>
    <div class="topbar-sub">第 {issue_num:03d} 期 · {date_range} · {day_label} · {len(tweets)} KOL 信号 · {n_web} Web 信号 · 自动生成框架</div>
  </div>
  <div class="search">
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#555" stroke-width="2.5">
      <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
    </svg>
    <input id="si" type="text" placeholder="搜索…" oninput="doSearch(this.value)">
  </div>
</div>
<div class="content" id="mc">

<div style="background:rgba(92,163,120,.08);border:1px solid rgba(92,163,120,.25);border-radius:8px;padding:10px 14px;margin-bottom:18px;font-size:12px;color:var(--t2);display:flex;align-items:center;gap:10px">
  <span style="color:#52C47A;font-size:16px">⚡</span>
  <span>自动生成框架 · {now_str} SGT · 数据来源：X OAuth1 ({len(ALL_KOLS)} KOL) + Serper + HN API + Substack API ·
  <strong style="color:var(--gold)">如需深度加固请联系 Gary</strong></span>
</div>

<div class="stats">
  <div class="stat"><div class="stat-n">{len(tweets)}</div><div class="stat-l">KOL 信号</div></div>
  <div class="stat"><div class="stat-n">{n_hot}</div><div class="stat-l">高热帖(♥500+)</div></div>
  <div class="stat"><div class="stat-n">{len(signals['launches'])}</div><div class="stat-l">发布信号</div></div>
  <div class="stat"><div class="stat-n">{len(signals['funding'])}</div><div class="stat-l">融资信号</div></div>
  <div class="stat"><div class="stat-n">{len(episodes)}</div><div class="stat-l">播客更新</div></div>
  <div class="stat"><div class="stat-n">{len(signals['hn'])}</div><div class="stat-l">HN 热帖</div></div>
</div>

<div class="section" id="trends">
  <div class="sec-head">
    <div class="sec-title">🔥 本期高热 KOL 信号</div>
    <div class="sec-desc">X OAuth1 扫描 {len(ALL_KOLS)} 个账号，按互动量降序，Top 4</div>
  </div>
  <hr class="sec-rule">
  <div class="trend-grid">{trend_cards}</div>
</div>

<div class="section" id="launches">
  <div class="sec-head">
    <div class="sec-title">🚀 产品发布 · Web 信号</div>
    <div class="sec-desc">Serper Search 自动抓取 · 需人工确认重要性 · 如信号为空说明搜索限额用完</div>
  </div>
  <hr class="sec-rule">
  <div class="launch-list" id="launchList">{launch_cards}</div>
</div>

<div class="section" id="kols">
  <div class="sec-head">
    <div class="sec-title">💬 KOL 推文全列表</div>
    <div class="sec-desc">{len(ALL_KOLS)} 个账号全量扫描 · 按互动量降序</div>
  </div>
  <hr class="sec-rule">
  <div class="kol-grid">{kol_cards}</div>
</div>

<div class="section" id="funding">
  <div class="sec-head">
    <div class="sec-title">💰 融资动态 · Web 信号</div>
    <div class="sec-desc">Serper Search 自动抓取</div>
  </div>
  <hr class="sec-rule">
  <div class="fund-list">{funding_cards}</div>
</div>

<div class="section" id="tech">
  <div class="sec-head">
    <div class="sec-title">🔬 技术前沿 · Web + HN</div>
    <div class="sec-desc">Serper + Hacker News Algolia API 联合抓取</div>
  </div>
  <hr class="sec-rule">
  <div class="tech-list">{tech_cards}</div>
</div>

<div class="section" id="reads">
  <div class="sec-head">
    <div class="sec-title">📚 播客 · 最新更新</div>
    <div class="sec-desc">Latent Space · Import AI · Dwarkesh · Substack API 直连</div>
  </div>
  <hr class="sec-rule">
  <div class="read-list">{podcast_cards}</div>
</div>

<div class="footer">
  Creekstone Intelligence Brief · 第 {issue_num:03d} 期 · {date_range} · {day_label}<br>
  ⚡ GitHub Actions 自动框架 · X×{len(ALL_KOLS)} KOL · Serper · HN · Substack<br>
  🌐 {GH_PAGES_URL} · {NETLIFY_URL}
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

# ── index.html 更新 ───────────────────────────────────────────────────────────
def update_index(issue_num, date_range, day_label, tweets):
    idx_path = DASH_DIR / "index.html"
    if not idx_path.exists():
        print("    index.html not found, skip")
        return

    html = idx_path.read_text()

    # 1. 更新侧边栏：把旧的最新期改为普通色
    html = re.sub(r'(brief_\d{3}\.html"><span class="sb-dot" style="background:#E05252"></span>第\d{3}期) 🔥',
                  r'\1', html)
    # 2. 插入新侧边栏项（在 第015期 那行前）
    new_sb = (f'    <a class="sb-item" href="brief_{issue_num:03d}.html">'
              f'<span class="sb-dot" style="background:#E05252"></span>'
              f'第{issue_num:03d}期 · {date_range} 🔥</a>\n')
    html = html.replace('    <a class="sb-item" href="brief_015.html">', new_sb + '    <a class="sb-item" href="brief_015.html">', 1)

    # 3. 把旧 latest issue-card 降级
    html = html.replace('class="issue-card latest"', 'class="issue-card"', 1)

    # 4. 构建新 issue-card
    signal_lines = ""
    for t in tweets[:5]:
        user = t.get('username', '?')
        like = t.get('public_metrics', {}).get('like_count', 0)
        text = esc(t.get('text', ''))[:80]
        signal_lines += (f'\n          <div class="ic-sig">'
                         f'<span class="ic-bull">▸</span>'
                         f'@{user} ♥{like:,}：{text}…</div>')

    new_card = f"""      <a href="brief_{issue_num:03d}.html" class="issue-card latest">
        <span class="ic-tag">最新 · 第 {issue_num:03d} 期 · {day_label} · 自动生成</span>
        <div class="ic-period">自动扫描 · {date_range}</div>
        <div class="ic-date">{date_range}</div>
        <div class="ic-signals">{signal_lines}
        </div>
        <div class="ic-footer">
          <span class="ic-sources">X×{len(ALL_KOLS)} · Serper · HN · Substack</span>
          <span class="ic-read">阅读全文 →</span>
        </div>
      </a>

"""
    # 插入到 issue-grid div 内部最前方
    marker = '<div class="issue-grid" id="issueGrid">'
    pos = html.find(marker)
    if pos > 0:
        insert_at = pos + len(marker) + 1  # +1 跳过换行
        html = html[:insert_at] + "\n" + new_card + html[insert_at:]
        print("    index.html: new card inserted into #issueGrid ✓")
    else:
        print("    index.html: marker not found, skip card insert")

    idx_path.write_text(html)

# ── GitHub REST API 上传 ──────────────────────────────────────────────────────
def gh_upload_file(token, repo, filepath, local_path, message):
    """用 GitHub Contents API 上传单个文件，避免 git push 超时"""
    api_url = f"https://api.github.com/repos/{repo}/contents/{filepath}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 获取当前 sha
    sha = ""
    try:
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            sha = json.loads(r.read()).get("sha", "")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"    gh GET {filepath}: HTTP {e.code}")
    except Exception as e:
        # 本地代理或网络问题，不影响 GitHub Actions 运行
        print(f"    gh GET {filepath}: {e} (will try PUT anyway)")

    with open(local_path, "rb") as f:
        content_b64 = base64.b64encode(f.read()).decode()

    payload = {"message": message, "content": content_b64, "branch": "main"}
    if sha:
        payload["sha"] = sha

    data = json.dumps(payload).encode()
    req = urllib.request.Request(api_url, data=data, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            commit_sha = json.loads(r.read()).get("commit", {}).get("sha", "?")[:8]
            return commit_sha
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"    gh PUT {filepath}: HTTP {e.code} {body}")
        return None

def publish_github(token, issue_num):
    """上传新生成的 brief + index.html + state.json 到 GitHub"""
    files_to_upload = [
        (f"brief_{issue_num:03d}.html", DASH_DIR / f"brief_{issue_num:03d}.html"),
        ("index.html",                  DASH_DIR / "index.html"),
        ("scripts/state.json",          DASH_DIR / "scripts" / "state.json"),
    ]
    ok = 0
    for repo_path, local_path in files_to_upload:
        if not local_path.exists():
            print(f"    skip {repo_path} (not found)")
            continue
        try:
            commit = gh_upload_file(
                token, REPO, repo_path, str(local_path),
                f"🤖 Auto-brief {repo_path} issue={issue_num:03d}"
            )
            if commit:
                print(f"    ✓ {repo_path} → commit {commit}")
                ok += 1
        except Exception as e:
            print(f"    ✗ {repo_path}: {e}")
        time.sleep(1)
    print(f"    GitHub: {ok}/{len(files_to_upload)} files uploaded")
    return ok > 0

# ── Netlify 发布（可选，额度满则跳过） ───────────────────────────────────────
def publish_netlify(token, site_id):
    import zipfile as zf
    zip_path = "/tmp/brief_auto.zip"
    with zf.ZipFile(zip_path, 'w', zf.ZIP_DEFLATED) as z:
        for html in DASH_DIR.glob("*.html"):
            z.write(html, html.name)
    with open(zip_path, 'rb') as f:
        data = f.read()
    os.remove(zip_path)
    try:
        req = urllib.request.Request(
            f"https://api.netlify.com/api/v1/sites/{site_id}/deploys",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/zip"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            result = json.loads(r.read())
        state = result.get('state', '?')
        print(f"    Netlify: {state} → {NETLIFY_URL}")
        return True
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:150]
        print(f"    Netlify skip: HTTP {e.code} — {body}")
        return False
    except Exception as e:
        print(f"    Netlify skip: {e}")
        return False

# ── state ─────────────────────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_issue": 15, "last_run": ""}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))

# ── 主函数 ────────────────────────────────────────────────────────────────────
def main():
    sgt     = timezone(timedelta(hours=8))
    now_sgt = datetime.now(sgt)
    now_utc = datetime.now(timezone.utc)
    print(f"=== Creekstone Brief Auto-Generator v4.0 ===")
    print(f"Time: {now_sgt.strftime('%Y-%m-%d %H:%M SGT')}")

    creds         = load_creds()
    netlify_token = os.environ.get('NETLIFY_TOKEN', '').strip()
    gh_token      = os.environ.get('GITHUB_TOKEN', '').strip()
    serper_key    = os.environ.get('SERPER_API_KEY', '').strip()

    state     = load_state()
    issue_num = state['last_issue'] + 1

    start_utc  = now_utc - timedelta(hours=WINDOW_HOURS)
    start_time = start_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
    end_time   = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    start_sgt  = now_sgt - timedelta(hours=WINDOW_HOURS)
    date_range = f"{start_sgt.strftime('%m-%d')}~{now_sgt.strftime('%m-%d')}"
    day_map    = {0:'周一',1:'周二',2:'周三',3:'周四',4:'周五',5:'周六',6:'周日'}
    day_label  = day_map[now_sgt.weekday()]

    print(f"Issue: {issue_num:03d} · Window: {date_range} ({WINDOW_HOURS}h)")
    print(f"Serper: {'✓' if serper_key else '✗ no key'} · "
          f"Netlify: {'✓' if netlify_token else '✗'} · "
          f"GitHub: {'✓' if gh_token else '✗'}")

    # Step 1: X KOL 扫描
    print("\n[1/5] Scanning X KOLs...")
    tweets = scan_kols(creds, start_time, end_time)

    # Step 2: Web 信号
    print("\n[2/5] Gathering web signals...")
    signals = gather_web_signals()

    # Step 3: Podcast / Substack
    print("\n[3/5] Fetching podcasts...")
    episodes = fetch_podcasts(WINDOW_HOURS)

    # Step 4: 生成 HTML
    print("\n[4/5] Building HTML...")
    html = build_html(issue_num, date_range, day_label, tweets, signals, episodes)
    out_path = DASH_DIR / f"brief_{issue_num:03d}.html"
    out_path.write_text(html)
    print(f"  Written: {out_path.name} ({len(html)//1024}KB, {len(html)} bytes)")

    update_index(issue_num, date_range, day_label, tweets)

    # 保存 state
    state['last_issue'] = issue_num
    state['last_run']   = now_utc.isoformat()
    save_state(state)

    # Step 5: 发布
    print("\n[5/5] Publishing...")
    if netlify_token:
        publish_netlify(netlify_token, NETLIFY_SITE)

    if gh_token:
        publish_github(gh_token, issue_num)
    else:
        print("  GitHub REST: no GITHUB_TOKEN, will rely on git push in workflow")

    print(f"\n✅ Done: brief_{issue_num:03d}.html")
    print(f"   GitHub Pages: {GH_PAGES_URL}")
    print(f"   Netlify:      {NETLIFY_URL}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
