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

# mt5.DEAL_REASON_*: what closed the position. Comparing the live mix with
# the backtest's exit reasons is what separates "the stop is being hit more
# often than on paper" from "the strategy's own exit fires differently".
_DEAL_REASONS = {
    0: "manual",    # CLIENT
    1: "manual",    # MOBILE
    2: "manual",    # WEB
    3: "expert",    # EXPERT - the bot's own exit signal
    4: "sl",        # STOP LOSS
    5: "tp",        # TAKE PROFIT
    6: "stopout",   # margin stop out
}


def deal_exit_reason(deal: Any) -> str:
    """Closing deal -> exit reason label; 'unknown' when the build omits it."""
    code = getattr(deal, "reason", None)
    if code is None:
        return "unknown"
    try:
        return _DEAL_REASONS.get(int(code), "unknown")
    except (TypeError, ValueError):
        return "unknown"


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
    # What actually closed the position, from the closing deal's reason code.
    # "sl" | "tp" | "expert" | "manual" | "stopout" | "unknown"
    exit_reason: str = "unknown"


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
class OpenPosition:
    """One position still open, with the two numbers a closed trade hides."""
    symbol: str
    magic: int
    strategy: str
    volume: float
    opened: datetime | None
    profit: float          # floating PnL, MT5 reports this WITHOUT swap
    swap: float            # financing paid so far; negative is a cost
    # Exposure in the ACCOUNT currency, so it is comparable with profit and
    # swap. 0.0 means the broker gave nothing to convert with, not "no
    # exposure" - see unit_value.
    notional: float = 0.0

    @property
    def unrealised(self) -> float:
        """What closing right now would add to the balance."""
        return self.profit + self.swap

    def days_held(self, now: datetime) -> float | None:
        if self.opened is None:
            return None
        return max(0.0, (now - self.opened).total_seconds() / 86400.0)


@dataclass
class OpenGroup:
    """Open positions of one strategy, added up."""
    strategy: str
    positions: int = 0
    volume: float = 0.0
    profit: float = 0.0
    swap: float = 0.0
    notional: float = 0.0
    oldest: datetime | None = None

    @property
    def unrealised(self) -> float:
        return self.profit + self.swap


@dataclass
class SwapDrag:
    """The nightly financing cost, annualised.

    Swap is charged at rollover, so a position opened a few hours ago has
    paid nothing yet and would drag the average toward zero. Those are
    counted separately (`too_new`) rather than averaged in - the same rule
    the payoff audit uses: say what the number covers, or don't print it.
    """
    counted: int = 0
    too_new: int = 0
    notional: float = 0.0
    per_day: float = 0.0  # JPY/day over the counted positions; negative = cost

    @property
    def annual(self) -> float:
        return self.per_day * 365.0

    # Above this, the ratio is not a financing rate. Brokers charge single
    # digits to low tens of percent; anything near 100%/yr means the cost and
    # the notional are not in the same currency (the first version of this
    # divided a JPY swap by a USD notional and published -536%/yr). Better to
    # withhold the number than to publish a unit error as a fact.
    IMPLAUSIBLE_PCT = 100.0

    @property
    def annual_pct(self) -> float | None:
        """Annual financing as a % of the notional it is charged on.

        None when there is nothing to divide by, or when the answer is too
        large to be a financing rate at all.
        """
        if self.notional <= 0:
            return None
        pct = 100.0 * self.annual / self.notional
        if abs(pct) > self.IMPLAUSIBLE_PCT:
            return None
        return pct

    @property
    def rate_withheld(self) -> bool:
        """True when a notional exists but the rate it implies is impossible.

        Worth saying out loud rather than silently omitting: it means the
        broker's figures for these symbols cannot be reconciled, which is a
        data problem, not a quiet account.
        """
        return self.notional > 0 and self.annual_pct is None


@dataclass
class AccountMonthly:
    account: str
    login: int = 0
    balance: float = 0.0
    months: list[MonthStats] = field(default_factory=list)  # chronological
    error: str | None = None
    # Open book: empty list means "none open", which is not the same as the
    # terminal never having been asked.
    open_groups: list[OpenGroup] = field(default_factory=list)
    drag: SwapDrag | None = None


def build_trades(
    deals: list[Any],
    magic_index: dict[tuple[str, int], Config],
    tz: timezone = JST,
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
                strategy=strategy_of(last_out.symbol, last_out.magic, magic_index),
                close_time=datetime.fromtimestamp(last_out.time, tz=tz),
                net=net,
                hours_held=hours,
                exit_reason=deal_exit_reason(last_out),
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


def unit_value(meta: dict) -> float:
    """Account-currency value of 1.0 of price, per lot. 0.0 when unknown.

    `contract_size * price` is denominated in the symbol's QUOTE currency,
    but MT5 reports .profit and .swap in the ACCOUNT currency. Mixing the
    two divides a JPY cost by a USD notional and overstates the rate by
    whatever the FX rate happens to be.

    trade_tick_value is in the account currency by definition: one lot moving
    by trade_tick_size earns exactly that. So tick_value / tick_size is the
    account-currency exposure per 1.0 of price, per lot - the conversion and
    the contract size in a single number the broker itself supplies.
    """
    tick_value = float(meta.get("trade_tick_value") or 0.0)
    tick_size = float(meta.get("trade_tick_size") or 0.0)
    if tick_value <= 0 or tick_size <= 0:
        return 0.0
    return tick_value / tick_size


def build_open_positions(
    positions: list[Any],
    magic_index: dict[tuple[str, int], Config],
    unit_values: dict[str, float] | None = None,
    tz: timezone = JST,
) -> list[OpenPosition]:
    """Raw MT5 positions -> OpenPosition rows.

    Positions need .symbol, .magic, .volume, .time (unix seconds), .profit,
    .swap and .price_current. `unit_values` maps symbol -> account-currency
    value of 1.0 of price per lot (see unit_value); a symbol missing from it
    gets notional 0 rather than a guessed one, because a notional in the
    wrong currency is wrong by whatever the FX rate happens to be.
    """
    sizes = unit_values or {}
    out: list[OpenPosition] = []
    for p in positions:
        symbol = getattr(p, "symbol", "") or ""
        if not symbol:
            continue  # balance entries are not positions
        magic = int(getattr(p, "magic", 0) or 0)
        opened = None
        raw_time = getattr(p, "time", None)
        if raw_time:
            opened = datetime.fromtimestamp(int(raw_time), tz=tz)
        volume = float(getattr(p, "volume", 0.0) or 0.0)
        per_price = float(sizes.get(symbol) or 0.0)  # account ccy, per lot
        price = float(getattr(p, "price_current", 0.0) or 0.0)
        out.append(
            OpenPosition(
                symbol=symbol,
                magic=magic,
                strategy=strategy_of(symbol, magic, magic_index),
                volume=volume,
                opened=opened,
                profit=float(getattr(p, "profit", 0.0) or 0.0),
                swap=float(getattr(p, "swap", 0.0) or 0.0),
                notional=(
                    volume * per_price * price
                    if per_price > 0 and price > 0
                    else 0.0
                ),
            )
        )
    return out


def group_open(positions: list[OpenPosition]) -> list[OpenGroup]:
    """Open positions summed per strategy, alphabetical."""
    groups: dict[str, OpenGroup] = {}
    for p in positions:
        g = groups.setdefault(p.strategy, OpenGroup(strategy=p.strategy))
        g.positions += 1
        g.volume += p.volume
        g.profit += p.profit
        g.swap += p.swap
        g.notional += p.notional
        if p.opened is not None and (g.oldest is None or p.opened < g.oldest):
            g.oldest = p.opened
    return [groups[k] for k in sorted(groups)]


def swap_drag(
    positions: list[OpenPosition], now: datetime, *, min_days: float = 1.0
) -> SwapDrag:
    """Financing cost per day, from positions old enough to have paid it.

    Each position's swap so far divided by the days it has been held is its
    daily rate; the book's rate is the sum. Positions younger than `min_days`
    have not been through a rollover, so including them would understate the
    cost - they are counted in `too_new` instead.
    """
    drag = SwapDrag()
    for p in positions:
        held = p.days_held(now)
        if held is None or held < min_days:
            drag.too_new += 1
            continue
        drag.counted += 1
        drag.notional += p.notional
        drag.per_day += p.swap / held
    return drag


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
            # a book that only holds closes nothing - that is the whole point
            # of the open section, so it must survive this early exit
            lines.extend(_open_book_lines(r))
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
        lines.extend(_open_book_lines(r))
        lines.append("")
    return "\n".join(lines)


def _drag_sentence(d: SwapDrag) -> str:
    """One line on what the financing costs, or why it cannot be said yet."""
    if d.counted == 0:
        return (
            f"    financing: not measurable yet - all {d.too_new} position(s) "
            f"are younger than a rollover"
        )
    pct = d.annual_pct
    rate = f" = {pct:+.1f}%/yr of notional" if pct is not None else ""
    if d.rate_withheld:
        rate = " (rate withheld: the notional implies an impossible rate)"
    tail = f" ({d.too_new} too new to count)" if d.too_new else ""
    return (
        f"    financing: {_money(d.per_day)}/day, {_money(d.annual)}/yr{rate}"
        f", over {d.counted} position(s){tail}"
    )


def _open_book_lines(r: AccountMonthly) -> list[str]:
    if not r.open_groups:
        return []
    lines = [
        "  open positions (not in the rows above - nothing is realized yet):",
        "    strategy     pos      volume  unrealised      of which swap   notional",
    ]
    for g in r.open_groups:
        lines.append(
            f"    {g.strategy:<10} {g.positions:>4}  {g.volume:>10.2f}"
            f"  {_money(g.unrealised):>13}  {_money(g.swap):>13}"
            f"  {'-' if g.notional <= 0 else f'JPY {g.notional:,.0f}'}"
        )
    if r.drag is not None:
        lines.append(_drag_sentence(r.drag))
    return lines


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
            # a held book realizes nothing, so this is exactly where it lives
            out += _open_book_markdown(r)
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

        out += _open_book_markdown(r)

    return "\n".join(out)


def _open_book_markdown(r: AccountMonthly) -> list[str]:
    """The open book as Markdown, or nothing when the account holds nothing."""
    if not r.open_groups:
        return []

    def _num(x: float) -> str:
        sign = "+" if x > 0 else ""
        return f"{sign}{x:,.0f}"

    out = [
        "Open positions — **not** counted in the tables above, because "
        "nothing has been realized yet:",
        "",
        "| strategy | positions | volume | unrealised | of which swap | notional |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for g in r.open_groups:
        out.append(
            f"| {g.strategy} | {g.positions} | {g.volume:,.2f} | "
            f"{_num(g.unrealised)} | {_num(g.swap)} | "
            f"{'—' if g.notional <= 0 else f'{g.notional:,.0f}'} |"
        )
    out.append("")
    if r.drag is not None:
        out += [_drag_markdown(r.drag), ""]
    return out


def _drag_markdown(d: SwapDrag) -> str:
    if d.counted == 0:
        return (
            f"Financing cost is not measurable yet: all {d.too_new} open "
            f"position(s) are younger than one rollover, so none has been "
            f"charged swap."
        )
    pct = d.annual_pct
    rate = f", **{pct:+.1f}%/yr of notional**" if pct is not None else ""
    if d.rate_withheld:
        rate = (
            " — the rate as a percentage is withheld, because the notional "
            "reported for these symbols implies a rate no broker charges"
        )
    tail = f" {d.too_new} position(s) are too new to count." if d.too_new else ""
    return (
        f"Financing: **{d.per_day:+,.0f}/day** → **{d.annual:+,.0f}/yr**{rate}, "
        f"measured over {d.counted} position(s) held at least a day.{tail} "
        f"A CFD pays this every night the position is held; a cash share or "
        f"an ETF pays none of it."
    )


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
