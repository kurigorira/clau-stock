"""Daily status report: pure formatting/aggregation logic.

scripts/daily_report.py wires this to MT5 (account_info, positions_get,
history_deals_get) and Gmail; everything here is plain-Python so it can be
unit tested without a broker connection.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .config import Config


@dataclass
class ClosedGroup:
    symbol: str
    magic: int
    strategy: str
    pnl: float
    trades: int
    loss_streak: int
    guard_tripped: bool


@dataclass
class PositionSnapshot:
    symbol: str
    side: str
    volume: float
    price_open: float
    profit: float
    sl: float
    tp: float
    magic: int
    strategy: str
    ticket: int


@dataclass
class AccountReport:
    account: str
    equity: float = 0.0
    balance: float = 0.0
    realized_pnl_today: float = 0.0
    trades_today: int = 0
    closed_groups: list[ClosedGroup] = field(default_factory=list)
    open_positions: list[PositionSnapshot] = field(default_factory=list)
    unprotected_positions: list[PositionSnapshot] = field(default_factory=list)
    error: str | None = None


def load_magic_index(config_dir: str | Path) -> dict[int, Config]:
    """magic_number -> Config for every genuine preset in config/.

    Only files that declare both `symbol` and `execution.magic_number` are
    indexed, so non-preset YAMLs (watchlist.yaml) can't collide with a real
    magic via Config's defaults.
    """
    out: dict[int, Config] = {}
    for p in Path(config_dir).glob("*.yaml"):
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if "symbol" not in raw or "magic_number" not in (raw.get("execution") or {}):
            continue
        try:
            cfg = Config.from_yaml(p)
        except Exception:  # noqa: BLE001
            continue
        out[cfg.execution.magic_number] = cfg
    return out


def strategy_of(magic: int, magic_index: dict[int, Config]) -> str:
    cfg = magic_index.get(magic)
    if cfg is not None:
        return cfg.strategy
    return "manual" if magic == 0 else "unknown"


def group_closed_deals(
    deals: list[Any], magic_index: dict[int, Config], equity: float
) -> list[ClosedGroup]:
    """Aggregate today's closing deals by (symbol, magic).

    Each deal needs .symbol, .magic, .profit, .commission, .swap, .time
    (matches MT5's deal objects and mt5_client.today_closed_pnl's shape).
    loss_streak mirrors mt5_client.today_closed_pnl: consecutive losing
    closes counting back from the most recent. guard_tripped reuses the
    exact thresholds the live executor enforces (DailyGuardConfig).
    """
    groups: dict[tuple[str, int], list[Any]] = defaultdict(list)
    for d in deals:
        groups[(d.symbol, d.magic)].append(d)

    out: list[ClosedGroup] = []
    for (symbol, magic), ds in groups.items():
        ds_sorted = sorted(ds, key=lambda d: d.time)
        nets = [float(d.profit) + float(d.commission) + float(d.swap) for d in ds_sorted]
        pnl = sum(nets)
        streak = 0
        for net in reversed(nets):
            if net < 0:
                streak += 1
            else:
                break

        cfg = magic_index.get(magic)
        strategy = strategy_of(magic, magic_index)
        tripped = False
        if cfg is not None:
            g = cfg.daily_guard
            loss_cap = equity * g.max_loss_pct / 100.0
            tripped = streak >= g.max_consecutive_losses or pnl <= -loss_cap

        out.append(
            ClosedGroup(
                symbol=symbol, magic=magic, strategy=strategy,
                pnl=pnl, trades=len(ds_sorted), loss_streak=streak,
                guard_tripped=tripped,
            )
        )
    return sorted(out, key=lambda g: g.pnl)


def to_position_snapshot(p: Any, magic_index: dict[int, Config]) -> PositionSnapshot:
    """Build a PositionSnapshot from an MT5 position object (duck-typed:
    .symbol .type .volume .price_open .profit .sl .tp .magic .ticket)."""
    side = "buy" if p.type == 0 else "sell"  # POSITION_TYPE_BUY = 0
    return PositionSnapshot(
        symbol=p.symbol, side=side, volume=p.volume, price_open=p.price_open,
        profit=p.profit, sl=p.sl, tp=p.tp, magic=p.magic,
        strategy=strategy_of(p.magic, magic_index), ticket=p.ticket,
    )


def _money(x: float) -> str:
    sign = "+" if x >= 0 else ""
    return f"{sign}¥{x:,.0f}"


def format_report_email(reports: list[AccountReport], generated_at: str) -> tuple[str, str]:
    """Build (subject, body) for the daily status email."""
    ok = [r for r in reports if r.error is None]
    total_pnl = sum(r.realized_pnl_today for r in ok)
    total_trades = sum(r.trades_today for r in ok)
    total_unprotected = sum(len(r.unprotected_positions) for r in ok)

    subject = (
        f"[clau-stock daily] {generated_at} | {_money(total_pnl)} | "
        f"{total_trades} trades | {len(ok)}/{len(reports)} accounts OK"
    )
    if total_unprotected:
        subject += f" | !! {total_unprotected} UNPROTECTED"

    lines: list[str] = [f"clau-stock daily report - {generated_at}", ""]
    for r in reports:
        lines.append(f"=== Account {r.account} ===")
        if r.error:
            lines.append(f"  ERROR: {r.error}")
            lines.append("")
            continue

        lines.append(f"  equity : ¥{r.equity:,.0f}   balance: ¥{r.balance:,.0f}")
        lines.append(f"  today  : {_money(r.realized_pnl_today)}  ({r.trades_today} trades closed)")

        if r.closed_groups:
            lines.append("  by symbol today:")
            for g in r.closed_groups:
                flag = "  <-- GUARD TRIPPED" if g.guard_tripped else ""
                lines.append(
                    f"    {g.symbol:<12} [{g.strategy:<9}] {_money(g.pnl):>10}  "
                    f"n={g.trades} streak={g.loss_streak}{flag}"
                )

        if r.open_positions:
            lines.append(f"  open positions ({len(r.open_positions)}):")
            for p in r.open_positions:
                sl_txt = f"{p.sl}" if p.sl else "NONE"
                tp_txt = f"{p.tp}" if p.tp else "-"
                lines.append(
                    f"    {p.symbol:<12} {p.side:<4} {p.volume}  "
                    f"pnl={_money(p.profit):>10}  SL={sl_txt} TP={tp_txt}  [{p.strategy}]"
                )
        else:
            lines.append("  open positions: none")

        if r.unprotected_positions:
            lines.append("  !! UNPROTECTED (no stop-loss):")
            for p in r.unprotected_positions:
                lines.append(
                    f"    ticket={p.ticket} {p.symbol} {p.side} vol={p.volume} "
                    f"magic={p.magic} [{p.strategy}]"
                )
        lines.append("")

    strat_totals: dict[str, list] = defaultdict(lambda: [0.0, 0])
    for r in ok:
        for g in r.closed_groups:
            entry = strat_totals[g.strategy]
            entry[0] += g.pnl
            entry[1] += g.trades
    if strat_totals:
        lines.append("=== By strategy (all accounts) ===")
        for strat, (pnl, n) in sorted(strat_totals.items(), key=lambda kv: -kv[1][0]):
            lines.append(f"  {strat:<10} {_money(pnl):>10}  ({n} trades)")
        lines.append("")

    return subject, "\n".join(lines)
