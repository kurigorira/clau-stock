"""Equal-weight buy and hold: sizing to an exposure, not to a stop.

Every other book here sizes a position from its stop distance, so that a loss
costs a fixed fraction of equity. Buy and hold has no stop, so that rule has
nothing to work with. It sizes to a target NOTIONAL instead: each symbol gets
an equal share of `exposure x equity`, and `exposure` is then the whole risk
decision - 1.0 is unlevered, 2.0 is twice the account at risk to the market.

Two things this cannot size away, both of which belong in the decision rather
than the arithmetic:

- **Financing.** A CFD is charged swap on the full notional every night it is
  held. Holding forever means paying it forever, on leverage if exposure > 1.
  For the same exposure a cash share or an ETF pays none of it.
- **Drawdown.** Without stops the position rides whatever the market does. A
  1.0 exposure falls with the index; a 2.0 exposure falls twice as fast and
  meets a margin call somewhere on the way down.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["BUYHOLD_MAGIC", "Target", "plan_targets", "round_volume"]

# The magic stamped on every held position. It lives here rather than in the
# script because the reports need it too: nothing in config/ describes this
# book (there is no preset - it is not a strategy the executor runs), so
# without a name for this number the held positions report as "unknown".
BUYHOLD_MAGIC = 20271000


@dataclass
class Target:
    symbol: str
    price: float
    volume: float          # lots, already rounded to the broker's step
    notional: float        # volume * contract_size * price
    held: float = 0.0      # lots already open
    to_buy: float = 0.0    # lots still to buy, rounded
    skip: str = ""         # why nothing can be bought, if so


def round_volume(raw: float, meta: dict) -> float:
    """Lots the broker will actually accept, rounded DOWN to its step.

    Down rather than nearest: rounding up would quietly buy more exposure
    than asked for, and across 100 symbols those roundings all point the same
    way. Below the minimum lot the answer is zero, not the minimum - a symbol
    too expensive for its share of the book should be skipped, not overweighted.
    """
    # no guessing a step: this sends real orders, and a wrong assumption is
    # wrong by whatever factor the broker actually uses
    step = float(meta.get("volume_step") or 0.0)
    vmin = float(meta.get("volume_min") or step)
    vmax = float(meta.get("volume_max") or 0) or None
    if step <= 0 or raw <= 0:
        return 0.0
    lots = int(raw / step) * step
    # int() on a float division can land a hair under a whole step
    if (lots + step) <= raw + step * 1e-9:
        lots += step
    lots = round(lots, 8)
    if lots < vmin:
        return 0.0
    if vmax is not None and lots > vmax:
        lots = vmax
    return lots


def plan_targets(
    quotes: dict[str, tuple[float, dict]],
    equity: float,
    *,
    exposure: float = 1.0,
    held: dict[str, float] | None = None,
) -> list[Target]:
    """What to hold, and what is still missing, for an equal-weight book.

    `quotes` maps symbol -> (price, symbol_meta). Each symbol targets
    `exposure * equity / len(quotes)` of notional. Symbols already held count
    toward the target, so running this again tops up rather than doubling.
    """
    held = held or {}
    out: list[Target] = []
    if not quotes or equity <= 0:
        return out
    per_symbol = exposure * equity / len(quotes)

    for symbol in sorted(quotes):
        price, meta = quotes[symbol]
        size = float(meta.get("contract_size") or 1.0)
        if price <= 0 or size <= 0:
            out.append(Target(symbol, price, 0.0, 0.0, skip="no quote"))
            continue
        want = round_volume(per_symbol / (price * size), meta)
        have = float(held.get(symbol, 0.0))
        t = Target(
            symbol=symbol,
            price=price,
            volume=want,
            notional=want * size * price,
            held=have,
        )
        if want <= 0:
            lot_cost = float(meta.get("volume_min") or 0) * size * price
            t.skip = (f"one lot is {lot_cost:,.0f} vs a "
                      f"{per_symbol:,.0f} slot")
        else:
            gap = want - have
            t.to_buy = round_volume(gap, meta) if gap > 0 else 0.0
            if have > 0 and t.to_buy <= 0:
                t.skip = "already at target"
        out.append(t)
    return out
