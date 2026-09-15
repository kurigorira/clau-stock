"""Signal reconciliation: did the live bot take the trades the backtest took?

Statistics need a sample; this does not. Over the same window, on the same
symbols, the backtest names every entry it would have made and the account
names every entry it did make. Matching them is a yes/no question about the
implementation, and any answer it gives is the same answer at 47 trades as
at 4,700.

Timing: the backtest stamps a signal with the H1 bar it was evaluated on -
the bar whose close produced it. The live bot only sees that bar once it has
closed, then sends the order, so the fill lands in the NEXT bar, or the one
after it when the first attempt is rejected and retried. Matching allows for
exactly that offset rather than comparing raw timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

__all__ = [
    "Signal",
    "LiveEntry",
    "MatchResult",
    "match_signals",
    "format_reconciliation",
]


@dataclass(frozen=True)
class Signal:
    """An entry the backtest says it would have taken."""
    symbol: str
    side: str            # "buy" | "sell"
    bar_time: datetime   # tz-aware UTC: the bar the signal was evaluated on


@dataclass(frozen=True)
class LiveEntry:
    """An entry the account actually took."""
    symbol: str
    side: str
    time: datetime       # tz-aware UTC: the fill
    magic: int = 0


@dataclass
class MatchResult:
    matched: list[tuple[Signal, LiveEntry]] = field(default_factory=list)
    backtest_only: list[Signal] = field(default_factory=list)   # live missed it
    live_only: list[LiveEntry] = field(default_factory=list)    # live invented it

    @property
    def n_backtest(self) -> int:
        return len(self.matched) + len(self.backtest_only)

    @property
    def n_live(self) -> int:
        return len(self.matched) + len(self.live_only)

    @property
    def match_rate(self) -> float:
        """Fraction of backtest signals the live bot actually took."""
        return len(self.matched) / self.n_backtest if self.n_backtest else 0.0


def match_signals(
    signals: list[Signal],
    live: list[LiveEntry],
    *,
    bar: timedelta = timedelta(hours=1),
    slack_bars: int = 1,
) -> MatchResult:
    """Pair backtest signals with live entries of the same symbol and side.

    A signal on bar T is expected to fill somewhere inside the bar starting at
    T + bar, or up to `slack_bars` later - so the accepted range runs from
    T + bar up to (but not including) the end of that last allowed bar.
    Matching is greedy in time order and each live entry is consumed once, so
    two signals on consecutive bars cannot both claim the same fill.
    """
    result = MatchResult()
    # bucket by (symbol, side) so an unrelated symbol can never absorb a fill
    pools: dict[tuple[str, str], list[LiveEntry]] = {}
    for e in sorted(live, key=lambda x: x.time):
        pools.setdefault((e.symbol, e.side), []).append(e)

    used: set[int] = set()
    for sig in sorted(signals, key=lambda s: s.bar_time):
        lo = sig.bar_time + bar
        hi = sig.bar_time + bar * (2 + max(0, slack_bars))   # end of the last bar
        hit = None
        for e in pools.get((sig.symbol, sig.side), ()):
            if id(e) in used:
                continue
            if lo <= e.time < hi:
                hit = e
                break
        if hit is None:
            result.backtest_only.append(sig)
        else:
            used.add(id(hit))
            result.matched.append((sig, hit))

    for e in live:
        if id(e) not in used:
            result.live_only.append(e)
    result.live_only.sort(key=lambda x: x.time)
    return result


def _top(counter: dict[str, int], n: int = 8) -> str:
    items = sorted(counter.items(), key=lambda kv: -kv[1])[:n]
    return ", ".join(f"{k}×{v}" for k, v in items) if items else "—"


def format_reconciliation(r: MatchResult, *, examples: int = 6) -> str:
    """Human-readable verdict. The verdict is the point, not the tables."""
    lines: list[str] = []
    lines.append(f"backtest signals : {r.n_backtest}")
    lines.append(f"live entries     : {r.n_live}")
    lines.append(f"matched          : {len(r.matched)} "
                 f"({r.match_rate * 100:.1f}% of backtest signals)")
    lines.append(f"backtest only    : {len(r.backtest_only)}  "
                 f"(the bot did not take these)")
    lines.append(f"live only        : {len(r.live_only)}  "
                 f"(the backtest never produced these)")
    lines.append("")

    if r.backtest_only:
        by_symbol: dict[str, int] = {}
        for s in r.backtest_only:
            by_symbol[s.symbol] = by_symbol.get(s.symbol, 0) + 1
        lines.append(f"  most-missed symbols: {_top(by_symbol)}")
        for s in sorted(r.backtest_only, key=lambda x: x.bar_time)[:examples]:
            lines.append(f"    missed  {s.bar_time:%Y-%m-%d %H:%M} UTC  "
                         f"{s.symbol:<10} {s.side}")
        if len(r.backtest_only) > examples:
            lines.append(f"    ... and {len(r.backtest_only) - examples} more")
        lines.append("")

    if r.live_only:
        by_symbol = {}
        for e in r.live_only:
            by_symbol[e.symbol] = by_symbol.get(e.symbol, 0) + 1
        lines.append(f"  unexplained-entry symbols: {_top(by_symbol)}")
        for e in r.live_only[:examples]:
            lines.append(f"    extra   {e.time:%Y-%m-%d %H:%M} UTC  "
                         f"{e.symbol:<10} {e.side}  magic={e.magic}")
        if len(r.live_only) > examples:
            lines.append(f"    ... and {len(r.live_only) - examples} more")
        lines.append("")

    lines.append("verdict:")
    if not r.n_backtest and not r.n_live:
        lines.append("  nothing to compare in this window")
    elif r.live_only and r.match_rate < 0.5:
        lines.append("  the two sides largely disagree in BOTH directions. The live "
                     "bot is not running the strategy the backtest validated - treat "
                     "this as an implementation bug, not a market result.")
    elif r.live_only:
        lines.append(f"  {len(r.live_only)} live entries have no backtest signal "
                     "behind them. Even a handful is a bug: the bot cannot see "
                     "anything the backtest cannot. Investigate these first.")
    elif r.match_rate >= 0.9:
        lines.append("  every live entry traces to a backtest signal and almost all "
                     "signals were taken. The implementation agrees with the "
                     "backtest; the live/backtest performance gap is execution cost "
                     "and sampling, not a coding difference.")
    else:
        lines.append(f"  every live entry traces to a backtest signal, but the bot "
                     f"skipped {len(r.backtest_only)} of {r.n_backtest} of them. "
                     "Skipping is expected from the position cap, the stop-distance "
                     "guard, session hours and downtime - check those account for "
                     "the number before reading anything into performance.")
    return "\n".join(lines)
