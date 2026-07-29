"""Market-breadth regime filter — net new highs across a symbol universe.

Breadth here is the classic new-highs-minus-new-lows count, computed over a
*coherent* universe (US single-name stocks, which share market hours and move
together) rather than the whole mixed fleet. At each timestamp it is:

    breadth(t) = (# symbols making a new `lookback`-bar high at t)
               - (# symbols making a new `lookback`-bar low at t)

Used as a regime gate (see breadth_blocks): only go long when the group is
broadly making new highs, only short when broadly making new lows. The series
is built once from every universe CSV and injected into each symbol's backtest
(run_backtest's breadth arg) — it is cross-sectional, so it cannot be derived
from a single symbol's data the way an indicator column can.

No look-ahead: a new high at bar t compares t's high against the prior
`lookback` bars (shift(1)); every symbol's contribution at t is its own closed
bar at t, and the strategy acts on that same closed bar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# US single-name stocks, as (canonical, *aliases) rows. Brokers disagree on
# naming — Vantage lists "NVIDIA" where others list "NVDA" — so every spelling
# of one company maps to a single canonical key and can never be counted twice
# in the tally. Indices, FX, crypto and commodities are deliberately excluded:
# breadth is only meaningful within one coherent, co-trading universe.
#
# Single-letter tickers (C, V, T, F, D, K, O, X) are deliberately omitted: an
# exact match on a one-character symbol is too easy to collide with a broker's
# internal instrument naming, and a false positive would spawn a live trading
# config on an unintended instrument. `scan_universe.py` lists anything we skip
# under MISSING so it can be added deliberately.
#
# This curated list only bounds the *backtest* universe (it matches data/ CSV
# stems). For live trading, prefer broker-taxonomy discovery — see
# discover_from_paths and BreadthConfig.universe_path — which scales to as many
# symbols as the broker offers without maintaining tickers by hand.
_COMPANY_ROWS: tuple[tuple[str, ...], ...] = (
    # mega-cap tech
    ("aapl", "apple"), ("msft", "microsoft"), ("goog", "googl", "google", "alphabet"),
    ("amzn", "amazon"), ("meta", "facebook"), ("nvda", "nvidia"), ("tsla", "tesla"),
    ("avgo", "broadcom"), ("orcl", "oracle"), ("crm", "salesforce"),
    ("adbe", "adobe"), ("csco", "cisco"), ("acn", "accenture"), ("amd",),
    ("intc", "intel"), ("qcom", "qualcomm"), ("txn",), ("ibm",),
    ("now", "servicenow"), ("intu", "intuit"), ("amat",), ("mu", "micron"),
    ("adi",), ("lrcx",), ("klac",), ("snps",), ("cdns",), ("anet",), ("mrvl",),
    ("panw",), ("crwd", "crowdstrike"), ("snow", "snowflake"), ("ddog",),
    ("pltr", "palantir"), ("uber",), ("abnb", "airbnb"), ("pypl", "paypal"),
    ("shop", "shopify"), ("coin", "coinbase"), ("dell",), ("smci",),
    ("mstr", "microstrategy"), ("zm", "zoom"), ("roku",), ("dash", "doordash"),
    # financials
    ("jpm",), ("bac",), ("wfc", "wellsfargo"), ("gs", "goldman", "goldmansachs"),
    ("ms", "morganstanley"), ("citigroup", "citi"), ("axp", "americanexpress"),
    ("blk", "blackrock"), ("schw", "schwab"), ("spgi",), ("cb",), ("pgr",),
    ("usb",), ("pnc",), ("cof",), ("visa",), ("ma", "mastercard"),
    ("bx", "blackstone"),
    # healthcare
    ("jnj",), ("unh",), ("lly", "lilly", "elililly"), ("pfe", "pfizer"),
    ("abbv", "abbvie"), ("mrk", "merck"), ("tmo",), ("abt", "abbott"), ("dhr",),
    ("bmy",), ("amgn", "amgen"), ("gild", "gilead"), ("cvs",), ("mdt", "medtronic"),
    ("isrg",), ("vrtx",), ("regn",), ("zts",), ("syk",), ("bsx",), ("elv",),
    # consumer
    ("wmt", "walmart"), ("pg", "procter"), ("ko", "cocacola"), ("pep", "pepsi", "pepsico"),
    ("cost", "costco"), ("mcd", "mcdonalds"), ("nke", "nike"), ("sbux", "starbucks"),
    ("tgt", "target"), ("low", "lowes"), ("hd", "homedepot"), ("dis", "disney"),
    ("nflx", "netflix"), ("cmcsa", "comcast"), ("tjx",), ("mdlz",), ("cl", "colgate"),
    ("kmb",), ("mo", "altria"), ("pm", "philipmorris"), ("cmg", "chipotle"),
    ("lulu", "lululemon"), ("rost",), ("dg",), ("yum",), ("kdp",), ("stz",), ("el",),
    # industrials
    ("cat", "caterpillar"), ("ba", "boeing"), ("ge",), ("hon", "honeywell"),
    ("ups",), ("rtx", "raytheon"), ("lmt", "lockheed"), ("de", "deere"), ("mmm",),
    ("emr",), ("etn",), ("itw",), ("csx",), ("unp",), ("fdx", "fedex"), ("noc",),
    ("gd",), ("wm",),
    # energy
    ("xom", "exxon"), ("cvx", "chevron"), ("cop", "conocophillips"), ("slb",),
    ("eog",), ("psx",), ("mpc",), ("vlo",), ("oxy",),
    # autos, telecom, utilities, REITs
    ("gm",), ("ford",), ("rivn", "rivian"), ("lcid", "lucid"),
    ("att",), ("vz", "verizon"), ("tmus",), ("nee",), ("duk",),
    ("amt",), ("pld",), ("spg",),
)

# variant stem -> canonical company key
_VARIANT_TO_COMPANY: dict[str, str] = {
    variant: row[0] for row in _COMPANY_ROWS for variant in row
}

# Flat set of every accepted stem (what is_universe_member matches against).
US_STOCKS = tuple(sorted(_VARIANT_TO_COMPANY))

# Symbol-path fragments that mean "not a single-name equity" for path-based
# discovery. Kept next to the universe so both discovery routes agree.
_NON_EQUITY_PATH_HINTS = (
    "index", "indices", "forex", "fx", "crypto", "commodit", "metal",
    "energy futures", "bond", "etf", "cash",
)

# Instruments that live in a broker's "US" group but are not single-name
# equities. Real observed leakage on Vantage: spot metals (XAUUSD), oil
# (USOUSD/UKOUSD), the dollar index (USDX.r), index CFDs (US2000.r) and notes
# (USNote10Y). Mixing them into the tally breaks breadth's premise of one
# coherent, co-trading universe.
_NON_EQUITY_STEMS = frozenset({
    "uso", "usl", "gold", "silver", "oil", "ngas", "gas",
    "copper", "corn", "wheat", "soybean",
})

# Roots that begin a non-equity code. Matched as a prefix so vendor-tagged
# variants ('UKOUSDft') are caught too. Deliberately none of them prefix a real
# ticker in the universe ('usb' matches none of these).
_NON_EQUITY_PREFIXES = (
    "xau", "xag", "xpt", "xpd", "uko", "usoil", "ukoil",
    "usdx", "usnote", "ustec", "usidx", "wti", "brent",
)

# Quote suffixes brokers bolt onto a second feed of the SAME instrument.
# A trailing "usd" is the big one: Vantage lists both AAPL and AAPLUSD, so
# without stripping it the tally counts Apple twice. Note we deliberately do
# NOT strip generic letter suffixes — 'amazon' ends in 'n' and 'microsoft' in
# 'ft', so trimming those would corrupt real names.
_QUOTE_SUFFIXES = ("usd", "-us")


def normalize_stem(name: str) -> str:
    """Reduce a broker symbol to a comparable company stem.

    Strips the '_h1' CSV tag, any '.24H'/'.r' venue tag and a trailing quote
    suffix ('AAPLUSD' -> 'aapl', 'ASML-US' -> 'asml'). Symbols containing
    digits (US2000, USNote10Y, SPX500) collapse to '' — single-name US equities
    don't carry digits, while index/bond/futures codes routinely do.
    """
    s = name.lower().strip()
    s = s[:-3] if s.endswith("_h1") else s
    s = s.split(".")[0]          # venue tag: NVIDIA.24h, US2000.r
    s = s.replace("&", "")       # AT&T -> att
    for suffix in _QUOTE_SUFFIXES:
        if len(s) > len(suffix) and s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    if any(ch.isdigit() for ch in s):
        return ""
    return s


def looks_like_equity(name: str) -> bool:
    """True if a broker symbol plausibly names a single US-listed company.

    Used by path-based discovery, where the broker's group membership is the
    only other signal — it keeps spot metals, oil, index CFDs and notes out of
    the breadth tally even when they sit in the same 'US' folder."""
    stem = normalize_stem(name)
    if not stem or len(stem) < 2 or stem in _NON_EQUITY_STEMS:
        return False
    return not stem.startswith(_NON_EQUITY_PREFIXES)


def is_universe_member(symbol_or_stem: str) -> bool:
    """True if a CSV stem / symbol slug belongs to the US-stock universe.

    Accepts 'nvidia_h1', 'NVIDIA', 'nvidia.24h' etc. — the '_h1' suffix and any
    '.24h'-style venue tag are stripped before matching.
    """
    return _company_of(symbol_or_stem) is not None


def _company_of(symbol_or_stem: str) -> str | None:
    """Canonical company key for a symbol/stem, or None if not in the universe.

    'NVDA', 'NVIDIA' and 'nvidia.24h' all resolve to the same key, so a broker
    listing more than one spelling never double-counts one company.
    """
    return _VARIANT_TO_COMPANY.get(normalize_stem(symbol_or_stem))


def discover_from_paths(entries, path_contains: str = "us") -> list[str]:
    """US-equity symbol names from (name, path) pairs of the broker's catalogue.

    MT5 groups symbols by a path such as 'Stocks\\US\\AAPL', which is the
    broker's own taxonomy — far more reliable than guessing from names, and it
    scales to however many symbols are offered without maintaining a ticker
    list by hand. Rows whose path names a non-equity bucket (index, FX, crypto,
    ...) are dropped, and venue variants of one symbol collapse to the shortest
    name (the plain market-hours feed).
    """
    needle = path_contains.lower()
    best: dict[str, str] = {}
    order: list[str] = []
    for name, path in entries:
        p = (path or "").lower()
        if needle not in p or any(h in p for h in _NON_EQUITY_PATH_HINTS):
            continue
        if not looks_like_equity(name):
            continue
        base = _VARIANT_TO_COMPANY.get(normalize_stem(name)) or normalize_stem(name)
        if base not in best:
            best[base] = name
            order.append(base)
        elif len(name) < len(best[base]):
            best[base] = name
    return [best[b] for b in order]


def sample_universe(symbols: list[str], cap: int) -> list[str]:
    """At most `cap` symbols, evenly spread across `symbols` (cap<=0 = all).

    Breadth is an aggregate statistic: its sampling error shrinks like 1/sqrt(n),
    so a couple of hundred names estimate the same regime as a thousand — while
    the live tally costs one history fetch per symbol per bar. Capping keeps
    that cost bounded when the traded universe is large. The stride sample is
    deterministic and order-stable, so the measured breadth doesn't jitter from
    bar to bar as the membership changes.
    """
    if cap <= 0 or len(symbols) <= cap:
        return list(symbols)
    ordered = sorted(symbols)
    step = len(ordered) / cap
    return [ordered[int(i * step)] for i in range(cap)]


def compute_breadth(frames: dict[str, pd.DataFrame], lookback: int) -> pd.Series:
    """Net new-high count per timestamp across `frames` (symbol -> OHLCV df).

    Each symbol contributes +1 on a bar that makes a new `lookback`-bar high,
    -1 on a new low, 0 otherwise; bars during the warm-up window and timestamps
    where a symbol has no bar contribute 0. The result is indexed by the union
    of all frames' timestamps.
    """
    events = []
    for sym, df in frames.items():
        prior_high = df["high"].rolling(lookback).max().shift(1)
        prior_low = df["low"].rolling(lookback).min().shift(1)
        new_high = (df["high"] > prior_high).astype("int8")
        new_low = (df["low"] < prior_low).astype("int8")
        ev = (new_high - new_low)
        ev.name = sym
        events.append(ev)
    if not events:
        return pd.Series(dtype="float64")
    mat = pd.concat(events, axis=1)          # union index; NaN where no bar
    return mat.fillna(0).sum(axis=1)          # net breadth per timestamp


def discover_universe(names: list[str]) -> list[str]:
    """Pick the US-stock universe out of a broker's symbol list.

    Filters by is_universe_member, then dedupes venue variants of the same
    stock ('NVIDIA' vs 'NVIDIA.24h') keeping the shortest name — the plain
    market-hours feed — so one company never counts twice and off-hours feeds
    don't skew the count. Order of first appearance is preserved.
    """
    best: dict[str, str] = {}
    order: list[str] = []
    for name in names:
        company = _company_of(name)
        if company is None:
            continue
        # key by company, not raw stem, so 'NVDA' and 'NVIDIA' collapse to one
        if company not in best:
            best[company] = name
            order.append(company)
        elif len(name) < len(best[company]):
            best[company] = name
    return [best[c] for c in order]


def live_net_breadth(fetch, symbols: list[str], lookback: int,
                     bar_time) -> float:
    """Net new-high count across `symbols` at the closed bar `bar_time`, live.

    `fetch(symbol, "H1", n_bars)` must return an OHLCV frame whose last row is
    the still-forming bar (mt5_client.fetch_ohlcv's contract). Mirrors
    compute_breadth's per-timestamp semantics: a symbol contributes +1 when its
    bar at `bar_time` makes a new `lookback`-bar high, -1 on a new low, and 0
    when it is stale (last closed bar isn't `bar_time` — halted/lagging feed),
    short on history, or its fetch fails. Fail-open by design: a degraded feed
    weakens the signal toward 0 instead of raising.
    """
    net = 0
    for sym in symbols:
        try:
            df = fetch(sym, "H1", lookback + 3)
        except Exception:  # noqa: BLE001 — one bad feed must not kill the gate
            continue
        if len(df) < 2:
            continue
        closed = df.iloc[:-1]
        if len(closed) < lookback + 1 or closed.index[-1] != bar_time:
            continue
        window = closed.iloc[-(lookback + 1):-1]
        bar = closed.iloc[-1]
        if float(bar["high"]) > float(window["high"].max()):
            net += 1
        if float(bar["low"]) < float(window["low"].min()):
            net -= 1
    return float(net)


def breadth_blocks(side: str, value: float, min_net: float) -> bool:
    """True if the breadth regime rejects an entry on `side`.

    A long needs net breadth > min_net (broad strength); a short needs
    breadth < -min_net (broad weakness). An unknown regime (NaN — e.g. before
    the lookback fills) does NOT block: the filter only bites when it has an
    opinion, so it never silently kills the early part of a backtest.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return False
    if side == "buy":
        return not (value > min_net)
    return not (value < -min_net)
