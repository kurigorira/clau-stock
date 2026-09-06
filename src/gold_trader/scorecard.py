"""Live-vs-backtest scorecard: does the backtested edge survive real trading?

Pure aggregation/formatting here; scripts/scorecard.py pulls the live side
from MT5 deal history and the backtest side from the CSVs. The point is to
catch symbols whose paper edge is eaten by real spreads/slippage BEFORE
they quietly bleed the account - the single most valuable check once live
data exists.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass
class LiveStats:
    symbol: str
    strategy: str
    n: int
    win_rate: float
    total_pnl: float  # account currency
    profit_factor: float


@dataclass
class ScorecardRow:
    symbol: str
    strategy: str
    live_n: int
    live_win_rate: float
    live_pf: float
    live_pnl: float
    bt_n: int          # backtested trade count over the reference window
    bt_win_rate: float
    bt_pf: float
    verdict: str       # "ok" | "underperforming" | "too-few" | "no-backtest"


def live_stats_from_deals(deals: list[Any], strategy_of) -> list[LiveStats]:
    """Aggregate closed MT5 deals into per-(symbol) live stats.

    Each deal needs .symbol, .magic, .profit, .commission, .swap and
    .entry == DEAL_ENTRY_OUT already filtered by the caller. strategy_of is
    a callable magic -> strategy name.
    """
    groups: dict[str, list[float]] = defaultdict(list)
    strat: dict[str, str] = {}
    for d in deals:
        net = float(d.profit) + float(d.commission) + float(d.swap)
        groups[d.symbol].append(net)
        strat.setdefault(d.symbol, strategy_of(d.magic))

    out: list[LiveStats] = []
    for symbol, nets in groups.items():
        wins = [x for x in nets if x > 0]
        losses = [x for x in nets if x < 0]
        gross_win = sum(wins)
        gross_loss = -sum(losses)
        pf = gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
        out.append(
            LiveStats(
                symbol=symbol,
                strategy=strat[symbol],
                n=len(nets),
                win_rate=len(wins) / len(nets) if nets else 0.0,
                total_pnl=sum(nets),
                profit_factor=pf,
            )
        )
    return sorted(out, key=lambda s: s.total_pnl)


def build_scorecard(
    live: list[LiveStats],
    backtest: dict[str, dict],
    *,
    min_live_trades: int = 5,
    pf_tolerance: float = 0.6,
) -> list[ScorecardRow]:
    """Join live stats with backtest results (symbol -> summary dict).

    Verdict:
      too-few         : fewer than min_live_trades live closes (not judgeable yet)
      no-backtest     : no backtest summary for the symbol
      underperforming : live PF < pf_tolerance * backtest PF (edge decayed)
      ok              : otherwise
    """
    rows: list[ScorecardRow] = []
    for s in live:
        bt = backtest.get(s.symbol)
        bt_n = int(bt["n"]) if bt else 0
        bt_win = float(bt["win_rate"]) if bt else 0.0
        bt_pf = _bt_pf(bt) if bt else 0.0

        if s.n < min_live_trades:
            verdict = "too-few"
        elif bt is None or bt_n == 0:
            verdict = "no-backtest"
        elif _finite(s.profit_factor) < pf_tolerance * _finite(bt_pf):
            verdict = "underperforming"
        else:
            verdict = "ok"

        rows.append(
            ScorecardRow(
                symbol=s.symbol, strategy=s.strategy,
                live_n=s.n, live_win_rate=s.win_rate,
                live_pf=s.profit_factor, live_pnl=s.total_pnl,
                bt_n=bt_n, bt_win_rate=bt_win, bt_pf=bt_pf,
                verdict=verdict,
            )
        )
    order = {"underperforming": 0, "ok": 1, "no-backtest": 2, "too-few": 3}
    return sorted(rows, key=lambda r: (order.get(r.verdict, 9), r.live_pnl))


def _bt_pf(summary: dict) -> float:
    trades = summary.get("trades", [])
    gross_win = sum(t.pnl_price for t in trades if t.pnl_price > 0)
    gross_loss = -sum(t.pnl_price for t in trades if t.pnl_price < 0)
    if gross_loss > 0:
        return gross_win / gross_loss
    return float("inf") if gross_win > 0 else 0.0


def _finite(x: float) -> float:
    # treat inf PF as a large-but-finite number so comparisons behave
    return 1e9 if x == float("inf") else x


def format_scorecard(rows: list[ScorecardRow], window_desc: str) -> tuple[str, str]:
    n_under = sum(1 for r in rows if r.verdict == "underperforming")
    subject = f"[clau-stock scorecard] {window_desc} | {len(rows)} symbols | {n_under} underperforming"

    lines = [f"clau-stock live-vs-backtest scorecard ({window_desc})", ""]
    hdr = (
        f"{'symbol':<12} {'strat':<9} {'verdict':<15} | "
        f"{'liveN':>5} {'liveWin':>7} {'livePF':>7} {'livePnL':>10} | "
        f"{'btN':>5} {'btWin':>7} {'btPF':>7}"
    )
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for r in rows:
        lines.append(
            f"{r.symbol:<12} {r.strategy:<9} {r.verdict:<15} | "
            f"{r.live_n:>5} {r.live_win_rate:>7.1%} {_pf(r.live_pf):>7} {r.live_pnl:>10.0f} | "
            f"{r.bt_n:>5} {r.bt_win_rate:>7.1%} {_pf(r.bt_pf):>7}"
        )
    lines.append("")
    lines.append("verdict key: underperforming = live PF well below backtest -> review/remove;")
    lines.append("             too-few = not enough live closes yet; no-backtest = missing CSV")
    return subject, "\n".join(lines)


def _pf(x: float) -> str:
    return "  inf" if x == float("inf") else f"{x:.2f}"
