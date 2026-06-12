#!/usr/bin/env python3
"""
ETF Daily — a fully self-contained, rules-based daily ETF digest generator.

No paid APIs, no AI keys, no Mira. Pulls free public market data from Yahoo
Finance, applies fixed selection rules, rotates a niche themed ETF each day,
and writes a standalone index.html. Designed to be run daily by GitHub Actions.

Tailored for a Singapore-based investor using Interactive Brokers (IBKR).
Where possible it favours Irish-domiciled UCITS ETFs (LSE-listed, .L) to
reduce US estate-tax exposure and dividend withholding for non-US persons.
"""

import json
import datetime
import urllib.request
import urllib.error
from zoneinfo import ZoneInfo

# --------------------------------------------------------------------------
# CONFIG — edit these lists anytime to change what the digest tracks.
# --------------------------------------------------------------------------

# Core "buy-and-hold" watchlist. UCITS (.L) tickers preferred for SG investors.
# Format: (display name, Yahoo ticker, one-line rationale)
CORE_ETFS = [
    ("Vanguard S&P 500 UCITS (VUAA)", "VUAA.L", "Core US large-cap, accumulating, Irish-domiciled"),
    ("iShares Core MSCI World UCITS (SWDA)", "SWDA.L", "Global developed-market core holding"),
    ("Vanguard FTSE All-World UCITS (VWRA)", "VWRA.L", "One-fund global equity, incl. emerging mkts"),
    ("iShares Core MSCI EM IMI UCITS (EIMI)", "EIMI.L", "Broad emerging-market exposure"),
    ("iShares Core Global Aggregate Bond UCITS (AGGG)", "AGGG.L", "Diversified global bonds, ballast"),
]

# Niche / less-popular themed ETFs — ONE is featured per day, rotated by date.
THEMED_ETFS = [
    ("Quantum Computing & ML (QTUM)", "QTUM", "Defiance Quantum ETF — quantum + machine learning"),
    ("Cybersecurity (BUG)", "BUG", "Global X Cybersecurity ETF"),
    ("Clean Energy (ICLN)", "ICLN", "iShares Global Clean Energy"),
    ("Robotics & AI (BOTZ)", "BOTZ", "Global X Robotics & Artificial Intelligence"),
    ("Uranium & Nuclear (URA)", "URA", "Global X Uranium ETF"),
    ("Water Resources (PHO)", "PHO", "Invesco Water Resources ETF"),
    ("Semiconductors (SOXX)", "SOXX", "iShares Semiconductor ETF"),
    ("Genomics & Biotech (ARKG)", "ARKG", "ARK Genomic Revolution ETF"),
    ("Infrastructure (IGF)", "IGF", "iShares Global Infrastructure"),
    ("Lithium & Battery Tech (LIT)", "LIT", "Global X Lithium & Battery Tech"),
    ("Space Exploration (ARKX)", "ARKX", "ARK Space Exploration & Innovation"),
    ("Agriculture (DBA)", "DBA", "Invesco DB Agriculture Fund"),
    ("Gold Miners (GDX)", "GDX", "VanEck Gold Miners ETF"),
    ("Cloud Computing (SKYY)", "SKYY", "First Trust Cloud Computing ETF"),
]

SGT = ZoneInfo("Asia/Singapore")


# --------------------------------------------------------------------------
# DATA FETCH — Yahoo Finance public quote endpoint (free, no key).
# --------------------------------------------------------------------------

def _fetch_one(ticker):
    """Fetch a single ticker via Yahoo's free chart endpoint (no auth needed)."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
        "?range=5d&interval=1d"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    res = data["chart"]["result"][0]
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    # Prefer the actual previous daily close from the series if available.
    try:
        closes = [c for c in res["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) >= 2:
            price = closes[-1]
            prev = closes[-2]
    except (KeyError, IndexError, TypeError):
        pass
    change_pct = None
    if price is not None and prev:
        change_pct = (price - prev) / prev * 100
    return {
        "price": price,
        "change_pct": change_pct,
        "currency": meta.get("currency", ""),
        "name": meta.get("symbol", ticker),
    }


def fetch_quotes(tickers):
    """Return a dict {ticker: {price, change_pct, currency, name}}; resilient per-ticker."""
    out = {}
    for tic in tickers:
        try:
            out[tic] = _fetch_one(tic)
        except (urllib.error.URLError, json.JSONDecodeError, KeyError,
                IndexError, TimeoutError) as e:
            print(f"WARN: fetch failed for {tic}: {e}")
            out[tic] = {"price": None, "change_pct": None, "currency": "", "name": tic}
    return out


def fmt(val, suffix="", dp=2):
    if val is None:
        return "—"
    return f"{val:.{dp}f}{suffix}"


# --------------------------------------------------------------------------
# RULES ENGINE
# --------------------------------------------------------------------------

def pick_themed(today):
    """Deterministically rotate one themed ETF per day."""
    idx = today.toordinal() % len(THEMED_ETFS)
    return THEMED_ETFS[idx]


def rank_core(quotes):
    """Sort core ETFs by today's % change (momentum) — highest first."""
    rows = []
    for name, tic, why in CORE_ETFS:
        q = quotes.get(tic, {})
        rows.append((name, tic, why, q.get("price"), q.get("change_pct"), q.get("currency")))
    rows.sort(key=lambda r: (r[4] is not None, r[4] or -999), reverse=True)
    return rows


# --------------------------------------------------------------------------
# HTML BUILDER
# --------------------------------------------------------------------------

def build_html(today, core_rows, themed, themed_q):
    date_str = today.strftime("%A, %d %B %Y")

    core_html = ""
    for name, tic, why, price, chg, ccy in core_rows:
        cls = "up" if (chg or 0) >= 0 else "down"
        arrow = "&#9650;" if (chg or 0) >= 0 else "&#9660;"
        core_html += f"""
        <tr>
          <td><strong>{name}</strong><br><span class="muted">{why}</span></td>
          <td class="num">{fmt(price)} <span class="ccy">{ccy}</span></td>
          <td class="num {cls}">{arrow} {fmt(chg, '%')}</td>
        </tr>"""

    tname, ttic, twhy = themed
    tp = themed_q.get(ttic, {})
    tchg = tp.get("change_pct")
    tcls = "up" if (tchg or 0) >= 0 else "down"
    tarrow = "&#9650;" if (tchg or 0) >= 0 else "&#9660;"

    # Top pick = best-momentum core ETF
    top = core_rows[0]
    top_cls = "up" if (top[4] or 0) >= 0 else "down"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ETF Daily — {date_str}</title>
<style>
  :root {{ --bg:#0d1117; --card:#161b22; --line:#30363d; --txt:#e6edf3;
           --muted:#8b949e; --up:#3fb950; --down:#f85149; --accent:#58a6ff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
          background:var(--bg); color:var(--txt); line-height:1.5; }}
  .wrap {{ max-width:860px; margin:0 auto; padding:24px 18px 60px; }}
  h1 {{ font-size:1.6rem; margin:0 0 2px; }}
  .date {{ color:var(--muted); margin-bottom:24px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
           padding:18px 20px; margin-bottom:20px; }}
  h2 {{ font-size:1.1rem; margin:0 0 12px; color:var(--accent); }}
  table {{ width:100%; border-collapse:collapse; }}
  td {{ padding:10px 8px; border-top:1px solid var(--line); vertical-align:top; }}
  tr:first-child td {{ border-top:none; }}
  .num {{ text-align:right; white-space:nowrap; font-variant-numeric:tabular-nums; }}
  .up {{ color:var(--up); }} .down {{ color:var(--down); }}
  .muted {{ color:var(--muted); font-size:.85rem; }}
  .ccy {{ color:var(--muted); font-size:.8rem; }}
  .pick {{ border-left:3px solid var(--accent); padding-left:14px; }}
  .badge {{ display:inline-block; background:#1f6feb22; color:var(--accent);
            border:1px solid #1f6feb55; border-radius:20px; padding:2px 10px;
            font-size:.75rem; margin-bottom:8px; }}
  footer {{ color:var(--muted); font-size:.78rem; margin-top:30px; }}
  a {{ color:var(--accent); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>ETF Daily</h1>
  <div class="date">{date_str} &middot; Singapore &middot; via Interactive Brokers</div>

  <div class="card">
    <h2>Today's Top Pick</h2>
    <div class="pick">
      <span class="badge">Best momentum today</span>
      <p><strong>{top[0]}</strong> — {top[2]}.<br>
      Last: {fmt(top[3])} {top[5] or ''} &nbsp;|&nbsp;
      Today: <span class="{top_cls}">{fmt(top[4],'%')}</span></p>
    </div>
  </div>

  <div class="card">
    <h2>Core Watchlist</h2>
    <table>{core_html}</table>
    <p class="muted">Ranked by today's move. UCITS (.L) funds are Irish-domiciled —
    generally preferable for SG investors on IBKR (lower withholding, no US estate-tax exposure).</p>
  </div>

  <div class="card">
    <h2>Themed Spotlight of the Day</h2>
    <div class="pick">
      <span class="badge">Rotates daily</span>
      <p><strong>{tname}</strong> — {twhy}.<br>
      Last: {fmt(tp.get('price'))} {tp.get('currency','') } &nbsp;|&nbsp;
      Today: <span class="{tcls}">{tarrow} {fmt(tchg,'%')}</span></p>
      <p class="muted">Niche themes are higher-risk satellites — size them small
      relative to your core. Tomorrow features a different theme.</p>
    </div>
  </div>

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
    today = datetime.datetime.now(SGT).date()

    core_tickers = [t for _, t, _ in CORE_ETFS]
    themed = pick_themed(today)
    themed_ticker = themed[1]

    quotes = fetch_quotes(core_tickers + [themed_ticker])

    core_rows = rank_core(quotes)
    html = build_html(today, core_rows, themed, quotes)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"OK: wrote index.html for {today} (themed: {themed[0]})")


if __name__ == "__main__":
    main()
