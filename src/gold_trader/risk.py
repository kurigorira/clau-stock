from __future__ import annotations

import math


def position_volume(
    equity: float,
    risk_pct: float,
    stop_distance_price: float,
    tick_value: float,
    tick_size: float,
    volume_min: float,
    volume_max: float,
    volume_step: float,
) -> float:
    """Position size in lots so a stop-out costs ~`risk_pct`%% of equity.

    money_per_lot = (stop_distance / tick_size) * tick_value
    Tick value/size come from MT5 symbol info, so this works for whatever
    contract size the broker uses (Vantage XAUUSD is typically 100 oz/lot).
    """
    if stop_distance_price <= 0 or tick_size <= 0 or tick_value <= 0:
        return 0.0
    risk_amount = equity * (risk_pct / 100.0)
    money_per_lot = (stop_distance_price / tick_size) * tick_value
    if money_per_lot <= 0:
        return 0.0
    raw_volume = risk_amount / money_per_lot
    stepped = math.floor(raw_volume / volume_step) * volume_step
    if stepped < volume_min:
        return 0.0
    return min(stepped, volume_max)
