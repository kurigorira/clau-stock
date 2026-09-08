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


def load_magic_index(config_dir: str | Path) -> dict[tuple[str, int], Config]:
    """(symbol, magic_number) -> Config for every genuine preset under config/.

    Keyed by symbol AND magic, not magic alone: retired presets and generated
    fleets have overlapping magic ranges, and a deal carries both fields, so
    the pair identifies the config that placed it even when the magic does
    not. Keying by magic alone silently filed a retired preset's FX trades
    under whichever fleet config loaded last.

    Searched recursively, so generated fleets in config/us_fleet* are indexed
    without every caller having to name them. Only files declaring both
    `symbol` and `execution.magic_number` are included, so non-preset YAMLs
    (watchlist.yaml) cannot enter via Config's defaults.
    """
    out: dict[tuple[str, int], Config] = {}
    for p in sorted(Path(config_dir).rglob("*.yaml")):
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
        key = (cfg.symbol, cfg.execution.magic_number)
        if key in out and out[key] is not None:
            other = out[key]
            if other.strategy != cfg.strategy:
                # Two configs are indistinguishable at the broker on this
                # instrument. Picking one would invent an attribution, so mark
                # the pair unresolvable and let callers say so.
                out[key] = None
                continue
        out[key] = cfg
    return out


def strategy_of(
    symbol: str, magic: int, magic_index: dict[tuple[str, int], Config | None]
) -> str:
    """Strategy behind a deal, from its symbol AND magic.

    No fall back to a magic-only match: a different symbol on the same magic
    is a different config, and treating it as this one is exactly the
    mis-attribution the pair key exists to prevent.
    """
    if (symbol, magic) in magic_index:
        cfg = magic_index[(symbol, magic)]
        return cfg.strategy if cfg is not None else "ambiguous"
    return "manual" if magic == 0 else "unknown"


def group_closed_deals(
    deals: list[Any], magic_index: dict[tuple[str, int], Config | None], equity: float
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

        cfg = magic_index.get((symbol, magic))
        strategy = strategy_of(symbol, magic, magic_index)
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


def to_position_snapshot(
    p: Any, magic_index: dict[tuple[str, int], Config | None]
) -> PositionSnapshot:
    """Build a PositionSnapshot from an MT5 position object (duck-typed:
    .symbol .type .volume .price_open .profit .sl .tp .magic .ticket)."""
    side = "buy" if p.type == 0 else "sell"  # POSITION_TYPE_BUY = 0
    return PositionSnapshot(
        symbol=p.symbol, side=side, volume=p.volume, price_open=p.price_open,
        profit=p.profit, sl=p.sl, tp=p.tp, magic=p.magic,
        strategy=strategy_of(p.symbol, p.magic, magic_index), ticket=p.ticket,
    )


def _money(x: float) -> str:
    # Plain ASCII on purpose: Windows Task Scheduler runs this script's
    # stdout through the console codepage (cp932 on ja-JP systems), which
    # cannot encode U+00A5 (¥) and crashes print() before the email is even
    # built. "JPY " avoids the whole class of codepage issues.
    sign = "+" if x >= 0 else ""
    return f"{sign}JPY {x:,.0f}"


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

        lines.append(f"  equity : JPY {r.equity:,.0f}   balance: JPY {r.balance:,.0f}")
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


def discover_accounts(env: dict[str, str] | None = None) -> list[str]:
    """Account suffixes present in the environment, in numeric-ish order.

    Reads MT5_LOGIN_<suffix> so adding a fifth account to .env is enough for
    the reports to pick it up - no default list to keep in step. A suffix is
    only returned when its password and server are set too, since a partial
    block would just fail at connect time.
    """
    import os
    import re

    src = os.environ if env is None else env
    out: list[str] = []
    for key in src:
        m = re.fullmatch(r"MT5_LOGIN_(\w+)", key)
        if not m:
            continue
        suffix = m.group(1)
        if src.get(f"MT5_PASSWORD_{suffix}") and src.get(f"MT5_SERVER_{suffix}"):
            out.append(suffix)
    return sorted(out, key=lambda s: (not s.isdigit(), int(s) if s.isdigit() else s))
