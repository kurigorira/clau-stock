from __future__ import annotations

from pathlib import Path

import pandas as pd


def resample_ohlcv(df: pd.DataFrame, rule: str = "4h") -> pd.DataFrame:
    """Aggregate a finer OHLCV frame into `rule` bars (bar-open timestamps).

    Used by the backtester to synthesise H4 bars from an H1 CSV so the
    fibonacci strategy can be tested from a single data file.
    """
    out = df.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    return out.dropna(subset=["open", "high", "low", "close"])


def load_csv(path: str | Path) -> pd.DataFrame:
    """Load OHLCV CSV with a UTC `time` column and open/high/low/close/volume."""
    df = pd.read_csv(path, encoding="utf-8")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    expected = {"open", "high", "low", "close", "volume"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing columns: {missing}")
    return df[["open", "high", "low", "close", "volume"]]
