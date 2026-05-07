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
    data = add_indicators(df, cfg)
    trades: List[Trade] = []
    side: str | None = None
    entry_price = 0.0
    entry_time: pd.Timestamp | None = None
    stop = 0.0

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
            atr = float(bar["atr"])
            hi = float(bar["donch_high"])
            lo = float(bar["donch_low"])
            if np.isnan(atr) or np.isnan(hi) or np.isnan(lo) or np.isnan(ema):
                continue
            if close > hi and close > ema:
                side = "buy"
                entry_price = close + slippage_price
                entry_time = bar.name
                stop = close - cfg.risk.atr_stop_mult * atr
            elif close < lo and close < ema:
                side = "sell"
                entry_price = close - slippage_price
                entry_time = bar.name
                stop = close + cfg.risk.atr_stop_mult * atr

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
