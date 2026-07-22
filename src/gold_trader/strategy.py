from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from .config import Config


@dataclass
class Signal:
    side: Optional[str]   # "buy", "sell", or None
    stop: float
    entry_ref: float
    atr: float
    # Populated when MTF filtering is on; used by the notifier in the email body.
    donch_high: float = 0.0
    donch_low: float = 0.0
    h4_trend_dir: int = 0   # +1 / -1 / 0
    # Fibonacci-strategy fields. tp is None for donchian (no fixed target).
    tp: Optional[float] = None
    swing_high: float = 0.0
    swing_low: float = 0.0
    fib_level: float = 0.0  # retrace depth at entry (0.5 = the 50% level)


def h4_trend_dir(df_h4: pd.DataFrame, cfg: Config) -> int:
    """Return +1 / -1 / 0 from an indicator-enriched H4 frame.

    Uses the *last fully closed* H4 bar (df_h4.iloc[-1] after the executor
    has already dropped the still-forming bar). +1 when ema_slope > 0 and
    ADX >= adx_min, -1 when ema_slope < 0 and ADX >= adx_min, else 0.
    """
    if len(df_h4) == 0:
        return 0
    bar = df_h4.iloc[-1]
    ema_slope = float(bar["ema_slope"])
    adx = float(bar["adx"])
    if np.isnan(ema_slope) or np.isnan(adx):
        return 0
    if adx < cfg.filters.adx_min:
        return 0
    if ema_slope > 0:
        return 1
    if ema_slope < 0:
        return -1
    return 0


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def _atr(df: pd.DataFrame, length: int) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def _adx(df: pd.DataFrame, length: int) -> pd.Series:
    """Wilder's ADX, smoothed via EMA(alpha=1/length)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    prev_high = high.shift(1)
    prev_low = low.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    up_move = high - prev_high
    down_move = prev_low - low
    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
    )
    atr = tr.ewm(alpha=1 / length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / length, adjust=False).mean()


def _macd_hist(close: pd.Series, fast: int, slow: int, signal: int) -> pd.Series:
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line - signal_line


def _stoch_k(df: pd.DataFrame, k: int, smooth: int) -> pd.Series:
    """Slow stochastic %K in [0, 100]. Uses the current (closed) bar's
    high/low/close over the trailing k bars, so no shift is needed — we only
    ever read it on the last closed bar."""
    low_k = df["low"].rolling(k).min()
    high_k = df["high"].rolling(k).max()
    rng = (high_k - low_k).replace(0.0, np.nan)
    raw_k = 100.0 * (df["close"] - low_k) / rng
    return raw_k.rolling(smooth).mean()


def _regression_trend(close: pd.Series, length: int) -> tuple[pd.Series, pd.Series]:
    """Rolling least-squares fit of a straight line to the last `length` closes.

    Returns (slope_pct, r2), both aligned to `close`:
      * slope_pct — the fitted slope expressed as a fraction of the line's
        end-value per bar, so it is comparable across price scales.
      * r2 — coefficient of determination in [0, 1] (how linear the window is).

    Fully vectorised: within each window x runs 0..length-1, so the x-moments
    are constants and only the y-moments roll. Every window ends at the current
    bar, so no future data enters (read only on the last closed bar, like %K).
    """
    n = int(length)
    y = close.astype(float)
    j = pd.Series(np.arange(len(y), dtype=float), index=y.index)  # absolute bar idx
    Sy = y.rolling(n).sum()
    Syy = (y * y).rolling(n).sum()
    Sjy = (j * y).rolling(n).sum()
    j0 = j - (n - 1)                       # absolute index of each window's start
    Sxy = Sjy - j0 * Sy                    # cross-moment in window coords (x=0..n-1)
    Sx = n * (n - 1) / 2.0
    Sxx = (n - 1) * n * (2 * n - 1) / 6.0
    denom = n * Sxx - Sx * Sx
    slope = (n * Sxy - Sx * Sy) / denom    # price per bar
    line_end = Sy / n + slope * (n - 1) / 2.0   # fitted value at the last bar
    sst = Syy - Sy * Sy / n
    ssr = slope * slope * (Sxx - Sx * Sx / n)
    r2 = (ssr / sst.replace(0.0, np.nan)).clip(0.0, 1.0)
    slope_pct = slope / line_end.replace(0.0, np.nan)
    return slope_pct, r2


def add_indicators(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    out = df.copy()
    out["ema_trend"] = _ema(out["close"], cfg.trend.ema_length)
    out["ema_slope"] = (
        out["ema_trend"] - out["ema_trend"].shift(cfg.trend.ema_slope_lookback)
    )
    out["atr"] = _atr(out, cfg.risk.atr_length)
    out["atr_pct"] = out["atr"] / out["close"]
    out["adx"] = _adx(out, cfg.filters.adx_length)
    n = cfg.breakout.donchian_length
    m = cfg.breakout.exit_donchian_length
    # shift(1) so the channel reflects bars *prior* to the current one
    out["donch_high"] = out["high"].rolling(n).max().shift(1)
    out["donch_low"] = out["low"].rolling(n).min().shift(1)
    out["exit_high"] = out["high"].rolling(m).max().shift(1)
    out["exit_low"] = out["low"].rolling(m).min().shift(1)
    fib = cfg.fibonacci
    # The macd strategy tunes MACD via cfg.macd; every other strategy uses the
    # fib MACD params (fib reads macd_hist as one of its entry filters). This
    # keeps the two independent so tuning one never perturbs the other.
    if cfg.strategy == "macd":
        mf, ms, mg = cfg.macd.fast, cfg.macd.slow, cfg.macd.signal
    else:
        mf, ms, mg = fib.macd_fast, fib.macd_slow, fib.macd_signal
    out["macd_hist"] = _macd_hist(out["close"], mf, ms, mg)
    # Shared stochastic gate: computed for whichever strategy runs when enabled.
    if cfg.stoch.use:
        out["stoch_k"] = _stoch_k(out, cfg.stoch.k, cfg.stoch.smooth)
    # Shared regression-trendline gate: only computed when enabled.
    if cfg.trendline.use:
        out["tl_slope"], out["tl_r2"] = _regression_trend(
            out["close"], cfg.trendline.length
        )
    out["vol_sma"] = out["volume"].rolling(fib.vol_sma_length).mean().shift(1)
    return out


def stoch_blocks(side: str, bar: pd.Series, cfg: Config) -> bool:
    """True if the shared stochastic gate rejects this entry.

    Rejects a long once slow %K >= overbought and a short once %K <= oversold,
    so an entry never chases an already-exhausted move. A NaN %K (warm-up) or a
    missing column is treated as "unconfirmed" and blocks the entry. Callers
    must only invoke this when cfg.stoch.use is on (the column exists then)."""
    stoch = float(bar["stoch_k"]) if "stoch_k" in bar else float("nan")
    if np.isnan(stoch):
        return True
    if side == "buy":
        return stoch >= cfg.stoch.overbought
    return stoch <= cfg.stoch.oversold


def trendline_blocks(side: str, bar: pd.Series, cfg: Config) -> bool:
    """True if the regression-trendline gate rejects this entry.

    Blocks a long unless the trendline both rises (fractional slope per bar >
    slope_min) and fits cleanly (R² >= r2_min); mirror-image for a short. A NaN
    (warm-up) or missing column is "unconfirmed" and blocks, matching the
    stochastic gate. Callers must only invoke this when cfg.trendline.use is on."""
    slope = float(bar["tl_slope"]) if "tl_slope" in bar else float("nan")
    r2 = float(bar["tl_r2"]) if "tl_r2" in bar else float("nan")
    if np.isnan(slope) or np.isnan(r2):
        return True
    if r2 < cfg.trendline.r2_min:
        return True
    if side == "buy":
        return not (slope > cfg.trendline.slope_min)
    return not (slope < -cfg.trendline.slope_min)


def evaluate_last_bar(
    df: pd.DataFrame,
    cfg: Config,
    df_h4: Optional[pd.DataFrame] = None,
) -> Signal:
    """Return entry signal computed on the most recent *closed* bar.

    Conditions (long; short is symmetric):
      1. close > Donchian-high(N).shift(1) + ATR * atr_buffer_mult
      2. close > EMA(trend)
      3. EMA(trend) now > EMA(trend) ema_slope_lookback bars ago
      4. ADX(adx_length) >= adx_min
      5. atr_pct_min <= ATR / close <= atr_pct_max
      6. (when df_h4 is given and cfg.trend.higher_timeframe is set)
         signal side agrees with the H4 trend direction
    Daily-loss / consecutive-loss filters are enforced at the executor layer
    because they need account history. df_h4=None preserves the legacy
    H1-only behaviour for tests that don't supply an H4 frame.
    """
    warmup = max(
        cfg.trend.ema_length,
        cfg.breakout.donchian_length,
        cfg.filters.adx_length * 2,
        cfg.trend.ema_slope_lookback + 1,
    )
    if len(df) < warmup + 2:
        return Signal(None, 0.0, 0.0, 0.0)

    bar = df.iloc[-1]
    close = float(bar["close"])
    ema = float(bar["ema_trend"])
    ema_slope = float(bar["ema_slope"])
    atr = float(bar["atr"])
    atr_pct = float(bar["atr_pct"])
    adx = float(bar["adx"])
    high_ref = float(bar["donch_high"])
    low_ref = float(bar["donch_low"])

    if any(
        np.isnan(x)
        for x in (atr, atr_pct, adx, ema, ema_slope, high_ref, low_ref)
    ):
        safe_atr = 0.0 if np.isnan(atr) else atr
        return Signal(None, 0.0, close, safe_atr)

    f = cfg.filters
    if not (f.atr_pct_min <= atr_pct <= f.atr_pct_max):
        return Signal(None, 0.0, close, atr)
    if adx < f.adx_min:
        return Signal(None, 0.0, close, atr)

    buffer = cfg.breakout.atr_buffer_mult * atr
    stop_dist = cfg.risk.atr_stop_mult * atr

    h4_dir = h4_trend_dir(df_h4, cfg) if (df_h4 is not None and cfg.trend.higher_timeframe) else 0
    mtf_on = df_h4 is not None and cfg.trend.higher_timeframe

    if close > high_ref + buffer and close > ema and ema_slope > 0:
        if mtf_on and h4_dir != 1:
            return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)
        if cfg.stoch.use and stoch_blocks("buy", bar, cfg):
            return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)
        if cfg.trendline.use and trendline_blocks("buy", bar, cfg):
            return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)
        return Signal("buy", close - stop_dist, close, atr, high_ref, low_ref, h4_dir)
    if close < low_ref - buffer and close < ema and ema_slope < 0:
        if mtf_on and h4_dir != -1:
            return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)
        if cfg.stoch.use and stoch_blocks("sell", bar, cfg):
            return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)
        if cfg.trendline.use and trendline_blocks("sell", bar, cfg):
            return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)
        return Signal("sell", close + stop_dist, close, atr, high_ref, low_ref, h4_dir)
    return Signal(None, 0.0, close, atr, high_ref, low_ref, h4_dir)


def should_exit(position_side: str, bar: pd.Series) -> bool:
    """Donchian reverse-channel exit: long exits below recent low, vice versa."""
    close = float(bar["close"])
    if position_side == "buy":
        ref = float(bar["exit_low"])
        return not np.isnan(ref) and close < ref
    ref = float(bar["exit_high"])
    return not np.isnan(ref) and close > ref


# ---------------------------------------------------------------------------
# Fibonacci strategy (strategy: "fibonacci")
# ---------------------------------------------------------------------------


def swing_range(df_h4: pd.DataFrame, lookback: int) -> tuple[float, float]:
    """High/low of the last `lookback` (closed) H4 bars."""
    tail = df_h4.iloc[-lookback:]
    return float(tail["high"].max()), float(tail["low"].min())


def fib_zone(
    swing_high: float,
    swing_low: float,
    direction: int,
    retrace_min: float,
    retrace_max: float,
) -> tuple[float, float]:
    """Price band of the retrace zone as (zone_low, zone_high).

    direction +1: uptrend — the pullback zone hangs below the swing high.
    direction -1: downtrend — the bounce zone sits above the swing low.
    """
    rng = swing_high - swing_low
    if direction == 1:
        return swing_high - retrace_max * rng, swing_high - retrace_min * rng
    return swing_low + retrace_min * rng, swing_low + retrace_max * rng


def evaluate_fib_entry(
    df_h1: pd.DataFrame,
    df_h4: Optional[pd.DataFrame],
    cfg: Config,
) -> Signal:
    """Fibonacci pullback entry on the most recent *closed* H1 bar.

    Long (short symmetric):
      1. H4 trend dir == +1 (EMA slope up, H4 ADX >= adx_min)
      2. H1 low or close inside the retrace_min..retrace_max zone of the
         H4 swing (last swing_lookback closed H4 bars)
      3. last `bounce_bars` H1 closes strictly rising
      4. H1 volume >= vol_mult * SMA(volume) (vol_mult=0 disables)
      5. MACD histogram rising vs previous bar (use_macd=false disables)
      6. atr_pct sanity band from cfg.filters
    SL beyond the swing extreme by stop_atr_buffer*ATR; TP at extension_tp.
    """
    fib = cfg.fibonacci
    need_h1 = max(fib.bounce_bars + 1, fib.vol_sma_length + 1, fib.macd_slow + fib.macd_signal)
    if df_h4 is None or len(df_h4) < fib.swing_lookback or len(df_h1) < need_h1:
        return Signal(None, 0.0, 0.0, 0.0)

    dir_h4 = h4_trend_dir(df_h4, cfg)
    if dir_h4 == 0:
        bar = df_h1.iloc[-1]
        return Signal(None, 0.0, float(bar["close"]), float(bar["atr"]), h4_trend_dir=0)

    swing_high, swing_low = swing_range(df_h4, fib.swing_lookback)
    rng = swing_high - swing_low
    bar = df_h1.iloc[-1]
    close = float(bar["close"])
    atr = float(bar["atr"])
    atr_pct = float(bar["atr_pct"])
    if rng <= 0 or np.isnan(atr) or np.isnan(atr_pct):
        return Signal(None, 0.0, close, 0.0 if np.isnan(atr) else atr, h4_trend_dir=dir_h4)

    no_trade = Signal(
        None, 0.0, close, atr,
        h4_trend_dir=dir_h4, swing_high=swing_high, swing_low=swing_low,
    )

    f = cfg.filters
    if not (f.atr_pct_min <= atr_pct <= f.atr_pct_max):
        return no_trade

    zone_low, zone_high = fib_zone(
        swing_high, swing_low, dir_h4, fib.retrace_min, fib.retrace_max
    )
    low = float(bar["low"])
    high = float(bar["high"])
    in_zone = (zone_low <= low <= zone_high) or (zone_low <= close <= zone_high) or (
        zone_low <= high <= zone_high
    )
    if not in_zone:
        return no_trade

    closes = df_h1["close"].iloc[-(fib.bounce_bars + 1):].to_numpy(dtype=float)
    diffs = np.diff(closes)
    bounce = (diffs > 0).all() if dir_h4 == 1 else (diffs < 0).all()
    if not bounce:
        return no_trade

    if fib.vol_mult > 0:
        vol = float(bar["volume"])
        vol_sma = float(bar["vol_sma"])
        if np.isnan(vol_sma) or vol < fib.vol_mult * vol_sma:
            return no_trade

    if fib.use_macd:
        hist_now = float(df_h1["macd_hist"].iloc[-1])
        hist_prev = float(df_h1["macd_hist"].iloc[-2])
        if np.isnan(hist_now) or np.isnan(hist_prev):
            return no_trade
        momentum_ok = hist_now > hist_prev if dir_h4 == 1 else hist_now < hist_prev
        if not momentum_ok:
            return no_trade

    side = "buy" if dir_h4 == 1 else "sell"
    if cfg.stoch.use and stoch_blocks(side, bar, cfg):
        return no_trade
    if cfg.trendline.use and trendline_blocks(side, bar, cfg):
        return no_trade

    ext = fib.extension_tp - 1.0
    if dir_h4 == 1:
        stop = swing_low - fib.stop_atr_buffer * atr
        tp = swing_high + ext * rng
        fib_level = (swing_high - close) / rng
        return Signal(
            "buy", stop, close, atr,
            h4_trend_dir=dir_h4, tp=tp,
            swing_high=swing_high, swing_low=swing_low, fib_level=fib_level,
        )
    stop = swing_high + fib.stop_atr_buffer * atr
    tp = swing_low - ext * rng
    fib_level = (close - swing_low) / rng
    return Signal(
        "sell", stop, close, atr,
        h4_trend_dir=dir_h4, tp=tp,
        swing_high=swing_high, swing_low=swing_low, fib_level=fib_level,
    )


# ---------------------------------------------------------------------------
# MACD strategy (strategy: "macd")
# ---------------------------------------------------------------------------


def evaluate_macd_entry(
    df_h1: pd.DataFrame,
    df_h4: Optional[pd.DataFrame],
    cfg: Config,
) -> Signal:
    """MACD/signal cross entry on the most recent closed H1 bar.

    Long: macd_hist flips from <=0 (prev bar) to >0 (this bar). Short is the
    mirror. When cfg.macd.use_h4_filter is on, the cross must agree with the
    H4 trend direction. SL = close -/+ risk.atr_stop_mult * ATR; no fixed TP
    (the position rides until the opposite cross — see should_exit_macd).
    """
    if len(df_h1) < 2:
        return Signal(None, 0.0, 0.0, 0.0)

    bar = df_h1.iloc[-1]
    close = float(bar["close"])
    atr = float(bar["atr"])
    atr_pct = float(bar["atr_pct"])
    hist_now = float(df_h1["macd_hist"].iloc[-1])
    hist_prev = float(df_h1["macd_hist"].iloc[-2])
    if any(np.isnan(x) for x in (atr, atr_pct, hist_now, hist_prev)):
        return Signal(None, 0.0, close, 0.0 if np.isnan(atr) else atr)

    f = cfg.filters
    if not (f.atr_pct_min <= atr_pct <= f.atr_pct_max):
        return Signal(None, 0.0, close, atr)

    cross_up = hist_prev <= 0 < hist_now
    cross_down = hist_prev >= 0 > hist_now
    if not (cross_up or cross_down):
        return Signal(None, 0.0, close, atr)

    # Shared stochastic confirmation: don't chase an already-extended move.
    if cfg.stoch.use and stoch_blocks("buy" if cross_up else "sell", bar, cfg):
        return Signal(None, 0.0, close, atr)
    if cfg.trendline.use and trendline_blocks("buy" if cross_up else "sell", bar, cfg):
        return Signal(None, 0.0, close, atr)

    dir_h4 = 0
    if cfg.macd.use_h4_filter and cfg.trend.higher_timeframe:
        if df_h4 is None:
            return Signal(None, 0.0, close, atr)
        dir_h4 = h4_trend_dir(df_h4, cfg)
        if cross_up and dir_h4 != 1:
            return Signal(None, 0.0, close, atr, h4_trend_dir=dir_h4)
        if cross_down and dir_h4 != -1:
            return Signal(None, 0.0, close, atr, h4_trend_dir=dir_h4)

    stop_dist = cfg.risk.atr_stop_mult * atr
    if cross_up:
        return Signal("buy", close - stop_dist, close, atr, h4_trend_dir=dir_h4)
    return Signal("sell", close + stop_dist, close, atr, h4_trend_dir=dir_h4)


def should_exit_macd(position_side: str, bar: pd.Series) -> bool:
    """MACD opposite-cross exit: a long exits once the histogram is no longer
    positive, a short once it is no longer negative."""
    hist = float(bar["macd_hist"])
    if np.isnan(hist):
        return False
    if position_side == "buy":
        return hist <= 0
    return hist >= 0
