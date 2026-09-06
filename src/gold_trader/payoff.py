"""Payoff-shape statistics, and the break-even arithmetic that reads them.

The question this answers: when a strategy that passed its backtest loses
live, is the win RATE off, or is the PAYOFF (average win vs average loss)
off? They call for different fixes - a wrong win rate points at the entry
or the regime, a wrong payoff points at the exit or at costs.

PnL units cancel in every figure here (ratios and rates), which is what
makes a backtest measured in price units comparable with live results
measured in JPY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass
class PayoffStats:
    n: int = 0
    wins: int = 0
    gross_win: float = 0.0
    gross_loss: float = 0.0     # positive magnitude
    total: float = 0.0
    median_hours: float | None = None

    @property
    def win_rate(self) -> float:
        """Fraction, not percent."""
        return self.wins / self.n if self.n else 0.0

    @property
    def avg_win(self) -> float:
        return self.gross_win / self.wins if self.wins else 0.0

    @property
    def avg_loss(self) -> float:
        """Average losing trade as a positive magnitude."""
        losses = self.n - self.wins
        return self.gross_loss / losses if losses else 0.0

    @property
    def payoff_ratio(self) -> float:
        """avg win / avg loss. inf when nothing lost, 0 when nothing won."""
        if self.avg_loss > 0:
            return self.avg_win / self.avg_loss
        return float("inf") if self.avg_win > 0 else 0.0

    @property
    def expectancy(self) -> float:
        """Expected PnL per trade, in the input's units."""
        return self.total / self.n if self.n else 0.0

    @property
    def breakeven_payoff(self) -> float:
        """Payoff ratio this win rate would need to break even.

        (1 - w) / w. Infinite when nothing wins - no payoff saves it.
        """
        w = self.win_rate
        return (1.0 - w) / w if w > 0 else float("inf")

    @property
    def breakeven_win_rate(self) -> float:
        """Win rate this payoff ratio would need to break even: 1 / (1 + R)."""
        r = self.payoff_ratio
        if r == float("inf"):
            return 0.0
        return 1.0 / (1.0 + r) if r >= 0 else 1.0


def stats_from_pnls(
    pnls: Iterable[float], hours: Sequence[float] | None = None
) -> PayoffStats:
    """Payoff stats for a set of closed trades.

    A zero-PnL trade counts as a loss: it consumed a slot and its costs are
    already inside the number, so calling it a win would flatter the rate.
    """
    values = [float(p) for p in pnls]
    s = PayoffStats(n=len(values))
    for v in values:
        s.total += v
        if v > 0:
            s.wins += 1
            s.gross_win += v
        else:
            s.gross_loss += -v
    if hours:
        ordered = sorted(float(h) for h in hours)
        mid = len(ordered) // 2
        s.median_hours = (
            ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
        )
    return s


def _fmt_ratio(x: float) -> str:
    if x == float("inf"):
        return "inf"
    return f"{x:.2f}"


def _fmt_hours(x: float | None) -> str:
    return "—" if x is None else f"{x:.1f}h"


def diagnose(live: PayoffStats, back: PayoffStats) -> list[str]:
    """Which half of the edge failed to survive contact with the broker.

    Compares the two shapes and names the gap, rather than restating that
    the live number is worse. Thresholds are deliberately loose: this is a
    pointer at what to investigate, not a test.
    """
    out: list[str] = []
    if live.n == 0 or back.n == 0:
        return ["not enough trades on one side to compare"]

    wr_gap = live.win_rate - back.win_rate
    po_gap = live.payoff_ratio - back.payoff_ratio

    if abs(wr_gap) >= 0.05:
        out.append(
            f"win rate {'below' if wr_gap < 0 else 'above'} backtest by "
            f"{abs(wr_gap) * 100:.1f} points ({live.win_rate * 100:.1f}% live "
            f"vs {back.win_rate * 100:.1f}% backtest) — look at the entry and "
            f"the regime filter"
        )
    if back.payoff_ratio != float("inf") and abs(po_gap) >= 0.3:
        out.append(
            f"payoff ratio {'below' if po_gap < 0 else 'above'} backtest "
            f"({_fmt_ratio(live.payoff_ratio)} live vs "
            f"{_fmt_ratio(back.payoff_ratio)} backtest) — look at the exit, "
            f"the stop distance and per-trade costs"
        )
    if (
        live.median_hours is not None
        and back.median_hours is not None
        and back.median_hours > 0
        and live.median_hours < back.median_hours * 0.6
    ):
        out.append(
            f"live trades close far sooner ({_fmt_hours(live.median_hours)} vs "
            f"{_fmt_hours(back.median_hours)} median) — winners are being cut short"
        )

    # The finding that does not depend on sample size: even at the win rate
    # the backtest promised, this payoff cannot pay.
    if live.payoff_ratio != float("inf") and back.win_rate > 0:
        needed = (1.0 - back.win_rate) / back.win_rate
        if live.payoff_ratio < needed:
            out.append(
                f"structural: at the backtested win rate "
                f"({back.win_rate * 100:.1f}%) this live payoff ratio "
                f"({_fmt_ratio(live.payoff_ratio)}) would STILL lose — it needs "
                f"{_fmt_ratio(needed)}. Restoring the win rate alone cannot fix it"
            )
    if not out:
        out.append("live and backtest shapes agree within tolerance")
    return out


def format_block(title: str, live: PayoffStats, back: PayoffStats | None) -> str:
    """One strategy's live/backtest comparison as fixed-width text."""
    lines = [f"=== {title} ==="]
    rows = [
        ("trades", f"{live.n}", f"{back.n}" if back else "—"),
        ("win rate", f"{live.win_rate * 100:.1f}%",
         f"{back.win_rate * 100:.1f}%" if back else "—"),
        ("avg win", f"{live.avg_win:,.2f}", f"{back.avg_win:,.4f}" if back else "—"),
        ("avg loss", f"{live.avg_loss:,.2f}", f"{back.avg_loss:,.4f}" if back else "—"),
        ("payoff ratio", _fmt_ratio(live.payoff_ratio),
         _fmt_ratio(back.payoff_ratio) if back else "—"),
        ("expectancy/trade", f"{live.expectancy:,.2f}",
         f"{back.expectancy:,.4f}" if back else "—"),
        ("median hold", _fmt_hours(live.median_hours),
         _fmt_hours(back.median_hours) if back else "—"),
    ]
    lines.append(f"  {'':<18} {'live':>14} {'backtest':>14}")
    for label, a, b in rows:
        lines.append(f"  {label:<18} {a:>14} {b:>14}")
    lines.append(
        f"  needs payoff >= {_fmt_ratio(live.breakeven_payoff)} at this win rate, "
        f"or win rate >= {live.breakeven_win_rate * 100:.1f}% at this payoff"
    )
    if back:
        for line in diagnose(live, back):
            lines.append(f"  -> {line}")
    return "\n".join(lines)
