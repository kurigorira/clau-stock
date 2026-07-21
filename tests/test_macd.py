import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import backtest as bt  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.strategy import (  # noqa: E402
    add_indicators,
    evaluate_macd_entry,
    should_exit_macd,
)


def _macd_cfg(use_h4: bool = False) -> Config:
    cfg = Config()
    cfg.strategy = "macd"
    cfg.macd.use_h4_filter = use_h4
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
    cfg.filters.adx_min = 0.0
    return cfg


def _frame_from_close(close: np.ndarray, cfg: Config) -> pd.DataFrame:
    n = len(close)
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    df = pd.DataFrame(
        {"open": close - 0.1, "high": close + 0.5, "low": close - 0.5,
         "close": close, "volume": 100},
        index=idx,
    )
    return add_indicators(df, cfg)


def _bullish_cross_series() -> np.ndarray:
    # long downtrend (MACD hist negative) then a sharp rally that flips hist +
    down = np.linspace(1200, 1000, 200)
    up = np.linspace(1000, 1120, 40)
    return np.concatenate([down, up])


def _bearish_cross_series() -> np.ndarray:
    up = np.linspace(1000, 1200, 200)
    down = np.linspace(1200, 1080, 40)
    return np.concatenate([up, down])


def _find_cross(df: pd.DataFrame, kind: str) -> int:
    h = df["macd_hist"].to_numpy()
    for i in range(1, len(h)):
        if np.isnan(h[i]) or np.isnan(h[i - 1]):
            continue
        if kind == "up" and h[i - 1] <= 0 < h[i]:
            return i
        if kind == "down" and h[i - 1] >= 0 > h[i]:
            return i
    return -1


# ---------------------------------------------------------------------------
# entry
# ---------------------------------------------------------------------------


def test_macd_bullish_cross_signals_buy():
    cfg = _macd_cfg()
    df = _frame_from_close(_bullish_cross_series(), cfg)
    i = _find_cross(df, "up")
    assert i > 0
    sig = evaluate_macd_entry(df.iloc[: i + 1], None, cfg)
    assert sig.side == "buy"
    assert sig.stop < sig.entry_ref
    assert sig.tp is None


def test_macd_bearish_cross_signals_sell():
    cfg = _macd_cfg()
    df = _frame_from_close(_bearish_cross_series(), cfg)
    i = _find_cross(df, "down")
    assert i > 0
    sig = evaluate_macd_entry(df.iloc[: i + 1], None, cfg)
    assert sig.side == "sell"
    assert sig.stop > sig.entry_ref


def test_macd_no_cross_no_signal():
    cfg = _macd_cfg()
    # steady uptrend: hist stays positive after warmup, no fresh cross at the end
    df = _frame_from_close(np.linspace(1000, 1400, 300), cfg)
    sig = evaluate_macd_entry(df, None, cfg)
    assert sig.side is None


def test_macd_atr_pct_filter_blocks():
    cfg = _macd_cfg()
    cfg.filters.atr_pct_min = 0.5  # impossible floor
    df = _frame_from_close(_bullish_cross_series(), cfg)
    i = _find_cross(df, "up")
    sig = evaluate_macd_entry(df.iloc[: i + 1], None, cfg)
    assert sig.side is None


# ---------------------------------------------------------------------------
# H4 filter
# ---------------------------------------------------------------------------


def _h4_up(cfg: Config) -> pd.DataFrame:
    close = np.linspace(1000, 2000, 60)
    idx = pd.date_range("2025-01-01", periods=60, freq="4h", tz="UTC")
    df = pd.DataFrame(
        {"open": close - 0.5, "high": close + 0.5, "low": close - 0.5,
         "close": close, "volume": 100},
        index=idx,
    )
    return add_indicators(df, cfg)


def _h4_down(cfg: Config) -> pd.DataFrame:
    close = np.linspace(2000, 1000, 60)
    idx = pd.date_range("2025-01-01", periods=60, freq="4h", tz="UTC")
    df = pd.DataFrame(
        {"open": close + 0.5, "high": close + 0.5, "low": close - 0.5,
         "close": close, "volume": 100},
        index=idx,
    )
    return add_indicators(df, cfg)


def test_macd_h4_filter_blocks_buy_against_downtrend():
    cfg = _macd_cfg(use_h4=True)
    df = _frame_from_close(_bullish_cross_series(), cfg)
    i = _find_cross(df, "up")
    sig = evaluate_macd_entry(df.iloc[: i + 1], _h4_down(cfg), cfg)
    assert sig.side is None


def test_macd_h4_filter_allows_buy_with_uptrend():
    cfg = _macd_cfg(use_h4=True)
    df = _frame_from_close(_bullish_cross_series(), cfg)
    i = _find_cross(df, "up")
    sig = evaluate_macd_entry(df.iloc[: i + 1], _h4_up(cfg), cfg)
    assert sig.side == "buy"


def test_macd_pure_ignores_h4():
    cfg = _macd_cfg(use_h4=False)
    df = _frame_from_close(_bullish_cross_series(), cfg)
    i = _find_cross(df, "up")
    # even with a conflicting H4 down frame, pure macd fires
    sig = evaluate_macd_entry(df.iloc[: i + 1], _h4_down(cfg), cfg)
    assert sig.side == "buy"


# ---------------------------------------------------------------------------
# exit
# ---------------------------------------------------------------------------


def test_should_exit_macd_long_on_negative_hist():
    assert should_exit_macd("buy", pd.Series({"macd_hist": -0.5})) is True
    assert should_exit_macd("buy", pd.Series({"macd_hist": 0.5})) is False


def test_should_exit_macd_short_on_positive_hist():
    assert should_exit_macd("sell", pd.Series({"macd_hist": 0.5})) is True
    assert should_exit_macd("sell", pd.Series({"macd_hist": -0.5})) is False


def test_should_exit_macd_nan_stays_in():
    assert should_exit_macd("buy", pd.Series({"macd_hist": np.nan})) is False


# ---------------------------------------------------------------------------
# backtest
# ---------------------------------------------------------------------------


def _h1(n: int, start: float = 1000.0, step: float = 0.5) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    close = start + np.arange(n) * step
    return pd.DataFrame(
        {"open": close - 0.2, "high": close + 1.0, "low": close - 1.0,
         "close": close, "volume": 100},
        index=idx,
    )


def test_macd_backtest_runs_and_reports_reasons():
    cfg = Config()
    cfg.strategy = "macd"
    cfg.macd.use_h4_filter = False
    # oscillating series produces crosses in both directions
    t = np.arange(600)
    close = 1000 + 50 * np.sin(t / 15.0)
    df = pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 100},
        index=pd.date_range("2025-01-01", periods=len(close), freq="h", tz="UTC"),
    )
    result = bt.run_backtest(df, cfg)
    assert "exit_reasons" in result
    assert result["n"] >= 1
    for tr in result["trades"]:
        assert tr.reason in ("sl", "channel")  # macd exits: opposite-cross or stop


def test_macd_backtest_no_lookahead_when_h4_filter_on():
    cfg = Config()
    cfg.strategy = "macd"
    cfg.macd.use_h4_filter = True
    violations = []

    def spy(df_h1, df_h4, c):
        from gold_trader.strategy import Signal
        t_h1 = df_h1.index[-1]
        if df_h4 is not None and len(df_h4) and df_h4.index[-1] > t_h1 - pd.Timedelta(hours=3):
            violations.append((t_h1, df_h4.index[-1]))
        return Signal(None, 0.0, 0.0, 0.0)

    with patch.object(bt, "evaluate_macd_entry", side_effect=spy):
        bt.run_backtest(_h1(200), cfg)
    assert not violations


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------


def test_config_macd_strategy_valid():
    cfg = Config(strategy="macd")
    assert cfg.strategy == "macd"
    assert cfg.macd.fast == 12


def test_config_macd_presets_parse():
    config_dir = Path(__file__).resolve().parents[1] / "config"
    for name in ("macd_example.yaml", "macd_pure.yaml"):
        cfg = Config.from_yaml(config_dir / name)
        assert cfg.strategy == "macd"
    assert Config.from_yaml(config_dir / "macd_pure.yaml").macd.use_h4_filter is False
    assert Config.from_yaml(config_dir / "macd_example.yaml").macd.use_h4_filter is True


def test_macd_params_independent_from_fib():
    # add_indicators must use cfg.macd params under macd strategy, cfg.fibonacci otherwise
    cfg = Config()
    cfg.strategy = "macd"
    cfg.macd.fast, cfg.macd.slow, cfg.macd.signal = 5, 10, 3
    cfg.fibonacci.macd_fast, cfg.fibonacci.macd_slow = 12, 26
    df = _h1(120)
    macd_hist = add_indicators(df, cfg)["macd_hist"]
    cfg.strategy = "fibonacci"
    fib_hist = add_indicators(df, cfg)["macd_hist"]
    # different params -> different histogram series
    assert not np.allclose(
        macd_hist.dropna().to_numpy()[-20:], fib_hist.dropna().to_numpy()[-20:]
    )
