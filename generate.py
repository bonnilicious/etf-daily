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
    ("Vanguard FTSE All-World UCITS (VWRA)", "VWRA.L", "One-fund global equity, incl. emerging mkts; largest/most liquid", 0.14, "Acc"),
    ("Invesco FTSE All-World UCITS (FWRA)", "FWRA.L", "USD-quoted FTSE All-World (the USD line of the iShares FTAW index family); cheap all-in-one", 0.15, "Acc"),
    ("Xtrackers FTSE All-World UCITS 1C (ALLW)", "ALLW.L", "Same FTSE All-World index as VWRA, cheapest TER on market", 0.07, "Acc"),
    ("iShares Core MSCI World UCITS (IWDA)", "IWDA.L", "USD-quoted twin of SWDA; developed-world core, deepest AUM/liquidity", 0.20, "Acc"),
    ("State Street SPDR MSCI World UCITS (SWRD)", "SWRD.L", "Cheapest MSCI World developed-world core (USD)", 0.12, "Acc"),
    ("iShares Core MSCI EM IMI UCITS (EIMI)", "EIMI.L", "Broad emerging-market exposure", 0.18, "Acc"),
    ("iShares MSCI World Small Cap UCITS (WSML)", "WSML.L", "Global small-cap tilt / diversifier vs large-cap core (USD)", 0.35, "Acc"),
    ("iShares Edge MSCI World Quality Factor (IWQU)", "IWQU.L", "Quality factor tilt — profitable, low-debt global names (USD)", 0.25, "Acc"),
    ("iShares Edge MSCI World Momentum Factor (IWMO)", "IWMO.L", "Momentum factor tilt for potential upside (USD)", 0.25, "Acc"),
    ("iShares Edge MSCI World Value Factor (IWVL)", "IWVL.L", "Value factor tilt — cheaper valuations, diversifier (USD)", 0.25, "Acc"),
    ("iShares Nasdaq 100 UCITS (CNX1)", "CNX1.L", "US tech/growth tilt, accumulating", 0.33, "Acc"),
    ("iShares MSCI World SRI UCITS (SUWS)", "SUWS.L", "ESG-screened global developed alternative", 0.20, "Acc"),
    ("iShares $ Treasury 7-10y UCITS (IDTM)", "IDTM.L", "US Treasuries, rate-sensitive ballast (Acc)", 0.07, "Acc"),
]

# Same-index groups: funds here track the SAME underlying index, so they are
# largely interchangeable and differ mainly on cost (TER)/liquidity. Shown as a
# small badge so you know which lines are substitutes rather than diversifiers.
INDEX_GROUPS = {
    "VUAA.L": "S&P 500", "SPXP.L": "S&P 500", "CSPX.L": "S&P 500",
    "SWDA.L": "MSCI World", "IWDA.L": "MSCI World", "SWRD.L": "MSCI World",
    "VHVG.L": "FTSE Dev World",
    "VWRA.L": "FTSE All-World", "FWRA.L": "FTSE All-World", "ALLW.L": "FTSE All-World",
}

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


def _fetch_history(ticker):
    """Full-history (range=max, monthly) fetch for a single ticker. Lets us
    compute 6-month & since-inception returns and a 1Y sparkline that the 1y
    daily feed can't provide. Returns {} on failure (caller degrades gracefully)."""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           "?range=max&interval=1mo")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.load(resp)
    res = data["chart"]["result"][0]
    ts = res.get("timestamp", []) or []
    try:
        raw = res["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        raw = []
    series = [(t, c) for t, c in zip(ts, raw) if c is not None]
    if len(series) < 2:
        return {}
    closes = [c for _, c in series]
    price = closes[-1]

    def ret_from(base):
        return (price - base) / base * 100 if (price and base) else None

    # 6-month return: walk back 6 monthly points.
    ret_6m = ret_from(closes[-7]) if len(closes) > 6 else None
    # Since-inception: first available monthly close.
    incep = ret_from(closes[0])
    incep_ts = series[0][0]
    incep_year = datetime.datetime.fromtimestamp(incep_ts, SGT).year
    # Annualised (CAGR) since inception: (end/start)^(1/years) - 1.
    now_ts = series[-1][0]
    years = max((now_ts - incep_ts) / (365.25 * 86400), 0.5)
    cagr = None
    if closes[0] and price and closes[0] > 0:
        cagr = ((price / closes[0]) ** (1.0 / years) - 1.0) * 100
    # ~1Y sparkline: last 13 monthly closes, normalised to a 0-100 y-scale.
    tail = closes[-13:] if len(closes) >= 13 else closes
    lo, hi = min(tail), max(tail)
    rng = (hi - lo) or 1.0
    spark = [round((c - lo) / rng * 100, 1) for c in tail]
    return {"ret_6m": ret_6m, "ret_incep": incep, "incep_year": incep_year,
            "cagr": cagr, "spark": spark}


def fetch_histories(tickers):
    """Batch full-history fetch. Missing/failed tickers simply absent."""
    out = {}
    for tic in tickers:
        try:
            h = _fetch_history(tic)
            if h:
                out[tic] = h
        except (urllib.error.URLError, json.JSONDecodeError, KeyError,
                IndexError, TimeoutError, ValueError) as e:
            print(f"WARN: history fetch failed for {tic}: {e}")
    return out


# Static SGD fallbacks used only if the live FX fetch fails (so the DCA tip is
# never blank). GBp = pence = GBP/100.
FX_FALLBACK = {"USD": 1.35, "GBP": 1.71, "GBp": 0.0171, "EUR": 1.46, "SGD": 1.0}


def fetch_fx_to_sgd():
    """Live FX -> SGD for the DCA 'shares per S$1,000' hint. Uses Yahoo FX
    pairs (e.g. USDSGD=X). Falls back to static rates per-currency on failure."""
    rates = dict(FX_FALLBACK)
    pairs = {"USD": "USDSGD=X", "GBP": "GBPSGD=X", "EUR": "EURSGD=X"}
    for ccy, sym in pairs.items():
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
               "?range=5d&interval=1d")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.load(resp)
            px = data["chart"]["result"][0]["meta"].get("regularMarketPrice")
            if px:
                rates[ccy] = px
        except (urllib.error.URLError, json.JSONDecodeError, KeyError,
                IndexError, TimeoutError) as e:
            print(f"WARN: FX fetch failed for {sym}: {e}")
    # GBp (pence) is GBP/100.
    rates["GBp"] = rates.get("GBP", FX_FALLBACK["GBP"]) / 100.0
    rates["SGD"] = 1.0
    return rates


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


def _is_not_gbp(ccy):
    """True if the quote currency is NOT sterling. Drops both GBP (pounds) and
    GBp (pence). A missing/blank currency (feed miss) is kept rather than
    silently dropped, so a transient fetch gap doesn't erase a fund."""
    if not ccy:
        return True
    return ccy.strip().upper() != "GBP"


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
    for tic, r in keyed:
        r["sharpe_like"] = sharpe_like(r)   # raw ratio for display
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
    # UCITS/LSE alternative tickers for today's themes (fetch quotes for them
    # too, so the alternatives table can show live price/returns + a popup).
    alt_tickers = []
    for tt in theme_tickers:
        alt = UCITS_ALTERNATIVES.get(tt)
        if alt and alt[1] not in alt_tickers:
            alt_tickers.append(alt[1])
    if alt_tickers:
        quotes.update(fetch_quotes(alt_tickers))
    # Extended full-history (range=max) for EVERY ticker we display in a table
    # with a click popup — core watchlist, themed ETFs, stocks in focus and the
    # UCITS/LSE alternatives — so each popup has 6-month & since-inception
    # returns, a CAGR and a 1Y sparkline. Missing/failed tickers degrade
    # gracefully (popup simply omits those rows).
    hist_tickers = list(dict.fromkeys(
        core_tickers + theme_tickers + stock_candidates + alt_tickers))
    histories = fetch_histories(hist_tickers)
    # Live FX -> SGD for the DCA "shares per S$1,000" hint.
    fx = fetch_fx_to_sgd()

    core_rows = []
    for name, tic, why, ter, dist in CORE_ETFS:
        q = quotes.get(tic, {})
        h = histories.get(tic, {})
        core_rows.append({"name": name, "short": short_name(name), "ticker": tic,
                          "why": why, "ter": ter, "dist": dist,
                          "price": q.get("price"), "change_pct": q.get("change_pct"),
                          "ccy": q.get("currency"), "ytd": q.get("ytd"),
                          "ret_1m": q.get("ret_1m"), "ret_3m": q.get("ret_3m"),
                          "ret_1y": q.get("ret_1y"), "vol": q.get("vol"),
                          "hi52": q.get("hi52"), "lo52": q.get("lo52"),
                          "from_hi": q.get("from_hi"),
                          "ret_6m": h.get("ret_6m"), "ret_incep": h.get("ret_incep"),
                          "incep_year": h.get("incep_year"), "cagr": h.get("cagr"),
                          "spark": h.get("spark"),
                          "index_group": INDEX_GROUPS.get(tic)})
    # Remove GBP-quoted lines per user preference: keep only funds/stocks the
    # live feed reports in a non-GBP currency (USD/EUR/etc.). Covers both GBP
    # (pounds) and GBp (pence). A row with no currency yet (feed miss) is kept.
    core_rows = [r for r in core_rows if _is_not_gbp(r.get("ccy"))]
    # Core Watchlist display order: sort by TER, lowest to highest (cheapest
    # first). None TERs sort last.
    core_rows.sort(key=lambda r: (r.get("ter") is None, r.get("ter") or 999))

    # Pro Score: rank the core watchlist by the composite 0-100 model. Uses a
    # copy so the day-momentum ordering of `core` (above) is preserved.
    # Per user preference, HIDE anything scoring below 50 (keep the shortlist to
    # genuinely strong/solid candidates only).
    scored_rows = [r for r in score_etfs([dict(r) for r in core_rows])
                   if r.get("pro_score") is not None and r["pro_score"] >= 50]

    themed_rows = []
    for name, tic, blurb, holdings in themes:
        q = quotes.get(tic, {})
        h = histories.get(tic, {})
        themed_rows.append({"name": name, "short": short_name(name), "ticker": tic,
                            "blurb": blurb, "holdings": holdings,
                            "price": q.get("price"), "change_pct": q.get("change_pct"),
                            "ccy": q.get("currency"), "ytd": q.get("ytd"),
                            "ret_1m": q.get("ret_1m"), "ret_3m": q.get("ret_3m"),
                            "ret_1y": q.get("ret_1y"), "vol": q.get("vol"),
                            "hi52": q.get("hi52"), "lo52": q.get("lo52"),
                            "from_hi": q.get("from_hi"), "dist": "—", "ter": None,
                            "ret_6m": h.get("ret_6m"), "ret_incep": h.get("ret_incep"),
                            "incep_year": h.get("incep_year"), "cagr": h.get("cagr"),
                            "spark": h.get("spark"),
                            "index_group": INDEX_GROUPS.get(tic)})
    themed_rows = [r for r in themed_rows if _is_not_gbp(r.get("ccy"))]

    # ETFs in focus: top 5 by today's momentum across core + themed.
    etf_pool = core_rows + themed_rows
    etfs_focus = sorted([e for e in etf_pool if e["change_pct"] is not None],
                        key=lambda e: e["change_pct"], reverse=True)[:5]

    # Stocks in focus: theme holdings, ranked by today's momentum (top 5).
    stock_rows = []
    for tic in stock_candidates:
        q = quotes.get(tic, {})
        h = histories.get(tic, {})
        if q.get("change_pct") is not None:
            stock_rows.append({"ticker": tic, "short": tic,
                               "name": q.get("name") or tic,
                               "price": q.get("price"),
                               "change_pct": q.get("change_pct"), "ccy": q.get("currency"),
                               "ytd": q.get("ytd"),
                               "ret_1m": q.get("ret_1m"), "ret_3m": q.get("ret_3m"),
                               "ret_1y": q.get("ret_1y"), "vol": q.get("vol"),
                               "hi52": q.get("hi52"), "lo52": q.get("lo52"),
                               "from_hi": q.get("from_hi"), "dist": "—", "ter": None,
                               "ret_6m": h.get("ret_6m"), "ret_incep": h.get("ret_incep"),
                               "incep_year": h.get("incep_year"), "cagr": h.get("cagr"),
                               "spark": h.get("spark"), "index_group": None})
    stock_rows = [s for s in stock_rows if _is_not_gbp(s.get("ccy"))]
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
            lse = alt[1]
            q = quotes.get(lse, {})
            h = histories.get(lse, {})
            ucits_alts.append({"us_ticker": t["ticker"], "us_name": t["short"],
                               "ucits_name": alt[0], "lse_ticker": lse,
                               "note": alt[2], "ter": alt[3],
                               # fields for the sortable table + click popup
                               "ticker": lse, "short": lse, "name": alt[0],
                               "dist": "Acc", "index_group": None,
                               "price": q.get("price"), "change_pct": q.get("change_pct"),
                               "ccy": q.get("currency"), "ytd": q.get("ytd"),
                               "ret_1m": q.get("ret_1m"), "ret_3m": q.get("ret_3m"),
                               "ret_1y": q.get("ret_1y"), "vol": q.get("vol"),
                               "hi52": q.get("hi52"), "lo52": q.get("lo52"),
                               "from_hi": q.get("from_hi"),
                               "ret_6m": h.get("ret_6m"), "ret_incep": h.get("ret_incep"),
                               "incep_year": h.get("incep_year"), "cagr": h.get("cagr"),
                               "spark": h.get("spark")})
    ucits_alts = [a for a in ucits_alts if _is_not_gbp(a.get("ccy"))]

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
        "fx": fx,
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


def _pop_payload(r, fx=None):
    """Build the per-fund JS payload consumed by the click/tap popup."""
    fx = fx or FX_FALLBACK
    price, ccy = r.get("price"), (r.get("ccy") or "")
    dca = None
    rate = fx.get(ccy)
    if price and rate:
        shares = 1000.0 / (price * rate)
        dca = f"≈ S$1,000 buys ~{shares:.1f} shares at today's price."
    incep_lbl = "Since inception"
    if r.get("incep_year"):
        incep_lbl = f"Since inception ({r['incep_year']})"
    rng = None
    if r.get("lo52") is not None and r.get("hi52") is not None:
        fh = r.get("from_hi")
        fh_txt = f" · {abs(fh):.1f}% below high" if fh is not None else ""
        rng = f"52-week range: {r['lo52']:.2f} – {r['hi52']:.2f} {ccy}{fh_txt}"
    cagr = r.get("cagr")
    cagr_txt = (f"Annualised since inception (CAGR): {cagr:+.1f}% / yr."
                if cagr is not None else None)
    # Header line: ticker + last price, then Acc/Dist + TER only when meaningful
    # (stocks have neither, so we skip the trailing '· — · TER —').
    tk = f"{r.get('ticker','')} · Last {fmt(price)} {ccy}"
    dist = r.get("dist", "")
    if dist and dist != "—":
        tk += f" · {dist}"
    if r.get("ter") is not None:
        tk += f" · TER {fmt(r.get('ter'), '%')}"
    return {
        "nm": r.get("name", r.get("short", "")),
        "tk": tk,
        "grp": r.get("index_group"),
        "r": [
            ["1 Month", r.get("ret_1m")], ["3 Months", r.get("ret_3m")],
            ["6 Months", r.get("ret_6m")], ["12 Months", r.get("ret_1y")],
            ["YTD", r.get("ytd")], [incep_lbl, r.get("ret_incep")],
        ],
        "spark": r.get("spark") or [],
        "rng": rng, "cagr": cagr_txt, "dca": dca,
    }


def render_day(rec, open_default=False):
    def chg_span(c):
        cls = "up" if (c or 0) >= 0 else "down"
        arrow = "&#9650;" if (c or 0) >= 0 else "&#9660;"
        return f'<span class="{cls}">{arrow} {fmt(c, "%")}</span>'

    # Collect popup payloads for this day, keyed date+ticker so days don't clash.
    payloads = {}

    def pop_key(r):
        k = f"{rec['date']}::{r.get('ticker','')}"
        payloads[k] = _pop_payload(r, rec.get("fx"))
        return k

    def fund_link(r, label):
        k = pop_key(r)
        return (f'<span class="lnk" role="button" tabindex="0" '
                f'onclick="pop(this)" onkeydown="if(event.key==\'Enter\')pop(this)" '
                f'data-k="{k}">{label}</span>')

    def grp_badge(r):
        g = r.get("index_group")
        return (f' <span class="grp" title="Same index as other funds tagged '
                f'{g} — interchangeable, differ mainly on cost">{g}</span>'
                if g else "")

    core_html = ""  # Core Watchlist merged into the unified Watchlist below.

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

    # ETFs in focus (top momentum) — sortable + click-for-popup, matching the
    # Ranked Watchlist treatment.
    def _chgv(c):
        return c if c is not None else -1e9

    etfs_html = ""
    if rec.get("etfs_focus"):
        etfs_html += """
        <tr class="hdr"><td data-c="0" data-t="s">ETF</td>
        <td class="num sortable" data-c="1" data-t="n">Last</td>
        <td class="num sortable" data-c="2" data-t="n">Day</td>
        <td class="num sortable" data-c="3" data-t="n">1M</td>
        <td class="num sortable" data-c="4" data-t="n">YTD</td></tr>"""
    for e in rec.get("etfs_focus", []):
        nm = f"<strong>{e['short']}</strong> <span class=\"muted\">{e.get('ticker','')}</span>"
        etfs_html += f"""
        <tr><td class="fund" data-v="{e['short']}">{fund_link(e, nm)}{grp_badge(e)}</td>
        <td class="num" data-v="{e.get('price') or -999}">{fmt(e['price'])} <span class="ccy">{e.get('ccy','')}</span></td>
        <td class="num" data-v="{_chgv(e.get('change_pct'))}">{chg_span(e['change_pct'])}</td>
        <td class="num" data-v="{_chgv(e.get('ret_1m'))}">{chg_span(e.get('ret_1m'))}</td>
        <td class="num" data-v="{_chgv(e.get('ytd'))}">{chg_span(e.get('ytd'))}</td></tr>"""

    # Stocks in focus (theme holdings by momentum) — sortable + click-for-popup.
    stocks_html = ""
    if rec.get("stocks_focus"):
        stocks_html += """
        <tr class="hdr"><td data-c="0" data-t="s">Stock</td>
        <td class="num sortable" data-c="1" data-t="n">Last</td>
        <td class="num sortable" data-c="2" data-t="n">Day</td>
        <td class="num sortable" data-c="3" data-t="n">1M</td>
        <td class="num sortable" data-c="4" data-t="n">vs 52w hi</td></tr>"""
    for s in rec.get("stocks_focus", []):
        nm = f"<strong>{s['ticker']}</strong>"
        stocks_html += f"""
        <tr><td class="fund" data-v="{s['ticker']}">{fund_link(s, nm)}</td>
        <td class="num" data-v="{s.get('price') or -999}">{fmt(s['price'])} <span class="ccy">{s.get('ccy','')}</span></td>
        <td class="num" data-v="{_chgv(s.get('change_pct'))}">{chg_span(s['change_pct'])}</td>
        <td class="num" data-v="{_chgv(s.get('ret_1m'))}">{chg_span(s.get('ret_1m'))}</td>
        <td class="num" data-v="{_chgv(s.get('from_hi'))}">{chg_span(s.get('from_hi'))}</td></tr>"""

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
        <div class="scroll"><table class="sortable-tbl" data-tid="{rec['date']}-etf">{etfs_html}</table></div>
        <p class="muted">Click / tap any name for its full return breakdown &amp; sparkline;
        click any underlined column header to sort. Not financial advice.</p>
      </div>""" if etfs_html else "")

    stocks_block = (f"""
      <div class="card">
        <h3>Stocks in Focus (from today's themes)</h3>
        <div class="scroll"><table class="sortable-tbl" data-tid="{rec['date']}-stk">{stocks_html}</table></div>
        <p class="muted">These are theme-ETF holdings surfaced by today's momentum —
        shown for research, NOT buy recommendations. Click / tap a name for its return
        breakdown; click a header to sort. Speculative themes (e.g. quantum)
        are especially high-risk. Always do your own due diligence.</p>
      </div>""" if stocks_html else "")

    # UCITS / LSE alternatives for the US-listed themes — sortable + click popup,
    # now showing the London-listed UCITS's live price/returns alongside the
    # US theme it replaces.
    ucits_html = ""
    if rec.get("ucits_alts"):
        ucits_html += """
        <tr class="hdr"><td data-c="0" data-t="s">London UCITS (replaces US theme)</td>
        <td class="num sortable" data-c="1" data-t="n">TER</td>
        <td class="num sortable" data-c="2" data-t="n">Last</td>
        <td class="num sortable" data-c="3" data-t="n">Day</td>
        <td class="num sortable" data-c="4" data-t="n">YTD</td>
        <td class="num sortable" data-c="5" data-t="n">1Y</td></tr>"""
    for a in rec.get("ucits_alts", []):
        ter = a.get("ter")
        ter_cell = (f'<span data-v="{ter}">{ter:.2f}%</span>' if ter is not None
                    else '<span class="muted" data-v="999">—</span>')
        nm = (f"<span class=\"lse\">{a['lse_ticker']}</span> "
              f"<span class=\"muted\">&larr; {a['us_ticker']} (US)</span>")
        ucits_html += f"""
        <tr><td class="fund" data-v="{a['lse_ticker']}">{fund_link(a, nm)}<br>
        <span class="muted">{a['ucits_name']}</span><br>
        <span class="muted">{a['note']}</span></td>
        <td class="num" data-v="{ter if ter is not None else 999}">{ter_cell}</td>
        <td class="num" data-v="{a.get('price') or -999}">{fmt(a.get('price'))} <span class="ccy">{a.get('ccy','')}</span></td>
        <td class="num" data-v="{_chgv(a.get('change_pct'))}">{chg_span(a.get('change_pct'))}</td>
        <td class="num" data-v="{_chgv(a.get('ytd'))}">{chg_span(a.get('ytd'))}</td>
        <td class="num" data-v="{_chgv(a.get('ret_1y'))}">{chg_span(a.get('ret_1y'))}</td></tr>"""
    ucits_block = (f"""
      <div class="card">
        <h3>UCITS / LSE Alternative (Singapore + IBKR friendly)</h3>
        <div class="scroll"><table class="sortable-tbl ucits" data-tid="{rec['date']}-ucits">{ucits_html}</table></div>
        <p class="muted">For each US-domiciled theme today, this is the closest
        <strong>London-listed UCITS</strong> equivalent — Irish-domiciled funds pay
        15% (not 30%) US dividend withholding and avoid US estate-tax exposure for a
        Singapore investor on IBKR. Click / tap a name for its return breakdown;
        click a header to sort. Some are imperfect proxies (e.g. there is no pure
        quantum-computing UCITS — AI is the nearest). Check TER, liquidity and tracking
        before buying. Not financial advice.</p>
      </div>""" if ucits_html else "")

    openattr = " open" if open_default else ""

    # Ranked Watchlist (Pro Score) — the Investing.com-Pro+-style composite.
    def score_badge(s):
        cls = ("s-strong" if s >= 70 else "s-solid" if s >= 55
               else "s-fair" if s >= 40 else "s-watch")
        return f'<span class="score {cls}">{s:.0f}</span>'

    def _pct(v, plus=False):
        """Format a raw percentage value (already in %)."""
        if v is None:
            return '<span class="muted">—</span>'
        sign = "+" if (plus and v >= 0) else ""
        cls = "" if not plus else (' class="pos"' if v >= 0 else ' class="neg"')
        return f'<span{cls}>{sign}{v:.1f}%</span>'

    def _tax_cell(r):
        d = r.get("dist", "")
        label = {"Acc": "Acc", "Dist": "Dist"}.get(d, d or "—")
        return f'<span>{label}</span>'

    def _ratio(v):
        if v is None:
            return '<span class="muted">—</span>'
        cls = ' class="pos"' if v >= 0 else ' class="neg"'
        return f'<span{cls}>{v:.2f}</span>'

    # --- Unified Watchlist: Core metrics + Ranked (Pro Score) metrics merged
    # into ONE table. Columns are tagged into two groups — "rank" (scoring
    # model) and "watch" (day-to-day price action) — each toggle-able via a
    # button so the user can show/hide either metric set. Fund / Score / Last
    # are always visible. data-c indices are contiguous for the sort JS. ---
    unified_html = """
        <tr class="hdr">
        <td data-c="0" data-t="s">Fund</td>
        <td class="ctr sortable col-rank" data-c="1" data-t="n">Score</td>
        <td class="num sortable" data-c="2" data-t="n">Last</td>
        <td class="ctr col-rank" data-c="3">Tax</td>
        <td class="num sortable col-rank" data-c="4" data-t="n">TER</td>
        <td class="num sortable col-rank" data-c="5" data-t="n">Risk-adj (1Y/vol)</td>
        <td class="num sortable col-rank" data-c="6" data-t="n">Momentum (1Y)</td>
        <td class="num sortable col-rank" data-c="7" data-t="n">Volatility</td>
        <td class="num sortable col-watch" data-c="8" data-t="n">Day</td>
        <td class="num sortable col-watch" data-c="9" data-t="n">YTD</td>
        <td class="num sortable col-watch" data-c="10" data-t="n">6M</td></tr>"""
    for r in rec.get("scored", []):
        ter = r.get("ter")
        ter_cell = (f'<span data-v="{ter}">{ter:.2f}%</span>' if ter is not None
                    else '<span class="muted" data-v="-999">—</span>')
        name_lbl = (f"<strong>{r['short']}</strong> "
                    f"<span class=\"muted\">{r['ticker']}</span>")
        last_cell = (f"{fmt(r.get('price'))} <span class=\"ccy\">{r.get('ccy','')}</span>"
                     if r.get('price') is not None else '<span class="muted">—</span>')
        sl = r.get('sharpe_like'); r1y = r.get('ret_1y'); vol = r.get('vol')
        day = r.get('change_pct'); ytd = r.get('ytd'); r6m = r.get('ret_6m')
        unified_html += f"""
        <tr><td class="fund" data-v="{r['short']}">{fund_link(r, name_lbl)}{grp_badge(r)}<br>
        <span class="muted">{r.get('verdict','')} · {r.get('why','')}</span></td>
        <td class="ctr col-rank" data-v="{r['pro_score']}">{score_badge(r['pro_score'])}</td>
        <td class="num" data-v="{r.get('price') or -999}">{last_cell}</td>
        <td class="ctr col-rank">{_tax_cell(r)}</td>
        <td class="num col-rank" data-v="{ter if ter is not None else 999}">{ter_cell}</td>
        <td class="num col-rank" data-v="{sl if sl is not None else -999}">{_ratio(sl)}</td>
        <td class="num col-rank" data-v="{r1y if r1y is not None else -999}">{_pct(r1y, plus=True)}</td>
        <td class="num col-rank" data-v="{vol if vol is not None else 999}">{_pct(vol)}</td>
        <td class="num col-watch" data-v="{day if day is not None else -1e9}">{chg_span(day)}</td>
        <td class="num col-watch" data-v="{ytd if ytd is not None else -1e9}">{chg_span(ytd)}</td>
        <td class="num col-watch" data-v="{r6m if r6m is not None else -1e9}">{chg_span(r6m)}</td></tr>"""

    tid = rec['date']
    scored_block = (f"""
      <div class="card">
        <h3>Watchlist &mdash; Pro Score + live metrics</h3>
        <div class="toggles">
          <span class="muted" style="margin-right:4px">Show:</span>
          <button class="tgl on" data-grp="rank" data-tid="{tid}">Ranking metrics</button>
          <button class="tgl on" data-grp="watch" data-tid="{tid}">Watchlist metrics</button>
        </div>
        <div class="scroll"><table class="sortable-tbl" data-tid="{tid}">{unified_html}</table></div>
        <p class="muted">One unified table combining the <strong>Pro Score ranking
        model</strong> with the day-to-day <strong>watchlist metrics</strong>. Use the
        buttons above to show/hide each set. <em>Ranking metrics</em> — Score (weighted
        0&ndash;100 composite: SG tax 25%, cost/TER 20%, risk-adjusted return 25%,
        momentum 15%, liquidity 15%), Tax (Acc/Dist), TER, Risk-adj (1Y return &divide;
        annualised volatility, higher is better) and Volatility. <em>Watchlist metrics</em>
        — Day / YTD / 6-month price change. All rows are UCITS, London-listed, USD-quoted
        (GBP lines removed), tax/cost-efficient for a Singapore IBKR investor (15% vs 30%
        US dividend withholding, no US estate tax). Anything scoring below 50 is hidden.
        <strong>Click any underlined header to sort; click a fund name for its full
        breakdown &amp; DCA hint.</strong> Same-index badges (e.g.
        <span class="grp">FTSE All-World</span>) mark interchangeable substitutes that
        differ mainly on cost. Decision-support only &mdash;
        <strong>not financial advice</strong>.</p>
      </div>""" if rec.get("scored") else "")

    return (f"""
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
        <h3>Themed ETFs &amp; Tickers Today</h3>
        {themed_html}
        <p class="muted">Holdings shown for context, not individual buy advice.
        Niche themes are higher-risk satellites — size them small vs. your core.</p>
      </div>
    </div>
  </details>""", payloads)


def render_page(records):
    # records: list sorted newest-first
    days_html = ""
    all_payloads = {}
    for i, r in enumerate(records):
        html, payloads = render_day(r, open_default=(i == 0))
        days_html += html
        all_payloads.update(payloads)
    payloads_json = json.dumps(all_payloads, ensure_ascii=False)
    latest_refresh = records[0]["refreshed"] if records else "—"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Stock Market News</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>%F0%9F%92%B0</text></svg>">
<style>
  :root {{ --bg:#0d1117; --card:#161b22; --line:#30363d; --txt:#e6edf3;
           --muted:#8b949e; --up:#3fb950; --down:#f85149; --accent:#58a6ff;
           --rowhi:#1c2430; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
          background:var(--bg); color:var(--txt); line-height:1.5; }}
  /* Desktop: use (almost) the full browser width so data tables get room to
     breathe instead of a narrow centred column. Fluid width with a generous
     cap and side gutters; collapses to tighter padding on small screens. */
  .wrap {{ width:100%; max-width:1600px; margin:0 auto; padding:24px 40px 60px; }}
  @media (max-width: 640px) {{
    /* "Zoom out" on phones: shrink the root font so every rem-based size
       (text, padding, rows, badges) scales down proportionally — more fits
       on screen at a glance without changing the layout. */
    html {{ font-size:13px; }}
    .wrap {{ padding:20px 14px 48px; }}
  }}
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
  .card {{ border-top:1px solid var(--line); padding:16px 0; }}
  h3 {{ font-size:1rem; margin:0 0 12px; color:var(--accent); }}
  /* --- Clean, aligned data grid --- */
  table {{ width:100%; border-collapse:collapse; }}
  td {{ padding:11px 14px; border-bottom:1px solid var(--line); vertical-align:middle; }}
  tr:first-child td {{ border-top:none; }}
  /* zebra striping + hover for scannability (skip the header row) */
  tbody-none {{}}
  table tr:nth-child(odd):not(.hdr) td {{ background:rgba(255,255,255,.015); }}
  table tr:not(.hdr):hover td {{ background:var(--rowhi); }}
  tr.hdr td {{ color:var(--muted); font-size:.72rem; text-transform:uppercase;
               letter-spacing:.04em; border-top:none; border-bottom:1px solid var(--line);
               padding-bottom:8px; font-weight:600; }}
  /* Numeric + label columns are CENTER-aligned so the header text sits directly
     over its figures (previously right-flushed, which looked ragged vs. the
     centred headers). Both .num and .ctr now center; header cells match. */
  .num {{ text-align:center; white-space:nowrap; font-variant-numeric:tabular-nums; }}
  .ctr {{ text-align:center; white-space:nowrap; font-variant-numeric:tabular-nums; }}
  tr.hdr td.num, tr.hdr td.ctr {{ text-align:center; }}
  /* Fund/name column: sensible min width; bold name on one line. */
  td.fund {{ text-align:left; min-width:190px; }}
  td.fund strong {{ white-space:nowrap; }}
  /* Horizontal scroll whenever the table is wider than its container (e.g. the
     unified Watchlist with BOTH metric groups shown) so the last column is
     never clipped. Padding-bottom leaves room for the scrollbar. On mobile the
     fund column also freezes so the name stays visible while swiping. */
  .scroll {{ overflow-x:auto; -webkit-overflow-scrolling:touch; padding-bottom:2px; }}
  @media (max-width:760px) {{
    .scroll table {{ min-width:40rem; }}
    td.fund {{ position:sticky; left:0; background:var(--card);
               box-shadow:2px 0 0 var(--line); }}
    table tr:nth-child(odd):not(.hdr) td.fund {{ background:var(--card); }}
  }}
  .up {{ color:var(--up); }} .down {{ color:var(--down); }}
  .pos {{ color:var(--up); font-variant-numeric:tabular-nums; }}
  .neg {{ color:var(--down); font-variant-numeric:tabular-nums; }}
  .muted {{ color:var(--muted); font-size:.85rem; }}
  .ccy {{ color:var(--muted); font-size:.8rem; }}
  /* clickable fund name -> popup */
  .lnk {{ cursor:pointer; border-bottom:1px dashed var(--muted); }}
  .lnk:hover, .lnk:focus {{ color:var(--accent); border-color:var(--accent); outline:none; }}
  /* same-index badge */
  .grp {{ display:inline-block; font-size:.68rem; padding:1px 7px; border-radius:20px;
         background:rgba(88,166,255,.14); color:var(--accent); border:1px solid rgba(88,166,255,.35);
         vertical-align:middle; white-space:nowrap; }}
  /* sortable header */
  .sortable {{ cursor:pointer; user-select:none; }}
  .sortable:hover {{ color:var(--accent); }}
  .sortable::after {{ content:" \\2195"; opacity:.45; }}
  .sortable.asc::after {{ content:" \\2191"; opacity:1; color:var(--accent); }}
  .sortable.desc::after {{ content:" \\2193"; opacity:1; color:var(--accent); }}
  /* metric-group toggle buttons + column show/hide */
  .toggles {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin:0 0 12px; }}
  .tgl {{ cursor:pointer; font-size:.8rem; padding:4px 12px; border-radius:20px;
         background:transparent; color:var(--muted); border:1px solid var(--line);
         font-family:inherit; }}
  .tgl:hover {{ color:var(--txt); border-color:var(--muted); }}
  .tgl.on {{ background:rgba(88,166,255,.14); color:var(--accent);
            border-color:rgba(88,166,255,.45); }}
  table.hide-rank .col-rank {{ display:none; }}
  table.hide-watch .col-watch {{ display:none; }}
  .pick {{ border-left:3px solid var(--accent); padding-left:12px; }}
  .theme {{ border-left:3px solid var(--line); padding-left:12px; margin-bottom:12px; }}
  .theme-head {{ display:flex; justify-content:space-between; gap:10px; }}
  .news {{ margin:0; padding-left:18px; }}
  .news li {{ margin-bottom:7px; }}
  .news a {{ color:var(--accent); text-decoration:none; }}
  .news a:hover {{ text-decoration:underline; }}
  .lse {{ color:var(--up); font-weight:600; font-variant-numeric:tabular-nums; }}
  .ucits td.fund {{ vertical-align:top; }}
  .score {{ display:inline-block; min-width:32px; padding:3px 8px; border-radius:7px;
            font-weight:700; font-variant-numeric:tabular-nums; color:#0d1117;
            text-align:center; }}
  .s-strong {{ background:var(--up); }}
  .s-solid  {{ background:#7ee787; }}
  .s-fair   {{ background:#d29922; color:#0d1117; }}
  .s-watch  {{ background:var(--down); color:#fff; }}
  footer {{ color:var(--muted); font-size:.78rem; margin-top:28px; }}
  /* --- popup / modal --- */
  .ov {{ position:fixed; inset:0; background:rgba(0,0,0,.62); display:none;
        align-items:center; justify-content:center; padding:20px; z-index:50; }}
  .ov.on {{ display:flex; }}
  .modal {{ background:var(--card); border:1px solid var(--line); border-radius:14px;
           max-width:470px; width:100%; padding:22px; position:relative; }}
  .modal h4 {{ margin:0 0 2px; font-size:1.15rem; }}
  .modal .tk2 {{ color:var(--muted); font-size:.85rem; margin-bottom:14px; }}
  .modal .x {{ position:absolute; top:12px; right:16px; cursor:pointer;
              color:var(--muted); font-size:1.4rem; line-height:1; background:none;
              border:none; }}
  .grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px 12px; margin:6px 0 14px; }}
  .cell {{ background:var(--bg); border:1px solid var(--line); border-radius:9px;
          padding:9px 12px; }}
  .cell .lab {{ color:var(--muted); font-size:.7rem; text-transform:uppercase;
               letter-spacing:.04em; }}
  .cell .val {{ font-size:1.1rem; font-weight:700; font-variant-numeric:tabular-nums; }}
  .foot {{ color:var(--muted); font-size:.78rem; margin-top:6px; }}
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

<!-- fund detail popup -->
<div class="ov" id="ov" onclick="if(event.target===this)closePop()">
  <div class="modal" role="dialog" aria-modal="true">
    <button class="x" onclick="closePop()" aria-label="Close">&times;</button>
    <h4 id="m-nm"></h4>
    <div class="tk2" id="m-tk"></div>
    <div id="m-grp" style="margin:-6px 0 12px"></div>
    <div class="grid" id="m-grid"></div>
    <svg id="m-spark" width="100%" height="46" viewBox="0 0 400 46" preserveAspectRatio="none" style="margin:2px 0"></svg>
    <div class="foot" id="m-rng"></div>
    <div class="foot" id="m-cagr" style="margin-top:6px"></div>
    <div class="foot" id="m-dca" style="margin-top:6px"></div>
  </div>
</div>

<script>
  var POP = {payloads_json};
  function fnum(v) {{
    if (v === null || v === undefined) return '&mdash;';
    var s = (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
    return '<span class="' + (v >= 0 ? 'pos' : 'neg') + '">' + s + '</span>';
  }}
  function pop(el) {{
    var d = POP[el.getAttribute('data-k')];
    if (!d) return;
    document.getElementById('m-nm').textContent = d.nm;
    document.getElementById('m-tk').textContent = d.tk;
    var g = document.getElementById('m-grid'); g.innerHTML = '';
    d.r.forEach(function(row) {{
      g.innerHTML += '<div class="cell"><div class="lab">' + row[0] +
        '</div><div class="val">' + fnum(row[1]) + '</div></div>';
    }});
    // sparkline
    var sv = document.getElementById('m-spark');
    if (d.spark && d.spark.length > 1) {{
      var n = d.spark.length, pts = d.spark.map(function(y, i) {{
        var x = i / (n - 1) * 400;
        var yy = 44 - (y / 100 * 40) - 2;   // invert; 0-100 -> 44..2
        return x.toFixed(1) + ',' + yy.toFixed(1);
      }}).join(' ');
      var rising = d.spark[n - 1] >= d.spark[0];
      sv.innerHTML = '<polyline fill="none" stroke="' +
        (rising ? '#3fb950' : '#f85149') + '" stroke-width="2" points="' + pts + '"/>';
      sv.style.display = '';
    }} else {{ sv.style.display = 'none'; }}
    document.getElementById('m-rng').textContent = d.rng || '';
    var gp = document.getElementById('m-grp');
    gp.innerHTML = d.grp ? '<span class="grp">Same index: ' + d.grp +
      '</span> <span class="muted">— interchangeable with other ' + d.grp +
      ' funds; choose on cost.</span>' : '';
    document.getElementById('m-cagr').textContent = d.cagr || '';
    document.getElementById('m-dca').innerHTML = d.dca
      ? d.dca + ' <span class="muted">(live FX, illustrative)</span>' : '';
    document.getElementById('ov').classList.add('on');
  }}
  function closePop() {{ document.getElementById('ov').classList.remove('on'); }}
  document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') closePop();
  }});

  // --- Sortable Ranked Watchlist tables ---
  document.querySelectorAll('table.sortable-tbl').forEach(function(tbl) {{
    var hdr = tbl.querySelector('tr.hdr');
    tbl.querySelectorAll('td.sortable').forEach(function(th) {{
      th.addEventListener('click', function() {{
        var col = +th.getAttribute('data-c');
        var asc = !th.classList.contains('asc');
        hdr.querySelectorAll('td').forEach(function(x) {{ x.classList.remove('asc','desc'); }});
        th.classList.add(asc ? 'asc' : 'desc');
        var rows = Array.prototype.slice.call(tbl.querySelectorAll('tr')).filter(function(r) {{
          return !r.classList.contains('hdr');
        }});
        rows.sort(function(a, b) {{
          var av = parseFloat(a.children[col].getAttribute('data-v'));
          var bv = parseFloat(b.children[col].getAttribute('data-v'));
          if (isNaN(av)) av = -1e9; if (isNaN(bv)) bv = -1e9;
          return asc ? av - bv : bv - av;
        }});
        rows.forEach(function(r) {{ tbl.appendChild(r); }});
      }});
    }});
  }});

  // --- Metric-group toggles (show/hide the "rank" vs "watch" column sets) ---
  document.querySelectorAll('button.tgl').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      var grp = btn.getAttribute('data-grp');          // 'rank' | 'watch'
      var tid = btn.getAttribute('data-tid');
      var tbl = document.querySelector('table.sortable-tbl[data-tid="' + tid + '"]');
      if (!tbl) return;
      var on = btn.classList.toggle('on');
      tbl.classList.toggle('hide-' + grp, !on);
    }});
  }});
</script>
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
