import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import backtest as bt  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.strategy import (  # noqa: E402
    _rci,
    add_indicators,
    evaluate_bollrci_entry,
    evaluate_kairi_entry,
    should_exit_bollrci,
    should_exit_kairi,
)


def _series(vals) -> pd.Series:
    idx = pd.date_range("2025-01-01", periods=len(vals), freq="h", tz="UTC")
    return pd.Series(np.asarray(vals, dtype=float), index=idx)


def _frame(closes, spread=0.3) -> pd.DataFrame:
    c = np.asarray(closes, dtype=float)
    idx = pd.date_range("2025-01-01", periods=len(c), freq="h", tz="UTC")
    return pd.DataFrame(
        {"open": c, "high": c + spread, "low": c - spread,
         "close": c, "volume": 100},
        index=idx,
    )


def _h4_ramp(step: float) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=60, freq="4h", tz="UTC")
    c = 1000.0 + np.arange(60) * step
    return pd.DataFrame(
        {"open": c, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 100},
        index=idx,
    )


def _cfg(strategy: str) -> Config:
    cfg = Config()
    cfg.strategy = strategy
    cfg.trend.ema_length = 20
    cfg.trend.ema_slope_lookback = 5
    cfg.filters.adx_min = 0.0
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
    return cfg


# --- RCI --------------------------------------------------------------------

def test_rci_extremes_and_warmup():
    up = _series(np.arange(30.0))
    dn = _series(np.arange(30.0)[::-1].copy())
    assert _rci(up, 9).iloc[-1] == 100.0
    assert _rci(dn, 9).iloc[-1] == -100.0
    assert _rci(up, 9).isna().sum() == 8          # first length-1 undefined


def test_rci_range_bounded():
    rng = np.random.default_rng(0)
    r = _rci(_series(100 + rng.standard_normal(200)), 9).dropna()
    assert (r <= 100).all() and (r >= -100).all()


# --- kairi ------------------------------------------------------------------

def _kairi_buy_frame():
    # flat, then a slide that stretches price well below the 25-bar MA while
    # keeping bar ranges (ATR) small
    closes = [100.0] * 40 + [99.5, 99.0, 98.0, 96.5, 95.0]
    return _frame(closes)


def test_kairi_stretched_below_ma_buys():
    cfg = _cfg("kairi")
    cfg.kairi.use_h4_filter = False
    df = add_indicators(_kairi_buy_frame(), cfg)
    sig = evaluate_kairi_entry(df, None, cfg)
    assert sig.side == "buy"
    assert sig.stop < sig.entry_ref


def test_kairi_flat_price_no_trade():
    cfg = _cfg("kairi")
    cfg.kairi.use_h4_filter = False
    df = add_indicators(_frame([100.0] * 60), cfg)
    assert evaluate_kairi_entry(df, None, cfg).side is None


def test_kairi_sell_mirror():
    cfg = _cfg("kairi")
    cfg.kairi.use_h4_filter = False
    closes = [100.0] * 40 + [100.5, 101.0, 102.0, 103.5, 105.0]
    df = add_indicators(_frame(closes), cfg)
    assert evaluate_kairi_entry(df, None, cfg).side == "sell"


def test_kairi_h4_filter_blocks_dip_buy_in_downtrend():
    cfg = _cfg("kairi")
    cfg.kairi.use_h4_filter = True
    df = add_indicators(_kairi_buy_frame(), cfg)
    h4_dn = add_indicators(_h4_ramp(-4.0), cfg)
    h4_up = add_indicators(_h4_ramp(+4.0), cfg)
    assert evaluate_kairi_entry(df, h4_dn, cfg).side is None   # knife-catching blocked
    assert evaluate_kairi_entry(df, h4_up, cfg).side == "buy"  # dip in uptrend ok
    assert evaluate_kairi_entry(df, None, cfg).side is None    # no H4 -> no trade


def test_kairi_exit_at_ma():
    assert should_exit_kairi("buy", pd.Series({"close": 100.0, "kairi_ma": 100.0}))
    assert not should_exit_kairi("buy", pd.Series({"close": 99.0, "kairi_ma": 100.0}))
    assert should_exit_kairi("sell", pd.Series({"close": 100.0, "kairi_ma": 100.0}))
    assert not should_exit_kairi("sell", pd.Series({"close": 101.0, "kairi_ma": 100.0}))
    assert not should_exit_kairi("buy", pd.Series({"close": 99.0, "kairi_ma": np.nan}))


# --- bollrci ----------------------------------------------------------------

def _bollrci_buy_frame():
    # flat, then nine strictly-declining bars with growing steps: the last
    # close pierces the lower band while RCI(9) sits at -100
    steps = [0.05, 0.07, 0.1, 0.15, 0.25, 0.4, 0.7, 1.2, 2.0]
    closes = [100.0] * 30 + list(100.0 - np.cumsum(steps))
    return _frame(closes)


def test_bollrci_band_plus_rci_buys():
    cfg = _cfg("bollrci")
    cfg.bollrci.use_h4_filter = False
    df = add_indicators(_bollrci_buy_frame(), cfg)
    # fixture sanity: both conditions genuinely hold
    last = df.iloc[-1]
    assert last["close"] < last["bb_lo"]
    assert last["rci"] <= -80
    sig = evaluate_bollrci_entry(df, None, cfg)
    assert sig.side == "buy"
    assert sig.stop < sig.entry_ref


def test_bollrci_rci_required():
    cfg = _cfg("bollrci")
    cfg.bollrci.use_h4_filter = False
    cfg.bollrci.rci_threshold = 101.0   # unreachable -> RCI can never confirm
    df = add_indicators(_bollrci_buy_frame(), cfg)
    assert evaluate_bollrci_entry(df, None, cfg).side is None


def test_bollrci_band_required():
    cfg = _cfg("bollrci")
    cfg.bollrci.use_h4_filter = False
    cfg.bollrci.rci_threshold = 0.0
    # constant-step decline: RCI = -100 but price never leaves the band
    closes = list(100.0 - 0.2 * np.arange(40))
    df = add_indicators(_frame(closes), cfg)
    last = df.iloc[-1]
    assert last["rci"] == -100.0
    assert last["close"] >= last["bb_lo"]
    assert evaluate_bollrci_entry(df, None, cfg).side is None


def test_bollrci_exit_at_mid():
    assert should_exit_bollrci("buy", pd.Series({"close": 100.0, "bb_mid": 100.0}))
    assert not should_exit_bollrci("buy", pd.Series({"close": 99.0, "bb_mid": 100.0}))
    assert should_exit_bollrci("sell", pd.Series({"close": 99.0, "bb_mid": 100.0}))


# --- backtest integration ---------------------------------------------------

def _wave(n=700):
    t = np.arange(n)
    return _frame(100 + 8 * np.sin(t / 10.0), spread=0.5)


def test_kairi_backtest_runs_and_reports_reasons():
    cfg = _cfg("kairi")
    cfg.kairi.use_h4_filter = False
    cfg.kairi.threshold_atr_mult = 1.5
    r = bt.run_backtest(_wave(), cfg)
    assert r["n"] > 0
    assert all(t.reason in ("sl", "channel") for t in r["trades"])


def test_bollrci_backtest_runs_and_reports_reasons():
    cfg = _cfg("bollrci")
    cfg.bollrci.use_h4_filter = False
    cfg.bollrci.rci_threshold = 50.0
    r = bt.run_backtest(_wave(), cfg)
    assert r["n"] > 0
    assert all(t.reason in ("sl", "channel") for t in r["trades"])


def test_meanrev_slippage_reduces_pnl():
    cfg = _cfg("kairi")
    cfg.kairi.use_h4_filter = False
    cfg.kairi.threshold_atr_mult = 1.5
    free = bt.run_backtest(_wave(), cfg)
    costly = bt.run_backtest(_wave(), cfg, slippage_price=0.05)
    assert costly["total_pnl_price"] < free["total_pnl_price"]


# --- config -----------------------------------------------------------------

def test_config_accepts_new_strategies(tmp_path):
    for name in ("kairi", "bollrci"):
        assert Config(strategy=name).strategy == name
    y = tmp_path / "k.yaml"
    y.write_text(
        "symbol: AAPL\nstrategy: kairi\n"
        "kairi:\n  ma_length: 30\n  threshold_atr_mult: 2.5\n  use_h4_filter: false\n"
        "bollrci:\n  rci_length: 13\n  rci_threshold: 70\n",
        encoding="utf-8",
    )
    c = Config.from_yaml(y)
    assert (c.kairi.ma_length, c.kairi.threshold_atr_mult, c.kairi.use_h4_filter) == (30, 2.5, False)
    assert (c.bollrci.rci_length, c.bollrci.rci_threshold) == (13, 70)
