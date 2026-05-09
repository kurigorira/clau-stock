from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

from .config import Config
from .strategy import add_indicators


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    stop: float
    pnl_price: float


def run_backtest(
    df: pd.DataFrame,
    cfg: Config,
    *,
    slippage_price: float = 0.0,
) -> dict:
    """Bar-by-bar backtest. Mirrors strategy.evaluate_last_bar entry filters.

    Daily-guard limits (consecutive losses, daily loss cap) are NOT applied
    here — they're enforced live by the executor against the broker account.
    """
    data = add_indicators(df, cfg)
    trades: List[Trade] = []
    side: str | None = None
    entry_price = 0.0
    entry_time: pd.Timestamp | None = None
    stop = 0.0

    f = cfg.filters
    buffer_mult = cfg.breakout.atr_buffer_mult
    stop_mult = cfg.risk.atr_stop_mult

    for i in range(1, len(data)):
        bar = data.iloc[i]

        if side is not None:
            hit_stop = (
                (side == "buy" and bar["low"] <= stop)
                or (side == "sell" and bar["high"] >= stop)
            )
            exit_signal = (
                (side == "buy" and bar["close"] < bar["exit_low"])
                or (side == "sell" and bar["close"] > bar["exit_high"])
            )
            if hit_stop or exit_signal:
                exit_price = stop if hit_stop else float(bar["close"])
                exit_price -= slippage_price if side == "buy" else -slippage_price
                pnl = (
                    exit_price - entry_price
                    if side == "buy"
                    else entry_price - exit_price
                )
                trades.append(
                    Trade(
                        side=side,
                        entry_time=entry_time,  # type: ignore[arg-type]
                        entry_price=entry_price,
                        exit_time=bar.name,
                        exit_price=exit_price,
                        stop=stop,
                        pnl_price=pnl,
                    )
                )
                side = None

        if side is None:
            close = float(bar["close"])
            ema = float(bar["ema_trend"])
            ema_slope = float(bar["ema_slope"])
            atr = float(bar["atr"])
            atr_pct = float(bar["atr_pct"])
            adx = float(bar["adx"])
            hi = float(bar["donch_high"])
            lo = float(bar["donch_low"])
            if any(
                np.isnan(x) for x in (atr, atr_pct, adx, ema, ema_slope, hi, lo)
            ):
                continue
            if not (f.atr_pct_min <= atr_pct <= f.atr_pct_max):
                continue
            if adx < f.adx_min:
                continue
            buffer = buffer_mult * atr
            if close > hi + buffer and close > ema and ema_slope > 0:
                side = "buy"
                entry_price = close + slippage_price
                entry_time = bar.name
                stop = close - stop_mult * atr
            elif close < lo - buffer and close < ema and ema_slope < 0:
                side = "sell"
                entry_price = close - slippage_price
                entry_time = bar.name
                stop = close + stop_mult * atr

    return _summary(trades)


def _summary(trades: List[Trade]) -> dict:
    if not trades:
        return {"trades": [], "n": 0, "win_rate": 0.0, "total_pnl_price": 0.0}
    pnls = np.array([t.pnl_price for t in trades])
    wins = pnls > 0
    return {
        "trades": trades,
        "n": int(len(trades)),
        "win_rate": float(wins.mean()),
        "total_pnl_price": float(pnls.sum()),
        "avg_win": float(pnls[wins].mean()) if wins.any() else 0.0,
        "avg_loss": float(pnls[~wins].mean()) if (~wins).any() else 0.0,
        "max_drawdown_price": float(_max_drawdown(pnls.cumsum())),
    }


def _max_drawdown(equity_curve: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity_curve)
    dd = equity_curve - peak
    return float(dd.min()) if len(dd) else 0.0
