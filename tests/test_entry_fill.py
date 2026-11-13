import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import backtest as bt  # noqa: E402
from gold_trader.config import Config  # noqa: E402


def _frame(n=600, seed=5, gap=0.0):
    """H1 bars. `gap` shifts every open away from the previous close, which is
    exactly the cost the live bot pays and the close-fill backtest ignores."""
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.standard_normal(n) * 0.3 + 0.01)
    open_ = np.concatenate([[close[0]], close[:-1] + gap])
    return pd.DataFrame(
        {"open": open_, "high": np.maximum(open_, close) + 0.4,
         "low": np.minimum(open_, close) - 0.4, "close": close, "volume": 1000},
        index=idx,
    )


def _cfg(strategy="macd"):
    cfg = Config()
    cfg.strategy = strategy
    cfg.filters.adx_min = 0.0
    cfg.filters.atr_pct_min = 0.0
    cfg.filters.atr_pct_max = 1.0
    if strategy == "macd":
        cfg.macd.use_h4_filter = False
    return cfg


# --- the option itself ------------------------------------------------------

def test_default_is_the_historical_close_fill():
    df, cfg = _frame(), _cfg()
    assert (bt.run_backtest(df, cfg)["trades"][0].entry_price
            == bt.run_backtest(df, cfg, entry_fill="close")["trades"][0].entry_price)


def test_unknown_fill_mode_is_rejected():
    with pytest.raises(ValueError, match="entry_fill"):
        bt.run_backtest(_frame(), _cfg(), entry_fill="tomorrow")


@pytest.mark.parametrize("strategy", ["macd", "donchian", "fibonacci", "bollrci"])
def test_every_strategy_accepts_both_fills(strategy):
    df, cfg = _frame(), _cfg(strategy)
    for mode in ("close", "next_open"):
        res = bt.run_backtest(df, cfg, entry_fill=mode)
        assert isinstance(res["n"], int)


# --- what next_open actually changes ---------------------------------------

def test_next_open_fills_at_the_following_bar_open():
    df, cfg = _frame(), _cfg()
    trades = bt.run_backtest(df, cfg, entry_fill="next_open")["trades"]
    assert trades, "fixture produced no trades"
    for t in trades[:5]:
        nxt = df.index[df.index.get_loc(t.entry_time) + 1]
        assert t.entry_price == pytest.approx(float(df.loc[nxt, "open"]))


def test_close_fill_uses_the_signal_bar_close():
    df, cfg = _frame(), _cfg()
    trades = bt.run_backtest(df, cfg, entry_fill="close")["trades"]
    assert trades
    for t in trades[:5]:
        assert t.entry_price == pytest.approx(float(df.loc[t.entry_time, "close"]))


def test_the_stop_does_not_move_with_the_fill():
    # the point of the whole exercise: a worse fill leaves less room in front
    # of a stop that stays where the signal bar put it
    df, cfg = _frame(), _cfg()
    a = {t.entry_time: t.stop for t in bt.run_backtest(df, cfg)["trades"]}
    b = {t.entry_time: t.stop for t in
         bt.run_backtest(df, cfg, entry_fill="next_open")["trades"]}
    shared = set(a) & set(b)
    assert shared
    for k in shared:
        assert a[k] == pytest.approx(b[k])


def test_a_gap_costs_longs_and_pays_shorts_by_the_same_amount():
    # Every open sits 0.5 above the prior close, so a long fills 0.5 worse and
    # a short 0.5 better. Net PnL cancels across a direction-balanced strategy
    # like MACD - which is why the aggregate alone would say nothing. The cost
    # is only visible per direction, and live it bites because the gap follows
    # the signal rather than pointing one fixed way.
    df, cfg = _frame(gap=0.5), _cfg()
    a = {t.entry_time: t for t in bt.run_backtest(df, cfg)["trades"]}
    b = {t.entry_time: t for t in
         bt.run_backtest(df, cfg, entry_fill="next_open")["trades"]}
    longs = shorts = 0
    for k in set(a) & set(b):
        if a[k].exit_time != b[k].exit_time:
            continue                       # a different fill can end elsewhere
        if a[k].side == "buy":
            assert b[k].pnl_price < a[k].pnl_price
            longs += 1
        else:
            assert b[k].pnl_price > a[k].pnl_price
            shorts += 1
    assert longs and shorts, "fixture needs trades in both directions"


def test_no_trade_is_opened_on_the_final_bar():
    # there is no next bar to fill on; the run must simply not take it
    df, cfg = _frame(), _cfg()
    for t in bt.run_backtest(df, cfg, entry_fill="next_open")["trades"]:
        assert t.entry_time != df.index[-1]
