import logging
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import executor as executor_mod  # noqa: E402
from gold_trader.breadth import (  # noqa: E402
    US_STOCKS,
    discover_universe,
    live_net_breadth,
)
from gold_trader.config import Config  # noqa: E402
from gold_trader.executor import Executor  # noqa: E402


# --- discover_universe ------------------------------------------------------

def test_discover_universe_filters_and_dedupes():
    names = ["EURUSD", "XAUUSD", "NVIDIA.24h", "NVIDIA", "AAPL", "BTCUSD", "Boeing"]
    got = discover_universe(names)
    # non-members dropped; NVIDIA venue duplicate deduped to the shortest name
    assert got == ["NVIDIA", "AAPL", "Boeing"]


def test_discover_universe_keeps_24h_when_only_feed():
    assert discover_universe(["NVIDIA.24h", "GS"]) == ["NVIDIA.24h", "GS"]


def test_discover_universe_empty():
    assert discover_universe(["EURUSD", "US500"]) == []


# --- live_net_breadth -------------------------------------------------------

BAR_T = pd.Timestamp("2025-06-02 15:00", tz="UTC")
LB = 5


def _feed(highs, lows, end=BAR_T, forming=True):
    """OHLCV frame ending at `end`; appends a still-forming bar when asked."""
    n = len(highs)
    idx = pd.date_range(end=end, periods=n, freq="h", tz="UTC")
    df = pd.DataFrame(
        {"open": lows, "high": highs, "low": lows,
         "close": [(h + l) / 2 for h, l in zip(highs, lows)], "volume": 100},
        index=idx,
    )
    if forming:
        nxt = df.iloc[[-1]].copy()
        nxt.index = [end + pd.Timedelta(hours=1)]
        df = pd.concat([df, nxt])
    return df


def test_live_net_breadth_counts_highs_and_lows():
    feeds = {
        # last closed bar breaks above the prior 5-bar high -> +1
        "UP": _feed([10, 10, 10, 10, 10, 11], [9, 9, 9, 9, 9, 9.5]),
        # breaks below the prior low -> -1
        "DN": _feed([10, 10, 10, 10, 10, 10], [9, 9, 9, 9, 9, 8]),
        # inside bar -> 0
        "FLAT": _feed([10, 10, 10, 10, 10, 10], [9, 9, 9, 9, 9, 9]),
    }
    net = live_net_breadth(lambda s, tf, n: feeds[s], list(feeds), LB, BAR_T)
    assert net == 0.0  # +1 -1 +0
    assert live_net_breadth(lambda s, tf, n: feeds["UP"], ["UP"], LB, BAR_T) == 1.0


def test_live_net_breadth_skips_stale_and_short_feeds():
    stale = _feed([10] * 6, [9] * 5 + [8], end=BAR_T - pd.Timedelta(hours=3))
    short = _feed([10, 11], [9, 9.5])

    def fetch(s, tf, n):
        if s == "ERR":
            raise RuntimeError("no rates")
        return {"STALE": stale, "SHORT": short}[s]

    assert live_net_breadth(fetch, ["STALE", "SHORT", "ERR"], LB, BAR_T) == 0.0


def test_live_net_breadth_ignores_forming_bar():
    # the forming bar spikes to a huge high; only the closed bar may count
    df = _feed([10, 10, 10, 10, 10, 10], [9, 9, 9, 9, 9, 9], forming=False)
    spike = df.iloc[[-1]].copy()
    spike.index = [BAR_T + pd.Timedelta(hours=1)]
    spike["high"] = 99.0
    df = pd.concat([df, spike])
    assert live_net_breadth(lambda s, tf, n: df, ["X"], LB, BAR_T) == 0.0


# --- Executor._breadth_value ------------------------------------------------

def _executor() -> Executor:
    cfg = Config()
    cfg.symbol = "AAPL"
    cfg.breadth.use = True
    cfg.breadth.lookback = LB
    return Executor(cfg, logging.getLogger("test"), account="1")


def test_executor_breadth_value_and_cache():
    executor_mod._BREADTH_CACHE.clear()
    ex = _executor()
    up = _feed([10, 10, 10, 10, 10, 11], [9, 9, 9, 9, 9, 9.5])
    calls = {"fetch": 0}

    def fake_fetch(sym, tf, n):
        calls["fetch"] += 1
        return up

    with patch("gold_trader.executor.mt5_client.list_symbols",
               return_value=["AAPL", "NVIDIA", "EURUSD"]), \
         patch("gold_trader.executor.mt5_client.fetch_ohlcv", fake_fetch):
        assert ex._breadth_value(BAR_T) == 2.0        # both members made highs
        n_first = calls["fetch"]
        assert ex._breadth_value(BAR_T) == 2.0        # cached: no new fetches
        assert calls["fetch"] == n_first
        # a second executor in the same process reuses the cached value
        ex2 = _executor()
        with patch("gold_trader.executor.mt5_client.list_symbols",
                   return_value=["AAPL", "NVIDIA"]):
            assert ex2._breadth_value(BAR_T) == 2.0
        assert calls["fetch"] == n_first


def test_executor_breadth_value_none_without_universe():
    executor_mod._BREADTH_CACHE.clear()
    ex = _executor()
    with patch("gold_trader.executor.mt5_client.list_symbols",
               return_value=["EURUSD", "XAUUSD"]):
        assert ex._breadth_value(BAR_T) is None       # no US stocks on broker


def test_executor_breadth_value_none_on_discovery_failure():
    executor_mod._BREADTH_CACHE.clear()
    ex = _executor()
    with patch("gold_trader.executor.mt5_client.list_symbols",
               side_effect=RuntimeError("terminal gone")):
        assert ex._breadth_value(BAR_T) is None


# --- alias handling, path discovery, sampling (universe expansion) ----------

def test_alias_variants_collapse_to_one_company():
    from gold_trader.breadth import discover_universe as du
    # ticker and company-name spellings of the SAME company must not double-count
    assert du(["NVDA", "NVIDIA"]) == ["NVDA"]
    assert du(["AMAZON", "AMZN"]) == ["AMZN"]        # shortest name wins
    assert du(["GOOGL", "GOOG", "ALPHABET"]) == ["GOOG"]
    # distinct companies are both kept
    assert du(["AAPL", "MSFT"]) == ["AAPL", "MSFT"]


def test_original_universe_still_matches():
    from gold_trader.breadth import is_universe_member as m
    for stem in ("aapl", "amazon", "boeing", "disney", "exxon", "intel",
                 "nvidia", "pfizer", "visa", "goog", "ma", "cost"):
        assert m(stem), stem
        assert m(f"{stem}_h1")


def test_single_letter_tickers_excluded():
    from gold_trader.breadth import is_universe_member as m
    # deliberately omitted: a 1-char exact match collides too easily with a
    # broker's internal naming and would spawn a live config on the wrong thing
    for risky in ("c", "v", "t", "f", "d", "k", "o", "x"):
        assert not m(risky), risky


def test_discover_from_paths_uses_broker_taxonomy():
    from gold_trader.breadth import discover_from_paths as dfp
    entries = [
        ("AAPL", r"Stocks\US\AAPL"),
        ("ZZZZ", r"Stocks\US\ZZZZ"),          # not in US_STOCKS but a US equity
        ("US500", r"Indices\US\US500"),        # index bucket -> excluded
        ("EURUSD", r"Forex\Majors\EURUSD"),
        ("BTCUSD", r"Crypto\BTCUSD"),
        ("BMW", r"Stocks\DE\BMW"),             # wrong region
    ]
    assert dfp(entries, "us") == ["AAPL", "ZZZZ"]


def test_discover_from_paths_dedupes_venue_variants():
    from gold_trader.breadth import discover_from_paths as dfp
    entries = [("NVDA.24h", r"Stocks\US\NVDA"), ("NVDA", r"Stocks\US\NVDA")]
    assert dfp(entries, "us") == ["NVDA"]


def test_sample_universe_caps_deterministically():
    from gold_trader.breadth import sample_universe as su
    syms = [f"S{i:04d}" for i in range(1000)]
    got = su(syms, 200)
    assert len(got) == 200
    assert got == su(list(reversed(syms)), 200)   # order-stable across calls
    assert len(set(got)) == 200                   # no duplicates
    assert su(syms, 0) == syms                    # 0 = no cap
    assert su(["A", "B"], 200) == ["A", "B"]      # under cap = unchanged


def test_executor_samples_large_universe():
    executor_mod._BREADTH_CACHE.clear()
    ex = _executor()
    ex.cfg.breadth.max_universe = 5
    up = _feed([10, 10, 10, 10, 10, 11], [9, 9, 9, 9, 9, 9.5])
    names = list(US_STOCKS)[:50]
    with patch("gold_trader.executor.mt5_client.list_symbols", return_value=names), \
         patch("gold_trader.executor.mt5_client.fetch_ohlcv", return_value=up):
        val = ex._breadth_value(BAR_T)
    assert len(ex._breadth_universe) == 5
    assert val == 5.0        # only the sampled symbols are counted


# --- broker-name normalization (real Vantage catalogue shapes) --------------

def test_normalize_stem_strips_feed_suffixes():
    from gold_trader.breadth import normalize_stem as n
    assert n("AAPLUSD") == "aapl"        # USD-quoted duplicate feed
    assert n("ABBV.24H") == "abbv"       # 24-hour venue feed
    assert n("ASML-US") == "asml"
    assert n("AT&T") == "att"
    assert n("nvidia_h1") == "nvidia"    # backtest CSV stem
    assert n("US2000.r") == ""           # digits -> not a single-name equity
    assert n("USNote10Y") == ""


def test_normalize_stem_does_not_corrupt_real_names():
    from gold_trader.breadth import normalize_stem as n
    # 'amazon' ends in n, 'microsoft' in ft — naive suffix trimming broke these
    for name in ("amazon", "microsoft", "msft", "visa", "boeing", "disney",
                 "pfizer", "usb", "goog", "ma", "intel"):
        assert n(name) == name, name


def test_looks_like_equity_rejects_us_path_leakage():
    from gold_trader.breadth import looks_like_equity as eq
    # all of these really sit in Vantage's US group but are not equities
    for junk in ("XAUUSD", "XAGUSD", "USO", "USOUSD", "USL", "UKOUSD",
                 "UKOUSDft", "US2000.r", "USDX.r", "USNote10Y", "VUSD"):
        assert not eq(junk), junk
    for real in ("AAPL", "AAPLUSD", "ABBV.24H", "ASML-US", "USB", "NVIDIA"):
        assert eq(real), real


def test_duplicate_company_feeds_collapse_in_path_discovery():
    from gold_trader.breadth import discover_from_paths as dfp
    entries = [
        ("AAPL", r"Stocks\US\AAPL"),
        ("AAPLUSD", r"Stocks\US\AAPLUSD"),      # same company, USD feed
        ("NVIDIA", r"Stocks\US\NVIDIA"),
        ("NVDAUSD", r"Stocks\US\NVDAUSD"),      # same company, ticker+USD
        ("XAUUSD", r"Stocks\US\XAUUSD"),        # gold -> excluded
    ]
    assert dfp(entries, "us") == ["AAPL", "NVIDIA"]


# --- discovered-universe file (scaling without hand-typed tickers) ----------

def test_load_universe_file_extends_and_filters(tmp_path):
    from gold_trader import breadth as b
    saved = dict(b._EXTRA_COMPANIES)
    b._EXTRA_COMPANIES.clear()
    try:
        f = tmp_path / "u.txt"
        f.write_text(
            "# discovered on broker\n"
            "ADSK\n"
            "BKNG\n"
            "AAOIUSD\n"      # USD feed of a company we don't curate
            "XAUUSD\n"       # gold -> must be rejected
            "US2000.r\n"     # index -> must be rejected
            "AAPL\n"         # already curated -> not counted twice
            "NVDAUSD\n"      # curated company via alias -> not counted twice
            "\n",
            encoding="utf-8",
        )
        added = b.load_universe_file(f)
        assert added == 3                      # ADSK, BKNG, AAOI only
        assert b.is_universe_member("ADSK")
        assert b.is_universe_member("adsk_h1")  # backtest CSV stem resolves
        assert b.is_universe_member("AAOIUSD")
        assert not b.is_universe_member("XAUUSD")
        assert not b.is_universe_member("US2000.r")
    finally:
        b._EXTRA_COMPANIES.clear()
        b._EXTRA_COMPANIES.update(saved)


def test_load_universe_file_missing_is_noop(tmp_path):
    from gold_trader import breadth as b
    assert b.load_universe_file(tmp_path / "nope.txt") == 0


def test_discovered_symbols_do_not_double_count_curated(tmp_path):
    from gold_trader import breadth as b
    saved = dict(b._EXTRA_COMPANIES)
    b._EXTRA_COMPANIES.clear()
    try:
        f = tmp_path / "u.txt"
        f.write_text("AAPLUSD\nAPPLE\nAAPL\n", encoding="utf-8")
        assert b.load_universe_file(f) == 0     # all three are one curated company
        assert b.discover_universe(["AAPL", "AAPLUSD", "APPLE"]) == ["AAPL"]
    finally:
        b._EXTRA_COMPANIES.clear()
        b._EXTRA_COMPANIES.update(saved)
