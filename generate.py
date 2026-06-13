#!/usr/bin/env python3
"""
ETF Daily v2 — self-contained, rules-based daily ETF digest with history.

New in v2:
  * Accumulating archive: each run saves data/<date>.json; the page renders
    ALL days in reverse-chronological order.
  * Collapsible day sections (native <details>, no JS framework).
  * Last-refresh timestamp (SGT) shown on the page.
  * Templated "newsletter" summary auto-written from the day's numbers.
  * Multiple themed ETFs per day (not just one), each with top holdings.

No paid APIs, no AI keys, no Mira. Data: Yahoo Finance free public endpoint.
For a Singapore investor on Interactive Brokers (IBKR); UCITS (.L) preferred.
"""

import os
import json
import glob
import datetime
import urllib.request
import urllib.error
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------
# CONFIG
# --------------------------------------------------------------------------

CORE_ETFS = [
    ("Vanguard S&P 500 UCITS (VUAA)", "VUAA.L", "Core US large-cap, accumulating, Irish-domiciled"),
    ("iShares Core MSCI World UCITS (SWDA)", "SWDA.L", "Global developed-market core holding"),
    ("Vanguard FTSE All-World UCITS (VWRA)", "VWRA.L", "One-fund global equity, incl. emerging mkts"),
    ("iShares Core MSCI EM IMI UCITS (EIMI)", "EIMI.L", "Broad emerging-market exposure"),
    ("iShares Core Global Aggregate Bond UCITS (AGGG)", "AGGG.L", "Diversified global bonds, ballast"),
]

# Themed ETFs with representative top holdings (factual, for context — NOT
# individual stock buy calls). Format: (name, ticker, blurb, [top holdings])
THEMED_ETFS = [
    ("Quantum Computing & ML (QTUM)", "QTUM", "Defiance Quantum ETF", ["NVDA", "IBM", "MSFT", "GOOGL"]),
    ("Cybersecurity (BUG)", "BUG", "Global X Cybersecurity", ["CRWD", "PANW", "ZS", "FTNT"]),
    ("Clean Energy (ICLN)", "ICLN", "iShares Global Clean Energy", ["FSLR", "ENPH", "NEE", "VWS.CO"]),
    ("Robotics & AI (BOTZ)", "BOTZ", "Global X Robotics & AI", ["NVDA", "ISRG", "ABBNY", "KEYS"]),
    ("Uranium & Nuclear (URA)", "URA", "Global X Uranium", ["CCJ", "NXE", "KAP.IL", "PDN.AX"]),
    ("Water Resources (PHO)", "PHO", "Invesco Water Resources", ["WAT", "ECL", "ROP", "XYL"]),
    ("Semiconductors (SOXX)", "SOXX", "iShares Semiconductor", ["NVDA", "AVGO", "AMD", "QCOM"]),
    ("Genomics & Biotech (ARKG)", "ARKG", "ARK Genomic Revolution", ["TEM", "CRSP", "TWST", "RXRX"]),
    ("Infrastructure (IGF)", "IGF", "iShares Global Infrastructure", ["AENA.MC", "NEE", "TRP", "ENB"]),
    ("Lithium & Battery (LIT)", "LIT", "Global X Lithium & Battery", ["ALB", "TSLA", "BYDDY", "SQM"]),
    ("Space Exploration (ARKX)", "ARKX", "ARK Space Exploration", ["RKLB", "KTOS", "TER", "TRMB"]),
    ("Agriculture (DBA)", "DBA", "Invesco DB Agriculture", ["Corn", "Soybeans", "Sugar", "Coffee"]),
    ("Gold Miners (GDX)", "GDX", "VanEck Gold Miners", ["NEM", "AEM", "GOLD", "WPM"]),
    ("Cloud Computing (SKYY)", "SKYY", "First Trust Cloud Computing", ["ORCL", "MSFT", "GOOGL", "NET"]),
]

# How many themed ETFs to feature each day (rotates through the list).
THEMES_PER_DAY = 3

SGT = ZoneInfo("Asia/Singapore")
DATA_DIR = "data"


# --------------------------------------------------------------------------
# DATA FETCH — Yahoo chart endpoint (free, no auth, resilient per-ticker)
# --------------------------------------------------------------------------

def _fetch_one(ticker):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           "?range=5d&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    res = data["chart"]["result"][0]
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    try:
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) >= 2:
            price, prev = closes[-1], closes[-2]
    except (KeyError, IndexError, TypeError):
        pass
    change_pct = (price - prev) / prev * 100 if (price is not None and prev) else None
    return {"price": price, "change_pct": change_pct,
            "currency": meta.get("currency", ""), "name": meta.get("symbol", ticker)}


def fetch_quotes(tickers):
    out = {}
    for tic in tickers:
        try:
            out[tic] = _fetch_one(tic)
        except (urllib.error.URLError, json.JSONDecodeError, KeyError,
                IndexError, TimeoutError) as e:
            print(f"WARN: fetch failed for {tic}: {e}")
            out[tic] = {"price": None, "change_pct": None, "currency": "", "name": tic}
    return out


# --------------------------------------------------------------------------
# NEWS FETCH — Yahoo Finance free search endpoint (real headlines + links)
# --------------------------------------------------------------------------

def fetch_news(query, count=3):
    """Return [{title, link, publisher}] for a ticker/keyword; [] on failure."""
    url = (f"https://query1.finance.yahoo.com/v1/finance/search?q={query}"
           f"&newsCount={count}&quotesCount=0")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.load(resp)
        items = []
        for n in data.get("news", [])[:count]:
            link = n.get("link", "")
            title = n.get("title", "")
            if link and title:
                items.append({"title": title, "link": link,
                              "publisher": n.get("publisher", "")})
        return items
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, TimeoutError) as e:
        print(f"WARN: news fetch failed for {query}: {e}")
        return []


# --------------------------------------------------------------------------
# RULES
# --------------------------------------------------------------------------

def pick_themes(today, n):
    """Rotate a window of N themed ETFs per day, deterministically."""
    base = today.toordinal() * n
    return [THEMED_ETFS[(base + i) % len(THEMED_ETFS)] for i in range(n)]


def fmt(val, suffix="", dp=2):
    return "—" if val is None else f"{val:.{dp}f}{suffix}"


def newsletter(core_rows, themed_rows):
    """Templated, factual market summary built from the day's numbers."""
    valid = [r for r in core_rows if r["change_pct"] is not None]
    if not valid:
        return "Market data was unavailable for this run; check back next refresh."
    best = max(valid, key=lambda r: r["change_pct"])
    worst = min(valid, key=lambda r: r["change_pct"])
    avg = sum(r["change_pct"] for r in valid) / len(valid)
    tone = "broadly higher" if avg > 0.15 else "broadly lower" if avg < -0.15 else "little changed"
    parts = [
        f"Core watchlist was {tone} (avg {fmt(avg, '%')}).",
        f"{best['short']} led ({fmt(best['change_pct'], '%')}); "
        f"{worst['short']} lagged ({fmt(worst['change_pct'], '%')}).",
    ]
    tvalid = [t for t in themed_rows if t["change_pct"] is not None]
    if tvalid:
        tbest = max(tvalid, key=lambda t: t["change_pct"])
        parts.append(f"Among themes, {tbest['short']} stood out ({fmt(tbest['change_pct'], '%')}).")
    return " ".join(parts)


def short_name(full):
    """Pull the ticker-ish short label from a display name like '... (VUAA)'."""
    if "(" in full and ")" in full:
        return full[full.rfind("(") + 1: full.rfind(")")]
    return full


# --------------------------------------------------------------------------
# BUILD ONE DAY'S DATA RECORD
# --------------------------------------------------------------------------

def build_day_record(today, now_sgt):
    themes = pick_themes(today, THEMES_PER_DAY)
    core_tickers = [t for _, t, _ in CORE_ETFS]
    theme_tickers = [t[1] for t in themes]

    # Gather candidate stock tickers from the featured themes' holdings.
    # Keep only real US-listed symbols (skip commodity words / non-equity).
    stock_candidates = []
    for _, _, _, holdings in themes:
        for h in holdings:
            if h.isupper() and h.isalpha() and 1 <= len(h) <= 5 and h not in stock_candidates:
                stock_candidates.append(h)

    quotes = fetch_quotes(core_tickers + theme_tickers + stock_candidates)

    core_rows = []
    for name, tic, why in CORE_ETFS:
        q = quotes.get(tic, {})
        core_rows.append({"name": name, "short": short_name(name), "ticker": tic,
                          "why": why, "price": q.get("price"),
                          "change_pct": q.get("change_pct"), "ccy": q.get("currency")})
    core_rows.sort(key=lambda r: (r["change_pct"] is not None, r["change_pct"] or -999),
                   reverse=True)

    themed_rows = []
    for name, tic, blurb, holdings in themes:
        q = quotes.get(tic, {})
        themed_rows.append({"name": name, "short": short_name(name), "ticker": tic,
                            "blurb": blurb, "holdings": holdings,
                            "price": q.get("price"), "change_pct": q.get("change_pct"),
                            "ccy": q.get("currency")})

    # ETFs in focus: top 5 by today's momentum across core + themed.
    etf_pool = core_rows + themed_rows
    etfs_focus = sorted([e for e in etf_pool if e["change_pct"] is not None],
                        key=lambda e: e["change_pct"], reverse=True)[:5]

    # Stocks in focus: theme holdings, ranked by today's momentum (top 5).
    stock_rows = []
    for tic in stock_candidates:
        q = quotes.get(tic, {})
        if q.get("change_pct") is not None:
            stock_rows.append({"ticker": tic, "price": q.get("price"),
                               "change_pct": q.get("change_pct"), "ccy": q.get("currency")})
    stocks_focus = sorted(stock_rows, key=lambda s: s["change_pct"], reverse=True)[:5]

    # News: a few headlines for the leading core ETF + the leading theme.
    news = []
    seen_links = set()
    news_queries = []
    if core_rows:
        news_queries.append(core_rows[0]["ticker"])
    if themed_rows:
        news_queries.append(themed_rows[0]["ticker"])
    if stocks_focus:
        news_queries.append(stocks_focus[0]["ticker"])
    for q in news_queries:
        for item in fetch_news(q, count=3):
            if item["link"] not in seen_links:
                seen_links.add(item["link"])
                news.append(item)
    news = news[:6]

    return {
        "date": today.isoformat(),
        "date_display": today.strftime("%A, %d %B %Y"),
        "refreshed": now_sgt.strftime("%d %b %Y, %H:%M SGT"),
        "newsletter": newsletter(core_rows, themed_rows),
        "core": core_rows,
        "themed": themed_rows,
        "etfs_focus": etfs_focus,
        "stocks_focus": stocks_focus,
        "news": news,
    }


# --------------------------------------------------------------------------
# HTML RENDERING
# --------------------------------------------------------------------------

def render_day(rec, open_default=False):
    def chg_span(c):
        cls = "up" if (c or 0) >= 0 else "down"
        arrow = "&#9650;" if (c or 0) >= 0 else "&#9660;"
        return f'<span class="{cls}">{arrow} {fmt(c, "%")}</span>'

    core_html = ""
    for r in rec["core"]:
        core_html += f"""
        <tr><td><strong>{r['name']}</strong><br><span class="muted">{r['why']}</span></td>
        <td class="num">{fmt(r['price'])} <span class="ccy">{r['ccy']}</span></td>
        <td class="num">{chg_span(r['change_pct'])}</td></tr>"""

    themed_html = ""
    for t in rec["themed"]:
        holdings = ", ".join(t["holdings"])
        themed_html += f"""
        <div class="theme">
          <div class="theme-head"><strong>{t['name']}</strong> {chg_span(t['change_pct'])}</div>
          <div class="muted">{t['blurb']} &middot; Last {fmt(t['price'])} {t['ccy']}</div>
          <div class="muted">Top holdings: {holdings}</div>
        </div>"""

    top = rec["core"][0]

    # ETFs in focus (top momentum)
    etfs_html = ""
    for e in rec.get("etfs_focus", []):
        etfs_html += f"""
        <tr><td><strong>{e['short']}</strong> <span class="muted">{e.get('ticker','')}</span></td>
        <td class="num">{fmt(e['price'])} <span class="ccy">{e.get('ccy','')}</span></td>
        <td class="num">{chg_span(e['change_pct'])}</td></tr>"""

    # Stocks in focus (theme holdings by momentum)
    stocks_html = ""
    for s in rec.get("stocks_focus", []):
        stocks_html += f"""
        <tr><td><strong>{s['ticker']}</strong></td>
        <td class="num">{fmt(s['price'])} <span class="ccy">{s.get('ccy','')}</span></td>
        <td class="num">{chg_span(s['change_pct'])}</td></tr>"""

    # News links
    news_html = ""
    for n in rec.get("news", []):
        pub = f" <span class=\"muted\">&middot; {n['publisher']}</span>" if n.get("publisher") else ""
        news_html += f'<li><a href="{n["link"]}" target="_blank" rel="noopener">{n["title"]}</a>{pub}</li>'
    news_block = (f"""
      <div class="card">
        <h3>News to Read</h3>
        <ul class="news">{news_html}</ul>
      </div>""" if news_html else "")

    etfs_block = (f"""
      <div class="card">
        <h3>ETFs in Focus (top momentum today)</h3>
        <table>{etfs_html}</table>
      </div>""" if etfs_html else "")

    stocks_block = (f"""
      <div class="card">
        <h3>Stocks in Focus (from today's themes)</h3>
        <table>{stocks_html}</table>
        <p class="muted">These are theme-ETF holdings surfaced by today's momentum —
        shown for research, NOT buy recommendations. Speculative themes (e.g. quantum)
        are especially high-risk. Always do your own due diligence.</p>
      </div>""" if stocks_html else "")

    openattr = " open" if open_default else ""
    return f"""
  <details class="day"{openattr}>
    <summary>
      <span class="day-date">{rec['date_display']}</span>
      <span class="day-meta">Refreshed {rec['refreshed']}</span>
    </summary>
    <div class="day-body">
      <div class="card">
        <h3>Daily Newsletter</h3>
        <p>{rec['newsletter']}</p>
      </div>{news_block}
      <div class="card">
        <h3>Top Pick (best momentum)</h3>
        <div class="pick"><strong>{top['name']}</strong> — {top['why']}.<br>
        Last {fmt(top['price'])} {top['ccy']} &nbsp;|&nbsp; {chg_span(top['change_pct'])}</div>
      </div>{etfs_block}{stocks_block}
      <div class="card">
        <h3>Core Watchlist</h3>
        <table>{core_html}</table>
      </div>
      <div class="card">
        <h3>Themed ETFs &amp; Tickers Today</h3>
        {themed_html}
        <p class="muted">Holdings shown for context, not individual buy advice.
        Niche themes are higher-risk satellites — size them small vs. your core.</p>
      </div>
    </div>
  </details>"""


def render_page(records):
    # records: list sorted newest-first
    days_html = "".join(render_day(r, open_default=(i == 0))
                        for i, r in enumerate(records))
    latest_refresh = records[0]["refreshed"] if records else "—"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Stock Market News</title>
<style>
  :root {{ --bg:#0d1117; --card:#161b22; --line:#30363d; --txt:#e6edf3;
           --muted:#8b949e; --up:#3fb950; --down:#f85149; --accent:#58a6ff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
          background:var(--bg); color:var(--txt); line-height:1.5; }}
  .wrap {{ max-width:880px; margin:0 auto; padding:24px 18px 60px; }}
  h1 {{ font-size:1.7rem; margin:0 0 2px; }}
  .sub {{ color:var(--muted); margin-bottom:6px; }}
  .refresh {{ color:var(--accent); font-size:.85rem; margin-bottom:22px; }}
  details.day {{ background:var(--card); border:1px solid var(--line);
                 border-radius:12px; margin-bottom:14px; overflow:hidden; }}
  summary {{ cursor:pointer; padding:14px 18px; list-style:none;
             display:flex; justify-content:space-between; align-items:center;
             gap:12px; flex-wrap:wrap; }}
  summary::-webkit-details-marker {{ display:none; }}
  summary::before {{ content:"\\25B6"; color:var(--muted); margin-right:8px;
                     transition:transform .15s; }}
  details[open] summary::before {{ transform:rotate(90deg); }}
  .day-date {{ font-weight:600; }}
  .day-meta {{ color:var(--muted); font-size:.8rem; }}
  .day-body {{ padding:0 18px 16px; }}
  .card {{ border-top:1px solid var(--line); padding:14px 0; }}
  h3 {{ font-size:1rem; margin:0 0 8px; color:var(--accent); }}
  table {{ width:100%; border-collapse:collapse; }}
  td {{ padding:8px 6px; border-top:1px solid var(--line); vertical-align:top; }}
  tr:first-child td {{ border-top:none; }}
  .num {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
  .up {{ color:var(--up); }} .down {{ color:var(--down); }}
  .muted {{ color:var(--muted); font-size:.85rem; }}
  .ccy {{ color:var(--muted); font-size:.8rem; }}
  .pick {{ border-left:3px solid var(--accent); padding-left:12px; }}
  .theme {{ border-left:3px solid var(--line); padding-left:12px; margin-bottom:12px; }}
  .theme-head {{ display:flex; justify-content:space-between; gap:10px; }}
  .news {{ margin:0; padding-left:18px; }}
  .news li {{ margin-bottom:7px; }}
  .news a {{ color:var(--accent); text-decoration:none; }}
  .news a:hover {{ text-decoration:underline; }}
  footer {{ color:var(--muted); font-size:.78rem; margin-top:28px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Daily Stock Market News</h1>
  <div class="sub">Singapore &middot; via Interactive Brokers &middot; rules-based archive</div>
  <div class="refresh">Last refresh: {latest_refresh} &middot; newest day expanded, click any date to expand/collapse</div>
  {days_html}
  <footer>
    Generated automatically by GitHub Actions &middot; rules-based, no manual input.<br>
    <strong>Not financial advice.</strong> Data: Yahoo Finance (delayed). Always do your own research.
  </footer>
</div>
</body>
</html>"""


# --------------------------------------------------------------------------
# MAIN
# --------------------------------------------------------------------------

def main():
    now_sgt = datetime.datetime.now(SGT)
    today = now_sgt.date()
    os.makedirs(DATA_DIR, exist_ok=True)

    # Build & save today's record (overwrites today's file if re-run same day).
    rec = build_day_record(today, now_sgt)
    with open(os.path.join(DATA_DIR, f"{today.isoformat()}.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)

    # Load ALL saved days, newest first.
    records = []
    for path in glob.glob(os.path.join(DATA_DIR, "*.json")):
        try:
            with open(path, encoding="utf-8") as f:
                records.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    records.sort(key=lambda r: r["date"], reverse=True)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(render_page(records))
    print(f"OK: {today} saved; page now shows {len(records)} day(s).")


if __name__ == "__main__":
    main()
