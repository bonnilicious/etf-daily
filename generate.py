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
    # All Irish-domiciled UCITS, LSE-listed (.L) — chosen for a Singapore investor
    # on IBKR: 15% (not 30%) US dividend withholding, no US estate-tax exposure,
    # no SG capital-gains/dividend tax. Accumulating share classes preferred
    # (dividends auto-reinvested, no manual re-investing, tidier for SG holders).
    # Format: (name, ticker, why, TER%, distribution)  — TER/dist are STATIC
    # (no free live feed for fees); update by hand if a fund changes its fee.
    # ACCUMULATING-ONLY core. All distributing (Dist) funds removed for a
    # tax-tidy, auto-reinvesting core (dropped AGGG, VHYL, FXC); gold ETCs
    # (SGLN, PHAU) also removed per preference. No fixed size cap — the list
    # is simply "every Acc UCITS core holding we track".
    ("Vanguard S&P 500 UCITS (VUAA)", "VUAA.L", "Core US large-cap, accumulating, Irish-domiciled", 0.07, "Acc"),
    ("Invesco S&P 500 UCITS (SPXP)", "SPXP.L", "Cheapest S&P 500 core, accumulating", 0.05, "Acc"),
    ("iShares Core S&P 500 UCITS (CSPX)", "CSPX.L", "The classic large S&P 500 UCITS, deep liquidity", 0.07, "Acc"),
    ("iShares Core MSCI World UCITS (SWDA)", "SWDA.L", "Global developed-market core holding", 0.20, "Acc"),
    ("Vanguard FTSE Dev World UCITS (VHVG)", "VHVG.L", "Developed-world core, low TER, accumulating", 0.12, "Acc"),
    ("Vanguard FTSE All-World UCITS (VWRA)", "VWRA.L", "One-fund global equity, incl. emerging mkts; largest/most liquid", 0.19, "Acc"),
    ("iShares FTSE All-World UCITS (FTAW)", "FTAW.L", "Same FTSE All-World index as VWRA, cheaper TER (new/smaller AUM)", 0.12, "Acc"),
    ("Xtrackers FTSE All-World UCITS 1C (ALLW)", "ALLW.L", "Same FTSE All-World index as VWRA, cheapest TER on market", 0.07, "Acc"),
    ("iShares Core MSCI EM IMI UCITS (EIMI)", "EIMI.L", "Broad emerging-market exposure", 0.18, "Acc"),
    ("iShares Nasdaq 100 UCITS (CNX1)", "CNX1.L", "US tech/growth tilt, accumulating", 0.33, "Acc"),
    ("iShares MSCI World SRI UCITS (SUWS)", "SUWS.L", "ESG-screened global developed alternative", 0.20, "Acc"),
    ("iShares $ Treasury 7-10y UCITS (IDTM)", "IDTM.L", "US Treasuries, rate-sensitive ballast (Acc)", 0.07, "Acc"),
]

# Map US-listed focus tickers -> a London-listed UCITS alternative where one
# meaningfully exists. Used to surface a cost/tax-efficient wrapper for a
# Singapore IBKR investor next to the US-domiciled momentum picks.
# Format: US_ticker -> (UCITS name, LSE ticker, note, TER%)  — TER is STATIC.
UCITS_ALTERNATIVES = {
    # Broad / index
    "SOXX": ("iShares Semiconductor / S&P US Tech UCITS (IUIT)", "IUIT.L", "Closest UCITS proxy for US tech/semis", 0.15),
    "SMH":  ("iShares S&P 500 Info Tech UCITS (IITU)", "IITU.L", "US tech sector UCITS", 0.15),
    "SKYY": ("iShares Digitalisation UCITS (DGTL)", "DGTL.L", "Digital/cloud-leaning UCITS proxy", 0.40),
    "QTUM": ("L&G Artificial Intelligence UCITS (AIAI)", "AIAI.L", "No pure-quantum UCITS; AI is closest proxy", 0.49),
    "BOTZ": ("L&G ROBO Global Robotics & Automation (ROBO)", "ROBO.L", "Robotics & automation UCITS", 0.80),
    "ROBO": ("L&G ROBO Global Robotics & Automation (ROBO)", "ROBO.L", "Robotics & automation UCITS", 0.80),
    "BUG":  ("L&G Cyber Security UCITS (ISPY)", "ISPY.L", "Cybersecurity UCITS", 0.69),
    "HACK": ("L&G Cyber Security UCITS (ISPY)", "ISPY.L", "Cybersecurity UCITS", 0.69),
    "ICLN": ("iShares Global Clean Energy UCITS (INRG)", "INRG.L", "Clean-energy UCITS (UK-listed)", 0.65),
    "TAN":  ("iShares Global Clean Energy UCITS (INRG)", "INRG.L", "Solar-heavy theme via clean-energy UCITS", 0.65),
    "URA":  ("Global X Uranium UCITS (URNU/URNG)", "URNU.L", "Uranium miners UCITS", 0.69),
    "URNM": ("Global X Uranium UCITS (URNU/URNG)", "URNU.L", "Uranium miners UCITS", 0.69),
    "LIT":  ("Global X Lithium & Battery Tech UCITS", "LITG.L", "Lithium/battery UCITS", 0.60),
    "GDX":  ("VanEck Gold Miners UCITS (GDX)", "GDGB.L", "Gold-miners UCITS (LSE)", 0.53),
    "GDXJ": ("VanEck Junior Gold Miners UCITS", "GJGB.L", "Junior gold-miners UCITS", 0.55),
    "IGF":  ("iShares Global Infrastructure UCITS (INFR)", "INFR.L", "Global infrastructure UCITS", 0.65),
    "ARKG": ("iShares Healthcare Innovation UCITS (HEAL)", "HEAL.L", "No ARK UCITS; healthcare-innovation proxy", 0.40),
    "ARKK": ("iShares Healthcare Innovation UCITS (HEAL)", "HEAL.L", "Disruptive-innovation proxy (imperfect)", 0.40),
    "PHO":  ("iShares Global Water UCITS (IH2O/DH2O)", "IH2O.L", "Global water UCITS", 0.65),
    "PAVE": ("iShares Global Infrastructure UCITS (INFR)", "INFR.L", "Infrastructure UCITS proxy", 0.65),
    "DBA":  ("WisdomTree Agriculture (AGAP)", "AGAP.L", "Agri-commodity ETC (UCITS-style, LSE)", 0.49),
}

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
    # 1y daily history with timestamps — lets us compute YTD/1M/3M/1Y, volatility
    # and 52-week high/low for free from the same single request.
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           "?range=1y&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    res = data["chart"]["result"][0]
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")

    ts = res.get("timestamp", []) or []
    raw_closes = []
    try:
        raw_closes = res["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        raw_closes = []

    # Pair timestamps with non-null closes.
    series = [(t, c) for t, c in zip(ts, raw_closes) if c is not None]
    closes = [c for _, c in series]
    if len(closes) >= 2:
        price, prev = closes[-1], closes[-2]
    change_pct = (price - prev) / prev * 100 if (price is not None and prev) else None

    def ret_from(base):
        return (price - base) / base * 100 if (price and base) else None

    # Period returns by walking back N trading days (~21/day-month, 63/3m, 252/1y).
    def ret_days(n):
        return ret_from(closes[-(n + 1)]) if len(closes) > n else None

    ret_1m = ret_days(21)
    ret_3m = ret_days(63)
    ret_1y = ret_from(closes[0]) if len(closes) > 200 else None

    # YTD: first close on/after Jan 1 of the current year.
    ytd = None
    if series:
        yr = datetime.datetime.now(SGT).year
        for t, c in series:
            if datetime.datetime.fromtimestamp(t, SGT).year == yr:
                ytd = ret_from(c)
                break

    # 52-week high/low + % below high.
    hi = max(closes) if closes else None
    lo = min(closes) if closes else None
    from_hi = (price - hi) / hi * 100 if (price and hi) else None

    # Annualised volatility from daily returns. Broad ETFs realistically never
    # move >25% in a day, so returns beyond that are Yahoo data glitches
    # (bad single-day prints / split artefacts) — drop them before computing.
    vol = None
    if len(closes) > 30:
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1]
                for i in range(1, len(closes)) if closes[i - 1]]
        rets = [r for r in rets if abs(r) < 0.25]
        if len(rets) > 20:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            vol = (var ** 0.5) * (252 ** 0.5) * 100

    return {"price": price, "change_pct": change_pct,
            "currency": meta.get("currency", ""), "name": meta.get("symbol", ticker),
            "ytd": ytd, "ret_1m": ret_1m, "ret_3m": ret_3m, "ret_1y": ret_1y,
            "hi52": hi, "lo52": lo, "from_hi": from_hi, "vol": vol}


def fetch_quotes(tickers):
    out = {}
    for tic in tickers:
        try:
            out[tic] = _fetch_one(tic)
        except (urllib.error.URLError, json.JSONDecodeError, KeyError,
                IndexError, TimeoutError) as e:
            print(f"WARN: fetch failed for {tic}: {e}")
            out[tic] = {"price": None, "change_pct": None, "currency": "", "name": tic,
                        "ytd": None, "ret_1m": None, "ret_3m": None, "ret_1y": None,
                        "hi52": None, "lo52": None, "from_hi": None, "vol": None}
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

# --------------------------------------------------------------------------
# PRO SCORE — a rules-based, Investing.com-Pro+-style composite (0-100)
# --------------------------------------------------------------------------
# Five weighted pillars, tuned for a long-term Singapore UCITS/IBKR investor:
#   SG tax efficiency 25% | Cost 20% | Risk-adjusted return 25%
#   Momentum 15% | Liquidity/size proxy 15%
# Every metric is converted to a 0-100 sub-score by PERCENTILE-RANK within the
# scored peer set (self-calibrating — no magic thresholds to maintain), except
# tax efficiency which uses fixed rules (domicile/dist policy are categorical).
# Missing data for a pillar => that pillar is dropped and remaining weights are
# renormalised, so a fund is never punished for a Yahoo data gap.

SCORE_WEIGHTS = {"tax": 0.25, "cost": 0.20, "riskadj": 0.25,
                 "momentum": 0.15, "liquidity": 0.15}


def _pctile_scores(values, higher_is_better=True):
    """Map a list of (key, value) into {key: 0-100} by percentile rank.
    None values get no score (returned as None)."""
    have = [(k, v) for k, v in values if v is not None]
    out = {k: None for k, _ in values}
    if not have:
        return out
    if len(have) == 1:
        out[have[0][0]] = 100.0
        return out
    ranked = sorted(have, key=lambda kv: kv[1], reverse=not higher_is_better)
    n = len(ranked)
    for i, (k, _) in enumerate(ranked):
        # rank 0 (worst) -> 0, rank n-1 (best) -> 100
        out[k] = round(i / (n - 1) * 100, 1)
    return out


def score_etfs(core_rows):
    """Attach a composite 'pro_score' (0-100) + pillar breakdown + verdict to
    each core row, then return the rows sorted by score (best first)."""
    keyed = [(r["ticker"], r) for r in core_rows]

    # --- Pillar 1: SG tax efficiency (fixed-rule, 0-100) ---
    # All core funds are Irish-domiciled UCITS (15% withholding, no US estate
    # tax). Accumulating > Distributing for a compounding SG holder (no manual
    # re-investing, no dividend leakage). Gold/'—' treated as neutral-high.
    for tic, r in keyed:
        dist = r.get("dist", "")
        r["_s_tax"] = 100.0 if dist == "Acc" else (85.0 if dist == "—" else 60.0)

    # --- Pillar 2: Cost (lower TER better) ---
    cost = _pctile_scores([(t, r.get("ter")) for t, r in keyed],
                          higher_is_better=False)

    # --- Pillar 3: Risk-adjusted return (Sharpe-like = 1Y return / vol) ---
    def sharpe_like(r):
        ret, vol = r.get("ret_1y"), r.get("vol")
        if ret is None or not vol:
            return None
        return ret / vol
    riskadj = _pctile_scores([(t, sharpe_like(r)) for t, r in keyed])

    # --- Pillar 4: Momentum (blend of 1M, 3M, 1Y trend + proximity to 52w hi) ---
    def momentum(r):
        parts = [r.get("ret_1m"), r.get("ret_3m"), r.get("ret_1y")]
        parts = [p for p in parts if p is not None]
        if not parts:
            return None
        base = sum(parts) / len(parts)
        fh = r.get("from_hi")            # negative = below high
        if fh is not None:
            base += fh * 0.25            # small bonus for being near the high
        return base
    momo = _pctile_scores([(t, momentum(r)) for t, r in keyed])

    # --- Pillar 5: Liquidity/size proxy ---
    # No free AUM feed, so use realised annualised volatility as an inverse
    # proxy (huge broad ETFs are lower-vol & deeply liquid). Lower vol => higher
    # liquidity sub-score. Rough but consistent across the peer set.
    liq = _pctile_scores([(t, r.get("vol")) for t, r in keyed],
                         higher_is_better=False)

    for tic, r in keyed:
        pillars = {"tax": r["_s_tax"], "cost": cost[tic], "riskadj": riskadj[tic],
                   "momentum": momo[tic], "liquidity": liq[tic]}
        # Renormalise weights over the pillars that actually have a score.
        avail = {k: v for k, v in pillars.items() if v is not None}
        wsum = sum(SCORE_WEIGHTS[k] for k in avail) or 1.0
        composite = sum(v * SCORE_WEIGHTS[k] for k, v in avail.items()) / wsum
        r["pro_score"] = round(composite, 1)
        r["pillars"] = {k: (round(v, 1) if v is not None else None)
                        for k, v in pillars.items()}
        r["verdict"] = _verdict(r)
        r.pop("_s_tax", None)

    return sorted(core_rows, key=lambda r: r["pro_score"], reverse=True)


def _verdict(r):
    """Plain-language, Pro-Tips-style one-liner from the score + pillars."""
    s = r["pro_score"]
    p = r.get("pillars", {})
    tag = ("Strong" if s >= 70 else "Solid" if s >= 55
           else "Fair" if s >= 40 else "Watch")
    bits = []
    if r.get("dist") == "Acc":
        bits.append("tax-efficient Acc UCITS")
    if p.get("cost") is not None and p["cost"] >= 70:
        bits.append("low cost")
    if p.get("riskadj") is not None and p["riskadj"] >= 70:
        bits.append("good risk-adjusted return")
    if p.get("momentum") is not None and p["momentum"] >= 70:
        bits.append("positive momentum")
    elif p.get("momentum") is not None and p["momentum"] <= 30:
        bits.append("weak momentum")
    detail = ", ".join(bits) if bits else "balanced profile"
    return f"{tag} — {detail}."


def build_day_record(today, now_sgt):
    themes = pick_themes(today, THEMES_PER_DAY)
    core_tickers = [t[1] for t in CORE_ETFS]
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
    for name, tic, why, ter, dist in CORE_ETFS:
        q = quotes.get(tic, {})
        core_rows.append({"name": name, "short": short_name(name), "ticker": tic,
                          "why": why, "ter": ter, "dist": dist,
                          "price": q.get("price"), "change_pct": q.get("change_pct"),
                          "ccy": q.get("currency"), "ytd": q.get("ytd"),
                          "ret_1m": q.get("ret_1m"),
                          "ret_1y": q.get("ret_1y"), "vol": q.get("vol")})
    # Core Watchlist display order: sort by TER, lowest to highest (cheapest
    # first). None TERs sort last.
    core_rows.sort(key=lambda r: (r.get("ter") is None, r.get("ter") or 999))

    # Pro Score: rank the core watchlist by the composite 0-100 model. Uses a
    # copy so the day-momentum ordering of `core` (above) is preserved.
    scored_rows = score_etfs([dict(r) for r in core_rows])

    themed_rows = []
    for name, tic, blurb, holdings in themes:
        q = quotes.get(tic, {})
        themed_rows.append({"name": name, "short": short_name(name), "ticker": tic,
                            "blurb": blurb, "holdings": holdings,
                            "price": q.get("price"), "change_pct": q.get("change_pct"),
                            "ccy": q.get("currency"), "ytd": q.get("ytd"),
                            "ret_1m": q.get("ret_1m"), "ret_1y": q.get("ret_1y")})

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
                               "change_pct": q.get("change_pct"), "ccy": q.get("currency"),
                               "ret_1m": q.get("ret_1m"), "from_hi": q.get("from_hi")})
    stocks_focus = sorted(stock_rows, key=lambda s: s["change_pct"], reverse=True)[:5]

    # UCITS/LSE alternatives for today's US-listed themed ETFs — so a Singapore
    # IBKR investor can see a more tax/cost-efficient wrapper next to each
    # US-domiciled momentum pick. Only includes themes that HAVE a real UCITS
    # proxy (from UCITS_ALTERNATIVES); de-duplicated by LSE ticker.
    ucits_alts = []
    seen_lse = set()
    for t in themed_rows:
        alt = UCITS_ALTERNATIVES.get(t["ticker"])
        if alt and alt[1] not in seen_lse:
            seen_lse.add(alt[1])
            ucits_alts.append({"us_ticker": t["ticker"], "us_name": t["short"],
                               "ucits_name": alt[0], "lse_ticker": alt[1],
                               "note": alt[2], "ter": alt[3]})

    # News: a few headlines for the leading core ETF + the leading theme.
    news = []
    seen_links = set()
    news_queries = []
    if core_rows:
        _cv = [r for r in core_rows if r["change_pct"] is not None]
        lead_core = max(_cv, key=lambda r: r["change_pct"]) if _cv else core_rows[0]
        news_queries.append(lead_core["ticker"])
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
        "scored": scored_rows,
        "themed": themed_rows,
        "etfs_focus": etfs_focus,
        "stocks_focus": stocks_focus,
        "ucits_alts": ucits_alts,
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

    core_html = """
        <tr class="hdr"><td>Fund</td><td class="num">TER</td><td class="num">Type</td>
        <td class="num">Last</td><td class="num">Day</td><td class="num">YTD</td>
        <td class="num">1Y</td><td class="num">Vol</td></tr>"""
    for r in rec["core"]:
        core_html += f"""
        <tr><td><strong>{r['name']}</strong><br><span class="muted">{r['why']}</span></td>
        <td class="num">{fmt(r.get('ter'), '%')}</td>
        <td class="num"><span class="ccy">{r.get('dist','')}</span></td>
        <td class="num">{fmt(r['price'])} <span class="ccy">{r['ccy']}</span></td>
        <td class="num">{chg_span(r['change_pct'])}</td>
        <td class="num">{chg_span(r.get('ytd'))}</td>
        <td class="num">{chg_span(r.get('ret_1y'))}</td>
        <td class="num">{fmt(r.get('vol'), '%', 1)}</td></tr>"""

    themed_html = ""
    for t in rec["themed"]:
        holdings = ", ".join(t["holdings"])
        themed_html += f"""
        <div class="theme">
          <div class="theme-head"><strong>{t['name']}</strong> {chg_span(t['change_pct'])}</div>
          <div class="muted">{t['blurb']} &middot; Last {fmt(t['price'])} {t['ccy']}</div>
          <div class="muted">1M {fmt(t.get('ret_1m'), '%')} &middot; YTD {fmt(t.get('ytd'), '%')} &middot; 1Y {fmt(t.get('ret_1y'), '%')}</div>
          <div class="muted">Top holdings: {holdings}</div>
        </div>"""

    # Top Pick = best momentum today (core is now TER-sorted for display, so
    # pick the max-change fund explicitly rather than relying on order).
    _core_valid = [r for r in rec["core"] if r["change_pct"] is not None]
    top = (max(_core_valid, key=lambda r: r["change_pct"])
           if _core_valid else rec["core"][0])

    # ETFs in focus (top momentum)
    etfs_html = ""
    if rec.get("etfs_focus"):
        etfs_html += """
        <tr class="hdr"><td>ETF</td><td class="num">Last</td><td class="num">Day</td>
        <td class="num">1M</td><td class="num">YTD</td></tr>"""
    for e in rec.get("etfs_focus", []):
        etfs_html += f"""
        <tr><td><strong>{e['short']}</strong> <span class="muted">{e.get('ticker','')}</span></td>
        <td class="num">{fmt(e['price'])} <span class="ccy">{e.get('ccy','')}</span></td>
        <td class="num">{chg_span(e['change_pct'])}</td>
        <td class="num">{chg_span(e.get('ret_1m'))}</td>
        <td class="num">{chg_span(e.get('ytd'))}</td></tr>"""

    # Stocks in focus (theme holdings by momentum)
    stocks_html = ""
    if rec.get("stocks_focus"):
        stocks_html += """
        <tr class="hdr"><td>Stock</td><td class="num">Last</td><td class="num">Day</td>
        <td class="num">1M</td><td class="num">vs 52w hi</td></tr>"""
    for s in rec.get("stocks_focus", []):
        stocks_html += f"""
        <tr><td><strong>{s['ticker']}</strong></td>
        <td class="num">{fmt(s['price'])} <span class="ccy">{s.get('ccy','')}</span></td>
        <td class="num">{chg_span(s['change_pct'])}</td>
        <td class="num">{chg_span(s.get('ret_1m'))}</td>
        <td class="num">{chg_span(s.get('from_hi'))}</td></tr>"""

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
        <div class="scroll"><table>{etfs_html}</table></div>
      </div>""" if etfs_html else "")

    stocks_block = (f"""
      <div class="card">
        <h3>Stocks in Focus (from today's themes)</h3>
        <div class="scroll"><table>{stocks_html}</table></div>
        <p class="muted">These are theme-ETF holdings surfaced by today's momentum —
        shown for research, NOT buy recommendations. Speculative themes (e.g. quantum)
        are especially high-risk. Always do your own due diligence.</p>
      </div>""" if stocks_html else "")

    # UCITS / LSE alternatives for the US-listed themes
    ucits_html = ""
    for a in rec.get("ucits_alts", []):
        ucits_html += f"""
        <tr><td><strong>{a['us_ticker']}</strong> <span class="muted">{a['us_name']} (US-listed)</span></td>
        <td><span class="lse">{a['lse_ticker']}</span> <span class="muted">&middot; TER {fmt(a.get('ter'), '%')}</span><br><span class="muted">{a['ucits_name']}</span><br>
        <span class="muted">{a['note']}</span></td></tr>"""
    ucits_block = (f"""
      <div class="card">
        <h3>UCITS / LSE Alternative (Singapore + IBKR friendly)</h3>
        <table class="ucits"><tr><td class="muted">US-listed theme</td><td class="muted">London-listed UCITS to consider</td></tr>{ucits_html}</table>
        <p class="muted">For each US-domiciled theme above, this is the closest
        <strong>London-listed UCITS</strong> equivalent — Irish-domiciled funds pay
        15% (not 30%) US dividend withholding and avoid US estate-tax exposure for a
        Singapore investor on IBKR. Some are imperfect proxies (e.g. there is no pure
        quantum-computing UCITS — AI is the nearest). Check TER, liquidity and tracking
        before buying. Not financial advice.</p>
      </div>""" if ucits_html else "")

    openattr = " open" if open_default else ""

    # Ranked Watchlist (Pro Score) — the Investing.com-Pro+-style composite.
    def score_badge(s):
        cls = ("s-strong" if s >= 70 else "s-solid" if s >= 55
               else "s-fair" if s >= 40 else "s-watch")
        return f'<span class="score {cls}">{s:.0f}</span>'

    def bar(v):
        if v is None:
            return '<span class="muted">—</span>'
        return (f'<span class="mini"><span class="mini-fill" '
                f'style="width:{max(0, min(100, v)):.0f}%"></span></span>')

    scored_html = """
        <tr class="hdr"><td>Fund</td><td class="num">Score</td>
        <td class="num">Tax</td><td class="num">Cost</td><td class="num">Risk-adj</td>
        <td class="num">Mom.</td><td class="num">Liq.</td></tr>"""
    for r in rec.get("scored", []):
        p = r.get("pillars", {})
        scored_html += f"""
        <tr><td><strong>{r['short']}</strong> <span class="muted">{r['ticker']}</span><br>
        <span class="muted">{r.get('verdict','')}</span></td>
        <td class="num">{score_badge(r['pro_score'])}</td>
        <td class="num">{bar(p.get('tax'))}</td>
        <td class="num">{bar(p.get('cost'))}</td>
        <td class="num">{bar(p.get('riskadj'))}</td>
        <td class="num">{bar(p.get('momentum'))}</td>
        <td class="num">{bar(p.get('liquidity'))}</td></tr>"""

    scored_block = (f"""
      <div class="card">
        <h3>Ranked Watchlist &mdash; Pro Score (0&ndash;100)</h3>
        <div class="scroll"><table>{scored_html}</table></div>
        <p class="muted">A rules-based composite scoring each core UCITS on
        <strong>SG tax efficiency (25%)</strong>, cost/TER (20%), risk-adjusted
        return (25%), momentum (15%) and a liquidity proxy (15%). Sub-scores are
        percentile-ranked <em>within this watchlist</em>, so they compare the funds
        against each other, not the whole market. Same-index funds (VWRA/FTAW/ALLW)
        score close together and separate mainly on cost. Decision-support only &mdash;
        <strong>not financial advice</strong>, and no model predicts markets.</p>
      </div>""" if rec.get("scored") else "")

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
      </div>{etfs_block}{stocks_block}{ucits_block}{scored_block}
      <div class="card">
        <h3>Core Watchlist</h3>
        <div class="scroll"><table>{core_html}</table></div>
        <p class="muted">All UCITS, London-listed (.L) — tax/cost-efficient for a
        Singapore investor on IBKR (15% vs 30% US dividend withholding, no US estate
        tax). Ranked by today's momentum. Not financial advice.</p>
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
  /* Horizontal scroll wrapper so wide metric tables stay readable on mobile:
     columns keep their width and you swipe sideways instead of squashing. */
  .scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; }}
  .scroll table {{ min-width:540px; }}
  td {{ padding:8px 6px; border-top:1px solid var(--line); vertical-align:top; }}
  /* First column = fund/ticker name. Give it a sensible min width and let the
     bold name stay on one line while the muted subtitle below may wrap. */
  .scroll td:first-child {{ min-width:170px; }}
  .scroll td:first-child strong {{ white-space:nowrap; }}
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
  .lse {{ color:var(--up); font-weight:600; font-variant-numeric:tabular-nums; }}
  .ucits td {{ vertical-align:top; }}
  .score {{ display:inline-block; min-width:34px; padding:2px 7px; border-radius:6px;
            font-weight:700; font-variant-numeric:tabular-nums; color:#0d1117; }}
  .s-strong {{ background:var(--up); }}
  .s-solid  {{ background:#7ee787; }}
  .s-fair   {{ background:#d29922; color:#0d1117; }}
  .s-watch  {{ background:var(--down); color:#fff; }}
  .mini {{ display:inline-block; width:46px; height:7px; border-radius:4px;
           background:var(--line); overflow:hidden; vertical-align:middle; }}
  .mini-fill {{ display:block; height:100%; background:var(--accent); }}
  tr.hdr td {{ color:var(--muted); font-size:.75rem; text-transform:uppercase;
               letter-spacing:.03em; border-top:none; padding-bottom:4px; }}
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
