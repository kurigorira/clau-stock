import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.strategy import (  # noqa: E402
    add_indicators,
    evaluate_fib_entry,
    fib_zone,
    swing_range,
)


def _fib_cfg() -> Config:
    cfg = Config()
    cfg.strategy = "fibonacci"
    cfg.trend.higher_timeframe = "H4"
    cfg.trend.ema_length = 20
    cfg.trend.ema_slope_lookback = 5
    cfg.filters.adx_min = 0.0
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
    return cfg


def _h4_ramp(n: int, start: float, step: float) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="4h", tz="UTC")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 100,
        },
        index=idx,
    )


def _h1_frame(closes: list[float], volumes: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    idx = pd.date_range("2025-02-01", periods=n, freq="h", tz="UTC")
    c = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": c - 0.2,
            "high": c + 0.5,
            "low": c - 0.5,
            "close": c,
            "volume": volumes if volumes is not None else [100.0] * n,
        },
        index=idx,
    )


def _buy_setup(cfg: Config, *, last_volume: float = 300.0, end_in_zone: bool = True):
    """H4 uptrend; H1 declines into the retrace zone then bounces twice."""
    h4 = add_indicators(_h4_ramp(60, start=1800.0, step=4.0), cfg)
    swing_high, swing_low = swing_range(h4, cfg.fibonacci.swing_lookback)
    zone_low, zone_high = fib_zone(
        swing_high, swing_low, 1, cfg.fibonacci.retrace_min, cfg.fibonacci.retrace_max
    )
    target = (zone_low + zone_high) / 2 if end_in_zone else swing_high + 5.0
    # 58 declining bars ending 3 below target, then a 2-bar bounce into target
    decline = np.linspace(target + 40.0, target - 3.0, 58)
    closes = list(decline) + [target - 1.5, target]
    volumes = [100.0] * 59 + [last_volume]
    h1 = add_indicators(_h1_frame(closes, volumes), cfg)
    return h1, h4, swing_high, swing_low


def test_fib_buy_on_pullback_bounce():
    cfg = _fib_cfg()
    h1, h4, swing_high, swing_low = _buy_setup(cfg)
    sig = evaluate_fib_entry(h1, h4, cfg)
    assert sig.side == "buy"
    assert sig.tp is not None and sig.tp > swing_high
    assert sig.stop < swing_low
    assert 0.0 < sig.fib_level < 1.0
    assert sig.h4_trend_dir == 1


def test_fib_rejects_outside_zone():
    cfg = _fib_cfg()
    h1, h4, _, _ = _buy_setup(cfg, end_in_zone=False)
    sig = evaluate_fib_entry(h1, h4, cfg)
    assert sig.side is None


def test_fib_rejects_without_bounce():
    cfg = _fib_cfg()
    h1, h4, swing_high, swing_low = _buy_setup(cfg)
    # break the bounce: force the final close below the previous one
    h1.iloc[-1, h1.columns.get_loc("close")] = float(h1["close"].iloc[-2]) - 1.0
    sig = evaluate_fib_entry(h1, h4, cfg)
    assert sig.side is None


def test_fib_rejects_low_volume():
    cfg = _fib_cfg()
    h1, h4, _, _ = _buy_setup(cfg, last_volume=100.0)  # == SMA, needs 1.2x
    sig = evaluate_fib_entry(h1, h4, cfg)
    assert sig.side is None


def test_fib_volume_filter_can_be_disabled():
    cfg = _fib_cfg()
    cfg.fibonacci.vol_mult = 0.0
    h1, h4, _, _ = _buy_setup(cfg, last_volume=100.0)
    sig = evaluate_fib_entry(h1, h4, cfg)
    assert sig.side == "buy"


def test_fib_rejects_falling_macd():
    cfg = _fib_cfg()
    h1, h4, _, _ = _buy_setup(cfg)
    # tamper the histogram so momentum reads as fading
    col = h1.columns.get_loc("macd_hist")
    h1.iloc[-1, col] = -1.0
    h1.iloc[-2, col] = 1.0
    sig = evaluate_fib_entry(h1, h4, cfg)
    assert sig.side is None


def test_fib_macd_filter_can_be_disabled():
    cfg = _fib_cfg()
    cfg.fibonacci.use_macd = False
    h1, h4, _, _ = _buy_setup(cfg)
    col = h1.columns.get_loc("macd_hist")
    h1.iloc[-1, col] = -1.0
    h1.iloc[-2, col] = 1.0
    sig = evaluate_fib_entry(h1, h4, cfg)
    assert sig.side == "buy"


def test_fib_sell_symmetric():
    cfg = _fib_cfg()
    h4 = add_indicators(_h4_ramp(60, start=2200.0, step=-4.0), cfg)
    swing_high, swing_low = swing_range(h4, cfg.fibonacci.swing_lookback)
    zone_low, zone_high = fib_zone(
        swing_high, swing_low, -1, cfg.fibonacci.retrace_min, cfg.fibonacci.retrace_max
    )
    target = (zone_low + zone_high) / 2
    rally = np.linspace(target - 40.0, target + 3.0, 58)
    closes = list(rally) + [target + 1.5, target]
    volumes = [100.0] * 59 + [300.0]
    h1 = add_indicators(_h1_frame(closes, volumes), cfg)
    sig = evaluate_fib_entry(h1, h4, cfg)
    assert sig.side == "sell"
    assert sig.tp is not None and sig.tp < swing_low
    assert sig.stop > swing_high


def test_fib_rejects_flat_h4():
    cfg = _fib_cfg()
    cfg.filters.adx_min = 1000.0  # H4 can never qualify as trending
    h1, h4, _, _ = _buy_setup(cfg)
    sig = evaluate_fib_entry(h1, h4, cfg)
    assert sig.side is None
    assert sig.h4_trend_dir == 0


def test_fib_none_h4_rejects():
    cfg = _fib_cfg()
    h1, _, _, _ = _buy_setup(cfg)
    sig = evaluate_fib_entry(h1, None, cfg)
    assert sig.side is None


def test_fib_zone_prices():
    lo, hi = fib_zone(200.0, 100.0, 1, 0.382, 0.786)
    assert abs(lo - (200.0 - 78.6)) < 1e-9
    assert abs(hi - (200.0 - 38.2)) < 1e-9
    lo, hi = fib_zone(200.0, 100.0, -1, 0.382, 0.786)
    assert abs(lo - (100.0 + 38.2)) < 1e-9
    assert abs(hi - (100.0 + 78.6)) < 1e-9
