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

# US single-name stocks in the fleet (CSV stems, lower-case). Indices, FX,
# crypto and commodities are deliberately excluded — breadth is only meaningful
# within one coherent, co-trading universe.
US_STOCKS = (
    "aapl", "amazon", "amd", "bac", "boeing", "cat", "cost", "cvx", "disney",
    "exxon", "ge", "goog", "gs", "hd", "intel", "jnj", "jpm", "ko", "ma",
    "mcd", "meta", "mrk", "msft", "nflx", "nke", "nvidia", "pep", "pfizer",
    "pg", "tsla", "unh", "visa", "wmt",
)


def is_universe_member(symbol_or_stem: str) -> bool:
    """True if a CSV stem / symbol slug belongs to the US-stock universe.

    Accepts 'nvidia_h1', 'NVIDIA', 'nvidia.24h' etc. — the '_h1' suffix and any
    '.24h'-style venue tag are stripped before matching.
    """
    s = symbol_or_stem.lower()
    s = s[:-3] if s.endswith("_h1") else s
    s = s.split(".")[0]
    return s in US_STOCKS


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
        if not is_universe_member(name):
            continue
        base = name.lower().split(".")[0]
        if base not in best:
            best[base] = name
            order.append(base)
        elif len(name) < len(best[base]):
            best[base] = name
    return [best[b] for b in order]


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
