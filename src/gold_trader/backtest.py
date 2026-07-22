from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd

from .config import Config
from .data import resample_ohlcv
from .strategy import (
    add_indicators,
    evaluate_fib_entry,
    evaluate_macd_entry,
    should_exit_macd,
    stoch_blocks,
)


@dataclass
class Trade:
    side: str
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    stop: float
    pnl_price: float
    reason: str = "channel"  # "tp" | "sl" | "channel"
    bars_held: int = 0


def run_backtest(
    df: pd.DataFrame,
    cfg: Config,
    *,
    slippage_price: float = 0.0,
) -> dict:
    """Bar-by-bar backtest dispatched on cfg.strategy.

    Daily-guard limits (consecutive losses, daily loss cap) are NOT applied
    here — they're enforced live by the executor against the broker account.
    """
    if cfg.strategy == "fibonacci":
        return _run_backtest_fib(df, cfg, slippage_price=slippage_price)
    if cfg.strategy == "macd":
        return _run_backtest_macd(df, cfg, slippage_price=slippage_price)
    data = add_indicators(df, cfg)
    trades: List[Trade] = []
    side: str | None = None
    entry_price = 0.0
    entry_time: pd.Timestamp | None = None
    stop = 0.0

    f = cfg.filters
    buffer_mult = cfg.breakout.atr_buffer_mult
    stop_mult = cfg.risk.atr_stop_mult

    entry_i = 0
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
                        reason="sl" if hit_stop else "channel",
                        bars_held=i - entry_i,
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
            gate = cfg.stoch.use  # shared stochastic confirmation, off by default
            if (
                close > hi + buffer and close > ema and ema_slope > 0
                and not (gate and stoch_blocks("buy", bar, cfg))
            ):
                side = "buy"
                entry_price = close + slippage_price
                entry_time = bar.name
                entry_i = i
                stop = close - stop_mult * atr
            elif (
                close < lo - buffer and close < ema and ema_slope < 0
                and not (gate and stoch_blocks("sell", bar, cfg))
            ):
                side = "sell"
                entry_price = close - slippage_price
                entry_time = bar.name
                entry_i = i
                stop = close + stop_mult * atr

    return _summary(trades)


def _run_backtest_fib(
    df: pd.DataFrame,
    cfg: Config,
    *,
    slippage_price: float = 0.0,
) -> dict:
    """Fibonacci-strategy backtest over an H1 frame.

    H4 bars are synthesised from the H1 data via resample. Look-ahead is
    avoided by only handing evaluate_fib_entry the H4 bars that had fully
    closed before the current H1 bar closed (H4 open <= t - 3h for an H1
    bar opening at t). Exits: SL hit, TP hit, or the Donchian reverse-channel
    exit — the same safety net the live executor applies to every position.
    When SL and TP are both touched within one bar the SL fills first
    (conservative).
    """
    data = add_indicators(df, cfg)
    h4 = add_indicators(resample_ohlcv(df, "4h"), cfg)
    # h4_closed_count[i] = number of H4 bars fully closed before H1 bar i closes
    closed_counts = h4.index.searchsorted(
        data.index - pd.Timedelta(hours=3), side="right"
    )

    trades: List[Trade] = []
    side: str | None = None
    entry_price = 0.0
    entry_time: pd.Timestamp | None = None
    stop = 0.0
    tp = 0.0

    warmup = max(cfg.fibonacci.vol_sma_length, cfg.fibonacci.macd_slow) + 2
    entry_i = 0
    for i in range(warmup, len(data)):
        bar = data.iloc[i]

        if side is not None:
            hit_stop = (
                (side == "buy" and bar["low"] <= stop)
                or (side == "sell" and bar["high"] >= stop)
            )
            hit_tp = (
                (side == "buy" and bar["high"] >= tp)
                or (side == "sell" and bar["low"] <= tp)
            )
            exit_signal = (
                (side == "buy" and bar["close"] < bar["exit_low"])
                or (side == "sell" and bar["close"] > bar["exit_high"])
            )
            if hit_stop or hit_tp or exit_signal:
                if hit_stop:
                    exit_price = stop
                    reason = "sl"
                elif hit_tp:
                    exit_price = tp
                    reason = "tp"
                else:
                    exit_price = float(bar["close"])
                    reason = "channel"
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
                        reason=reason,
                        bars_held=i - entry_i,
                    )
                )
                side = None

        if side is None:
            k = int(closed_counts[i])
            if k < cfg.fibonacci.swing_lookback:
                continue
            sig = evaluate_fib_entry(data.iloc[: i + 1], h4.iloc[:k], cfg)
            if sig.side is None or sig.tp is None:
                continue
            side = sig.side
            entry_price = sig.entry_ref + (
                slippage_price if side == "buy" else -slippage_price
            )
            entry_time = bar.name
            entry_i = i
            stop = sig.stop
            tp = sig.tp

    return _summary(trades)


def _run_backtest_macd(
    df: pd.DataFrame,
    cfg: Config,
    *,
    slippage_price: float = 0.0,
) -> dict:
    """MACD-strategy backtest. Entry on the MACD/signal cross (optionally
    gated by the H4 trend), exit on the opposite cross or the ATR stop.

    Like the fib backtest, H4 is synthesised from H1 via resample with the
    same no-lookahead rule (only H4 bars closed 3h before the H1 bar close
    are visible). Exit reasons: 'sl' for the stop, 'channel' for the
    opposite-cross exit (reusing the shared reason vocabulary). SL fills
    first when the stop and an opposite cross land on the same bar.
    """
    data = add_indicators(df, cfg)
    use_h4 = cfg.macd.use_h4_filter and bool(cfg.trend.higher_timeframe)
    if use_h4:
        h4 = add_indicators(resample_ohlcv(df, "4h"), cfg)
        closed_counts = h4.index.searchsorted(
            data.index - pd.Timedelta(hours=3), side="right"
        )
    else:
        h4 = None
        closed_counts = None

    trades: List[Trade] = []
    side: str | None = None
    entry_price = 0.0
    entry_time: pd.Timestamp | None = None
    entry_i = 0
    stop = 0.0

    warmup = cfg.macd.slow + cfg.macd.signal + 2
    for i in range(warmup, len(data)):
        bar = data.iloc[i]

        if side is not None:
            hit_stop = (
                (side == "buy" and bar["low"] <= stop)
                or (side == "sell" and bar["high"] >= stop)
            )
            exit_signal = should_exit_macd(side, bar)
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
                        reason="sl" if hit_stop else "channel",
                        bars_held=i - entry_i,
                    )
                )
                side = None

        if side is None:
            df_h4 = None
            if use_h4:
                k = int(closed_counts[i])
                df_h4 = h4.iloc[:k]
            sig = evaluate_macd_entry(data.iloc[: i + 1], df_h4, cfg)
            if sig.side is None:
                continue
            side = sig.side
            entry_price = sig.entry_ref + (
                slippage_price if side == "buy" else -slippage_price
            )
            entry_time = bar.name
            entry_i = i
            stop = sig.stop

    return _summary(trades)


def exit_reason_breakdown(trades: List[Trade]) -> dict:
    """Per-exit-reason aggregates: count, total pnl, win rate, avg bars held.

    Reveals whether the Donchian-channel safety exit is cutting winners
    short before the fib TP (many profitable 'channel' exits + few 'tp'),
    or whether stops dominate.
    """
    out: dict[str, dict] = {}
    for reason in ("tp", "sl", "channel"):
        rt = [t for t in trades if t.reason == reason]
        if not rt:
            continue
        pnls = np.array([t.pnl_price for t in rt])
        held = np.array([t.bars_held for t in rt])
        out[reason] = {
            "n": len(rt),
            "pnl": float(pnls.sum()),
            "win_rate": float((pnls > 0).mean()),
            "avg_bars_held": float(held.mean()),
        }
    return out


def _summary(trades: List[Trade]) -> dict:
    if not trades:
        return {"trades": [], "n": 0, "win_rate": 0.0, "total_pnl_price": 0.0,
                "exit_reasons": {}}
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
        "exit_reasons": exit_reason_breakdown(trades),
    }


def _max_drawdown(equity_curve: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity_curve)
    dd = equity_curve - peak
    return float(dd.min()) if len(dd) else 0.0
