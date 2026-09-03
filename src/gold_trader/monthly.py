"""Monthly operating statistics: pure aggregation/formatting logic.

scripts/monthly_report.py wires this to MT5 (account_info, history_deals_get);
everything here is plain Python so it can be unit tested without a broker.

Semantics
---------
- A "trade" is one closed position (deals grouped by position_id), not one
  deal: partial closes collapse into a single trade. Its net PnL includes
  profit + commission + swap over every deal of the position (the entry
  deal's commission included), and it is dated by its LAST closing deal.
- Months are calendar months in the requested timezone offset (JST by
  default). MT5 stamps deals in broker server time, so a trade within a few
  hours of midnight on the 1st can land in the neighboring month; at monthly
  granularity this is noise.
- Balance operations (deposits/withdrawals/credits: deals with no symbol)
  are tracked separately so a funded month doesn't masquerade as a winning
  one, and so end-of-month balances reconcile against the current balance.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import Config
from .report import strategy_of

JST = timezone(timedelta(hours=9))

_DEAL_ENTRY_OUT = 1  # mt5.DEAL_ENTRY_OUT


@dataclass
class TradeRow:
    position_id: int
    symbol: str
    magic: int
    strategy: str
    close_time: datetime
    net: float


@dataclass
class MonthStats:
    month: str  # "2026-08"
    trades: int = 0
    wins: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0  # negative
    balance_ops: float = 0.0
    by_strategy: dict[str, list] = field(default_factory=dict)  # name -> [pnl, n]
    end_balance: float | None = None

    @property
    def net(self) -> float:
        return self.gross_profit + self.gross_loss

    @property
    def win_rate(self) -> float:
        return 100.0 * self.wins / self.trades if self.trades else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss < 0:
            return self.gross_profit / -self.gross_loss
        return float("inf") if self.gross_profit > 0 else 0.0


@dataclass
class AccountMonthly:
    account: str
    login: int = 0
    balance: float = 0.0
    months: list[MonthStats] = field(default_factory=list)  # chronological
    error: str | None = None


def build_trades(
    deals: list[Any], magic_index: dict[int, Config], tz: timezone = JST
) -> tuple[list[TradeRow], list[Any]]:
    """(closed trades, balance-operation deals) from raw MT5 deals.

    Deals need .position_id, .symbol, .magic, .profit, .commission, .swap,
    .time (unix seconds) and .entry. Positions that never closed (no
    entry==DEAL_ENTRY_OUT deal in the window) are dropped: their PnL is not
    realized yet and their entry costs will be counted when they do close.
    """
    balance_ops = [d for d in deals if not getattr(d, "symbol", "")]

    by_pos: dict[int, list[Any]] = defaultdict(list)
    for d in deals:
        if getattr(d, "symbol", "") and getattr(d, "position_id", 0):
            by_pos[d.position_id].append(d)

    trades: list[TradeRow] = []
    for pos_id, ds in by_pos.items():
        outs = [d for d in ds if d.entry == _DEAL_ENTRY_OUT]
        if not outs:
            continue  # still open
        net = sum(float(d.profit) + float(d.commission) + float(d.swap) for d in ds)
        last_out = max(outs, key=lambda d: d.time)
        trades.append(
            TradeRow(
                position_id=pos_id,
                symbol=last_out.symbol,
                magic=last_out.magic,
                strategy=strategy_of(last_out.magic, magic_index),
                close_time=datetime.fromtimestamp(last_out.time, tz=tz),
                net=net,
            )
        )
    trades.sort(key=lambda t: t.close_time)
    return trades, balance_ops


def monthly_stats(
    trades: list[TradeRow],
    balance_ops: list[Any],
    *,
    balance_now: float | None = None,
    tz: timezone = JST,
) -> list[MonthStats]:
    """Bucket trades and balance ops into calendar months (chronological).

    With balance_now given, back-fills each month's end balance by walking
    the current balance backwards through later months' net + balance_ops.
    Only months that saw a trade or a balance op appear; a silent month in
    the middle of the history is shown as a zero row so streaks stay visible.
    """
    buckets: dict[str, MonthStats] = {}

    def bucket(key: str) -> MonthStats:
        if key not in buckets:
            buckets[key] = MonthStats(month=key)
        return buckets[key]

    for t in trades:
        key = t.close_time.strftime("%Y-%m")
        m = bucket(key)
        m.trades += 1
        if t.net >= 0:
            m.wins += 1
            m.gross_profit += t.net
        else:
            m.gross_loss += t.net
        entry = m.by_strategy.setdefault(t.strategy, [0.0, 0])
        entry[0] += t.net
        entry[1] += 1

    for d in balance_ops:
        key = datetime.fromtimestamp(d.time, tz=tz).strftime("%Y-%m")
        bucket(key).balance_ops += float(d.profit)

    if not buckets:
        return []

    # fill silent months between first and last so gaps are visible
    keys = sorted(buckets)
    y, mo = map(int, keys[0].split("-"))
    last_y, last_mo = map(int, keys[-1].split("-"))
    while (y, mo) <= (last_y, last_mo):
        bucket(f"{y:04d}-{mo:02d}")
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)

    months = [buckets[k] for k in sorted(buckets)]

    if balance_now is not None:
        running = balance_now
        for m in reversed(months):
            m.end_balance = running
            running -= m.net + m.balance_ops
    return months


def _money(x: float) -> str:
    # ASCII on purpose - see report._money (cp932 consoles).
    sign = "+" if x >= 0 else ""
    return f"{sign}JPY {x:,.0f}"


def _pf_txt(m: MonthStats) -> str:
    pf = m.profit_factor
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def format_monthly_report(reports: list[AccountMonthly], generated_at: str) -> str:
    lines: list[str] = [f"clau-stock monthly report - {generated_at}", ""]
    for r in reports:
        head = f"=== Account {r.account}"
        if r.login:
            head += f" ({r.login})"
        lines.append(head + " ===")
        if r.error:
            lines.append(f"  ERROR: {r.error}")
            lines.append("")
            continue
        if not r.months:
            lines.append("  no closed trades or balance operations in the window")
            lines.append("")
            continue

        lines.append(
            "  month    trades  win%    PF     gross+        gross-        "
            "net           in/out        end balance"
        )
        for m in r.months:
            end_bal = f"JPY {m.end_balance:,.0f}" if m.end_balance is not None else "-"
            lines.append(
                f"  {m.month}  {m.trades:>6}  {m.win_rate:>5.1f}  {_pf_txt(m):>5}"
                f"  {_money(m.gross_profit):>12}  {_money(m.gross_loss):>12}"
                f"  {_money(m.net):>12}  {_money(m.balance_ops):>12}  {end_bal}"
            )
        total_trades = sum(m.trades for m in r.months)
        total_wins = sum(m.wins for m in r.months)
        total_net = sum(m.net for m in r.months)
        win_rate = 100.0 * total_wins / total_trades if total_trades else 0.0
        lines.append(
            f"  TOTAL    {total_trades:>6}  {win_rate:>5.1f}         "
            f"net {_money(total_net)}   balance now JPY {r.balance:,.0f}"
        )

        strat_lines = []
        for m in r.months:
            for strat, (pnl, n) in sorted(m.by_strategy.items()):
                strat_lines.append(
                    f"    {m.month}  {strat:<10} {_money(pnl):>12}  ({n} trades)"
                )
        if strat_lines:
            lines.append("  by strategy:")
            lines.extend(strat_lines)
        lines.append("")
    return "\n".join(lines)


def monthly_csv_rows(reports: list[AccountMonthly]) -> list[dict[str, Any]]:
    """Tidy rows (one per account x month) for --csv."""
    rows: list[dict[str, Any]] = []
    for r in reports:
        if r.error:
            continue
        for m in r.months:
            rows.append(
                {
                    "account": r.account,
                    "login": r.login,
                    "month": m.month,
                    "trades": m.trades,
                    "wins": m.wins,
                    "win_rate_pct": round(m.win_rate, 2),
                    "profit_factor": (
                        "" if m.profit_factor == float("inf") else round(m.profit_factor, 3)
                    ),
                    "gross_profit": round(m.gross_profit, 2),
                    "gross_loss": round(m.gross_loss, 2),
                    "net_pnl": round(m.net, 2),
                    "balance_ops": round(m.balance_ops, 2),
                    "end_balance": (
                        "" if m.end_balance is None else round(m.end_balance, 2)
                    ),
                }
            )
    return rows
