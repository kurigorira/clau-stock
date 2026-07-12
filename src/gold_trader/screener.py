"""Symbol screening: find instruments that fit the strategies, instead of
testing hand-picked instruments.

Core logic lives here (pure, unit-testable); scripts/screen_symbols.py wires
it to the MT5 terminal and walks every symbol the broker offers.

Guardrails against data-mining luck:
- train/test split: a symbol must clear the profit gate on the first part of
  the history AND stay profitable on the held-out remainder
- spread-aware slippage: each side of a trade pays half the current spread,
  so wide-spread instruments can't fake profitability
- minimum trade counts on both segments: a huge PF over 2 trades is noise
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from .backtest import run_backtest
from .config import Config


@dataclass
class StrategyScore:
    strategy: str
    train_n: int
    train_pf: float
    train_pnl: float
    test_n: int
    test_pf: float
    test_pnl: float


@dataclass
class ScreenResult:
    symbol: str
    spread_points: float
    scores: list[StrategyScore]

    def best(self) -> StrategyScore | None:
        passing = [s for s in self.scores if s.test_pf > 0]
        return max(passing, key=lambda s: s.test_pf) if passing else None


def existing_symbols(config_dir: str | Path) -> set[str]:
    """Every `symbol:` already claimed by a preset in config/.

    Covers the launched fleet, benched presets and legacy YAMLs alike — a
    symbol that has ever been through the gate shouldn't resurface as a
    "new" candidate. Files without a symbol key (e.g. watchlist.yaml) are
    ignored.
    """
    symbols: set[str] = set()
    for p in Path(config_dir).glob("*.yaml"):
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        sym = raw.get("symbol")
        if isinstance(sym, str) and sym:
            symbols.add(sym)
    return symbols


def profit_factor(trades) -> float:
    wins = sum(t.pnl_price for t in trades if t.pnl_price > 0)
    losses = -sum(t.pnl_price for t in trades if t.pnl_price < 0)
    if losses > 0:
        return wins / losses
    return float("inf") if wins > 0 else 0.0


def split_frame(df: pd.DataFrame, ratio: float = 0.7) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Chronological train/test split by row count."""
    if not 0.0 < ratio < 1.0:
        raise ValueError(f"ratio must be in (0, 1), got {ratio}")
    cut = int(len(df) * ratio)
    return df.iloc[:cut], df.iloc[cut:]


def passes_gate(
    score: StrategyScore,
    *,
    min_train_trades: int = 10,
    min_train_pf: float = 1.2,
    min_test_trades: int = 4,
    min_test_pf: float = 1.0,
) -> bool:
    """True when a strategy's result is strong in-sample AND holds up
    out-of-sample. The test bar is deliberately lower (fewer bars, fewer
    trades) — it exists to reject flukes, not to demand perfection twice."""
    return (
        score.train_n >= min_train_trades
        and score.train_pf >= min_train_pf
        and score.test_n >= min_test_trades
        and score.test_pf >= min_test_pf
    )


def score_symbol(
    symbol: str,
    df_h1: pd.DataFrame,
    cfg: Config,
    *,
    spread_points: float = 0.0,
    point: float = 0.0,
    split_ratio: float = 0.7,
) -> ScreenResult:
    """Backtest both strategies on a train/test split of one symbol's bars.

    Slippage per side = half the quoted spread, so round-trip cost equals the
    full spread — the realistic floor a live fill pays.
    """
    import copy

    slippage = spread_points * point / 2.0
    train, test = split_frame(df_h1, split_ratio)
    scores: list[StrategyScore] = []
    for strategy in ("donchian", "fibonacci"):
        c = copy.deepcopy(cfg)
        c.strategy = strategy
        r_train = run_backtest(train, c, slippage_price=slippage)
        r_test = run_backtest(test, c, slippage_price=slippage)
        scores.append(
            StrategyScore(
                strategy=strategy,
                train_n=r_train["n"],
                train_pf=profit_factor(r_train["trades"]),
                train_pnl=r_train["total_pnl_price"],
                test_n=r_test["n"],
                test_pf=profit_factor(r_test["trades"]),
                test_pnl=r_test["total_pnl_price"],
            )
        )
    return ScreenResult(symbol=symbol, spread_points=spread_points, scores=scores)
