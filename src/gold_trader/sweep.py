"""Parameter sweep helpers: vary one config parameter across a list of
values and score it by POOLING trades across many symbols.

Why pool: a single symbol has only ~20-40 trades over 12 months, far too
few to tune even one parameter without fitting noise. Pooling every symbol
that runs a given strategy yields hundreds of trades, enough to move 1-2
parameters with a train/test guard. Tune at the strategy level, then apply
the winner to all symbols in that strategy - do NOT tune per symbol.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import pandas as pd

from .backtest import run_backtest
from .config import Config
from .screener import profit_factor, split_frame


def set_param(cfg: Config, path: str, value) -> Config:
    """Return a deep copy of cfg with a dotted parameter path set.

    e.g. set_param(cfg, "fibonacci.retrace_min", 0.5) or
    set_param(cfg, "risk.atr_stop_mult", 2.5). Raises on unknown paths so a
    typo fails loudly instead of silently sweeping nothing.
    """
    out = copy.deepcopy(cfg)
    obj = out
    parts = path.split(".")
    for attr in parts[:-1]:
        obj = getattr(obj, attr)
    leaf = parts[-1]
    if not hasattr(obj, leaf):
        raise AttributeError(f"unknown parameter path: {path}")
    current = getattr(obj, leaf)
    # coerce to the existing field's type so YAML-style strings work
    if isinstance(current, bool):
        value = value if isinstance(value, bool) else str(value).lower() in ("1", "true", "yes")
    elif isinstance(current, int) and not isinstance(current, bool):
        value = int(value)
    elif isinstance(current, float):
        value = float(value)
    setattr(obj, leaf, value)
    return out


@dataclass
class PooledScore:
    value: object
    train_n: int
    train_pf: float
    train_pnl: float
    test_n: int
    test_pf: float
    test_pnl: float


def _pool(results: list[dict]) -> tuple[int, float, float]:
    """Aggregate (n, profit_factor, total_pnl) across per-symbol results."""
    trades = [t for r in results for t in r["trades"]]
    n = len(trades)
    pf = profit_factor(trades)
    pnl = sum(t.pnl_price for t in trades)
    return n, pf, pnl


def sweep_param(
    frames: dict[str, pd.DataFrame],
    base_cfg: Config,
    path: str,
    values: list,
    *,
    strategy: str,
    split_ratio: float = 0.7,
    spread_by_symbol: dict[str, float] | None = None,
) -> list[PooledScore]:
    """Sweep one parameter, pooling trades across all `frames`.

    frames: symbol -> H1 OHLCV. spread_by_symbol: symbol -> slippage_price
    (half-spread in price units); defaults to 0 for every symbol.
    Returns one PooledScore per value, in input order.
    """
    spread = spread_by_symbol or {}
    scores: list[PooledScore] = []
    for value in values:
        cfg = set_param(base_cfg, path, value)
        cfg.strategy = strategy
        train_results, test_results = [], []
        for symbol, df in frames.items():
            train, test = split_frame(df, split_ratio)
            slip = spread.get(symbol, 0.0)
            train_results.append(run_backtest(train, cfg, slippage_price=slip))
            test_results.append(run_backtest(test, cfg, slippage_price=slip))
        tr_n, tr_pf, tr_pnl = _pool(train_results)
        te_n, te_pf, te_pnl = _pool(test_results)
        scores.append(
            PooledScore(
                value=value,
                train_n=tr_n, train_pf=tr_pf, train_pnl=tr_pnl,
                test_n=te_n, test_pf=te_pf, test_pnl=te_pnl,
            )
        )
    return scores
