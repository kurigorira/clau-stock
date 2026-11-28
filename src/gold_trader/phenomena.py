"""Measuring market phenomena, not strategies.

Before building anything, ask whether the effect exists in THIS universe at
all, how big it is, and what survives costs. Everything here answers that and
stops - none of it places a trade or fits a parameter.

Two phenomena, chosen because they do not rely on out-predicting anyone:

**Overnight vs intraday.** US equity returns have historically accrued
between the close and the next open rather than during the session. That is
compensation for carrying gap risk, not a forecast, which is why it has
persisted. On a CFD the financing charge is levied against exactly that
window, so the question is entirely empirical: what is left after the swap.

**Cross-sectional dispersion.** Buying 100 large caps at once is one bet on
the market wearing the costume of a hundred. Ranking them and going long the
losers against the winners removes the common factor, leaving many roughly
independent bets - which matters less for return than for how fast you can
tell whether anything is there at all.

The statistics are reported as t-statistics against the bar that multiple
testing actually sets, not against zero: after N attempts the best of N pure
coin flips already looks good, and that bar is computed here.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import e as _E
from math import log, sqrt
from statistics import NormalDist

import numpy as np
import pandas as pd

__all__ = [
    "Stats",
    "summarize",
    "session_frame",
    "overnight_intraday",
    "cross_sectional_reversal",
    "expected_max_sharpe",
]

_EULER = 0.5772156649015329


@dataclass
class Stats:
    n: int = 0
    mean: float = 0.0          # per period, in return units
    std: float = 0.0
    win_rate: float = 0.0      # fraction of periods > 0
    t_stat: float = 0.0
    sharpe: float = 0.0        # annualised
    total: float = 0.0         # summed return over the sample


def summarize(returns, periods_per_year: float = 252.0) -> Stats:
    """Mean, dispersion and significance of a return series.

    t_stat is the plain mean/standard-error: it assumes the periods are
    independent, which is the assumption the caller has to earn. For a series
    of daily cross-sectional portfolio returns that is roughly true; for a
    series of overlapping per-trade returns on correlated symbols it is not,
    and the number will flatter the result.
    """
    r = np.asarray([x for x in returns if x == x], dtype=float)   # drop NaN
    s = Stats(n=len(r))
    if s.n == 0:
        return s
    s.mean = float(r.mean())
    s.std = float(r.std(ddof=1)) if s.n > 1 else 0.0
    s.win_rate = float((r > 0).mean())
    s.total = float(r.sum())
    if s.std > 0:
        s.t_stat = s.mean / (s.std / sqrt(s.n))
        s.sharpe = s.mean / s.std * sqrt(periods_per_year)
    return s


def expected_max_sharpe(n_trials: int, n_obs: int, periods_per_year: float = 252.0) -> float:
    """The annualised Sharpe the BEST of `n_trials` worthless strategies shows.

    Under the null a Sharpe estimate has standard deviation
    sqrt(periods_per_year / n_obs); the maximum of n_trials draws from that
    concentrates near the Gumbel expectation used below. This is the bar a
    result has to clear - selecting the best of twenty backtests and comparing
    it against zero is comparing it against the wrong thing.
    """
    if n_trials < 2 or n_obs < 2:
        return 0.0
    sigma = sqrt(periods_per_year / n_obs)
    nd = NormalDist()
    a = nd.inv_cdf(1.0 - 1.0 / n_trials)
    b = nd.inv_cdf(1.0 - 1.0 / (n_trials * _E))
    return sigma * ((1.0 - _EULER) * a + _EULER * b)


def session_frame(df: pd.DataFrame, session=None) -> pd.DataFrame:
    """One row per session: its open, its close, and the two return legs.

    `session` is (start_utc, end_utc) as datetime.time - the hours the
    instrument's cash session actually covers. Passing it is what makes the
    split mean anything: these CFDs quote outside the cash session, so
    grouping a raw UTC day puts nearly the whole 24 hours into "intraday" and
    leaves "overnight" measuring an hour of nothing. With the bounds given,
    intraday is open-to-close and overnight is close-to-next-open, which is
    the exposure a position actually carries between sessions.

    Without it the split still runs, on UTC days, and means much less.
    """
    if df.empty:
        return pd.DataFrame(columns=["open", "close", "intraday", "overnight"])
    if session is not None:
        start, end = session
        t = df.index.time
        df = df[(t >= start) & (t <= end)]
        if df.empty:
            return pd.DataFrame(columns=["open", "close", "intraday", "overnight"])
    g = df.groupby(df.index.normalize())
    out = pd.DataFrame({"open": g["open"].first(), "close": g["close"].last()})
    out = out[(out["open"] > 0) & (out["close"] > 0)]
    out["intraday"] = out["close"] / out["open"] - 1.0
    out["overnight"] = out["open"].shift(-1) / out["close"] - 1.0
    return out


def overnight_intraday(frames: dict[str, pd.DataFrame], cost_bp: float = 0.0,
                       sessions: dict | None = None):
    """Pooled overnight and intraday legs across symbols, net of a round trip.

    `cost_bp` is charged per side, so each leg pays it twice - entering and
    leaving. Returns (overnight Stats, intraday Stats, per-symbol rows).
    """
    cost = 2.0 * cost_bp / 10_000.0
    over: list[float] = []
    intra: list[float] = []
    rows: list[tuple[str, float, float, int]] = []
    for symbol, df in frames.items():
        s = session_frame(df, (sessions or {}).get(symbol))
        if s.empty:
            continue
        o = (s["overnight"].dropna() - cost).tolist()
        i = (s["intraday"].dropna() - cost).tolist()
        over.extend(o)
        intra.extend(i)
        rows.append((symbol, float(np.mean(o)) if o else float("nan"),
                     float(np.mean(i)) if i else float("nan"), len(o)))
    return summarize(over), summarize(intra), rows


def cross_sectional_reversal(
    frames: dict[str, pd.DataFrame],
    *,
    lookback: int = 1,
    quantile: float = 0.2,
    cost_bp: float = 0.0,
):
    """Long the weakest, short the strongest, held one session. Market-neutral.

    Ranking is on the trailing `lookback` sessions and the position is held
    over the FOLLOWING session, so nothing uses a return it could not have
    seen. Legs are equal-weighted and cancel, which is the point: the market
    factor goes, and what is left is one roughly independent observation per
    session rather than one per position.

    Costs are charged on the whole book each session (both legs fully turned
    over), which overstates them slightly and is the right way to be wrong.
    """
    closes = {}
    for symbol, df in frames.items():
        s = session_frame(df)
        if not s.empty:
            closes[symbol] = s["close"]
    if len(closes) < 4:
        return summarize([]), 0

    px = pd.DataFrame(closes).sort_index()
    rets = px.pct_change()
    signal = px.pct_change(lookback)

    daily: list[float] = []
    cost = 2.0 * cost_bp / 10_000.0
    for i in range(lookback, len(px) - 1):
        sig = signal.iloc[i].dropna()
        nxt = rets.iloc[i + 1]
        sig = sig[sig.index.isin(nxt.dropna().index)]
        k = int(len(sig) * quantile)
        if k < 2:
            continue
        ordered = sig.sort_values()
        longs = ordered.index[:k]          # weakest -> expect the bounce
        shorts = ordered.index[-k:]        # strongest -> expect the fade
        daily.append(
            float(nxt[longs].mean() - nxt[shorts].mean()) / 2.0 - cost
        )
    return summarize(daily), len(px.columns)
