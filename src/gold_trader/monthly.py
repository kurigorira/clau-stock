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
    # None when the opening deal falls outside the queried window, so the
    # position's real entry time is unknown rather than zero.
    hours_held: float | None = None


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
        ins = [d for d in ds if d.entry != _DEAL_ENTRY_OUT]
        hours = None
        if ins:
            opened = min(d.time for d in ins)
            hours = max(0.0, (last_out.time - opened) / 3600.0)
        trades.append(
            TradeRow(
                position_id=pos_id,
                symbol=last_out.symbol,
                magic=last_out.magic,
                strategy=strategy_of(last_out.magic, magic_index),
                close_time=datetime.fromtimestamp(last_out.time, tz=tz),
                net=net,
                hours_held=hours,
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


def mask_login(login: int) -> str:
    """Account number with all but the last 3 digits hidden.

    A login is half of a credential pair (login + server identify the
    account to anyone with the password), so published reports carry the
    masked form by default - enough to tell accounts apart, not enough to
    address one.
    """
    s = str(login)
    return f"***{s[-3:]}" if len(s) > 3 else "***"


def format_monthly_markdown(
    reports: list[AccountMonthly],
    generated_at: str,
    *,
    mask_logins: bool = True,
) -> str:
    """Markdown version of the monthly report, for committing to the repo.

    Same numbers as format_monthly_report; account logins are masked unless
    the caller opts out.
    """
    def _num(x: float) -> str:
        sign = "+" if x > 0 else ""
        return f"{sign}{x:,.0f}"

    out: list[str] = [
        "# Monthly operating statistics",
        "",
        f"Generated {generated_at} from live MT5 account history "
        "(`scripts/monthly_report.py --markdown`).",
        "",
        "One closed **position** counts as one trade (partial closes collapse) and "
        "its PnL includes commission and swap on every deal of the position. Months "
        "are JST calendar months; a month with no trades is shown as a zero row. "
        "Deposits and withdrawals are reported separately from trading PnL, so a "
        "funded month cannot read as a winning one. All amounts in JPY.",
        "",
    ]

    ok = [r for r in reports if r.error is None and r.months]
    if ok:
        out += [
            "## Summary",
            "",
            "| account | months | trades | win % | PF | net PnL |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for r in ok:
            trades = sum(m.trades for m in r.months)
            wins = sum(m.wins for m in r.months)
            gp = sum(m.gross_profit for m in r.months)
            gl = sum(m.gross_loss for m in r.months)
            wr = 100.0 * wins / trades if trades else 0.0
            pf = gp / -gl if gl < 0 else (float("inf") if gp > 0 else 0.0)
            pf_txt = "inf" if pf == float("inf") else f"{pf:.2f}"
            label = _account_label(r, mask_logins)
            out.append(
                f"| {label} | {len(r.months)} | {trades} | {wr:.1f} | "
                f"{pf_txt} | {_num(gp + gl)} |"
            )
        out.append("")

    for r in reports:
        out.append(f"## Account {_account_label(r, mask_logins)}")
        out.append("")
        if r.error:
            out += [f"Not reported: {r.error}", ""]
            continue
        if not r.months:
            out += ["No closed trades or balance operations in the window.", ""]
            continue

        out += [
            "| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for m in r.months:
            end_bal = f"{m.end_balance:,.0f}" if m.end_balance is not None else "-"
            out.append(
                f"| {m.month} | {m.trades} | {m.win_rate:.1f} | {_pf_txt(m)} | "
                f"{_num(m.gross_profit)} | {_num(m.gross_loss)} | {_num(m.net)} | "
                f"{_num(m.balance_ops)} | {end_bal} |"
            )
        total_trades = sum(m.trades for m in r.months)
        total_wins = sum(m.wins for m in r.months)
        total_net = sum(m.net for m in r.months)
        wr = 100.0 * total_wins / total_trades if total_trades else 0.0
        out.append(
            f"| **total** | **{total_trades}** | **{wr:.1f}** | | | | "
            f"**{_num(total_net)}** | | **{r.balance:,.0f}** |"
        )
        out.append("")

        strat_rows = [
            (m.month, strat, pnl, n)
            for m in r.months
            for strat, (pnl, n) in sorted(m.by_strategy.items())
        ]
        if strat_rows:
            out += [
                "By strategy:",
                "",
                "| month | strategy | net | trades |",
                "|---|---|---:|---:|",
            ]
            out += [
                f"| {month} | {strat} | {_num(pnl)} | {n} |"
                for month, strat, pnl, n in strat_rows
            ]
            out.append("")

    return "\n".join(out)


def _account_label(r: AccountMonthly, mask_logins: bool) -> str:
    if not r.login:
        return r.account
    shown = mask_login(r.login) if mask_logins else str(r.login)
    return f"{r.account} ({shown})"


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
