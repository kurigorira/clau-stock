"""Out-of-sample validation of the US-stock breadth gate.

The A/B sweep (ab_breadth.py) picks the best min_net on the *same* data it
scores on — so a good number there can be curve-fit. This script splits the
timeline at --split, chooses one global min_net on the in-sample (train) half by
train PnL, then reports how that choice does on the held-out (test) half. If the
test improvement survives, the gate is real; if it collapses, it was fitting.

Method notes:
  * One full backtest per (symbol, min_net); its trades are partitioned into
    train/test by *entry time* against a single global split timestamp (the
    `--split` quantile of all bar timestamps). This needs no re-warmup and never
    leaks: breadth at any bar already uses only trailing data.
  * A single global min_net is selected (not per-symbol) — per-symbol tuning
    would just move the overfitting downstream.

Usage:
    python scripts/oos_breadth.py --strategy macd
    python scripts/oos_breadth.py --strategy macd --stoch    # stoch+breadth combo
    python scripts/oos_breadth.py --strategy fibonacci --split 0.6
    python scripts/oos_breadth.py --strategy donchian --candidates 0,1,2,3,5
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.breadth import compute_breadth, is_universe_member  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _config_for_csv(csv_path: Path) -> Path | None:
    slug = re.sub(r"[^a-z0-9]", "_", csv_path.stem.removesuffix("_h1").lower())
    candidate = CONFIG_DIR / f"fib_{slug}.yaml"
    return candidate if candidate.exists() else None


FLEET_CFGS: dict = {}


def _base_cfg(csv_path: Path, args) -> Config:
    slug = re.sub(r"[^a-z0-9]", "_", csv_path.stem.removesuffix("_h1").lower())
    live = FLEET_CFGS.get(slug)
    if live is not None:
        # the fleet's own parameters, so the test isn't validating a different
        # strategy than the one that trades (macd.use_h4_filter differs)
        cfg = copy.deepcopy(live)
        cfg.strategy = args.strategy
        cfg.breadth.lookback = args.lookback
        cfg.stoch.use = args.stoch
        return cfg
    matched = _config_for_csv(csv_path)
    cfg = Config.from_yaml(matched) if matched else Config()
    cfg.strategy = args.strategy
    cfg.breadth.lookback = args.lookback
    # --stoch layers the stochastic gate onto EVERY row (base included), so
    # the table isolates breadth's marginal effect on top of stoch — i.e. it
    # OOS-tests the stoch+breadth combo against a stoch-only base.
    cfg.stoch.use = args.stoch
    return cfg


def _run_split(csvs, frames, breadth, args, min_net, use, split_ts, slips):
    """Return {'train': (n, wins, pnl), 'test': (n, wins, pnl)} pooled over
    every symbol, trades assigned to a segment by entry time vs split_ts."""
    seg = {"train": [0, 0, 0.0], "test": [0, 0, 0.0]}
    for csv_path in csvs:
        cfg = _base_cfg(csv_path, args)
        cfg.breadth.min_net = min_net
        cfg.breadth.use = use
        try:
            r = run_backtest(frames[csv_path.stem], cfg, breadth=breadth,
                             slippage_price=slips.get(csv_path.stem, 0.0))
        except Exception:  # noqa: BLE001
            continue
        for t in r["trades"]:
            s = "train" if t.entry_time < split_ts else "test"
            seg[s][0] += 1
            seg[s][1] += 1 if t.pnl_price > 0 else 0
            seg[s][2] += t.pnl_price
    return seg


def _fmt(cell):
    n, wins, pnl = cell
    win = wins / n if n else 0.0
    return f"{n:>5} {win:>6.1%} {pnl:>11.2f}"


def main() -> None:
    p = argparse.ArgumentParser(description="out-of-sample breadth-gate validation")
    p.add_argument("--strategy", default="macd",
                   choices=("donchian", "fibonacci", "macd"))
    p.add_argument("--data-dir", default="data")
    p.add_argument("--split", type=float, default=0.6,
                   help="fraction of the timeline used for in-sample (default 0.6)")
    p.add_argument("--lookback", type=int, default=100)
    p.add_argument("--candidates", default="auto",
                   help="comma min_net candidates, or 'auto' (default) to place "
                        "them at percentiles of |net breadth| so selectivity "
                        "means the same thing at any universe size")
    p.add_argument("--configs", nargs="*", default=[],
                   help="restrict the tested universe to these configs' symbols "
                        "(e.g. config/us_fleet/*.yaml). Backtesting names you do "
                        "not trade contaminates both the breadth tally and the "
                        "pooled PnL")
    p.add_argument("--slippage-bp", type=float, default=0.0,
                   help="per-side cost in basis points of each symbol's median "
                        "price — the gate's whole job is surviving costs")
    p.add_argument("--stoch", action="store_true",
                   help="enable the stochastic gate on every row (base too) — "
                        "OOS-tests stoch+breadth against a stoch-only base")
    args = p.parse_args()

    all_csvs = sorted(Path(args.data_dir).glob("*_h1.csv"))
    csvs = [c for c in all_csvs if is_universe_member(c.stem)]
    if args.configs:
        # keep only the symbols we actually trade, matched on the CSV stem
        for path in expand_paths(args.configs):
            live = Config.from_yaml(path)
            FLEET_CFGS[re.sub(r"[^a-z0-9]", "_", live.symbol.lower())] = live
        csvs = [c for c in csvs
                if re.sub(r"[^a-z0-9]", "_", c.stem.removesuffix("_h1")) in FLEET_CFGS]
    if not csvs:
        sys.stderr.write(f"no US-stock CSVs in {args.data_dir}/\n")
        sys.exit(2)

    frames = {c.stem: load_csv(c) for c in csvs}
    breadth = compute_breadth(frames, args.lookback)
    slips = {s: float(df["close"].median()) * args.slippage_bp / 1e4
             for s, df in frames.items()}
    split_ts = breadth.index[int(len(breadth) * args.split)]
    absb = breadth.abs()
    absb = absb[absb > 0]
    if args.candidates.strip().lower() == "auto":
        # thresholds at percentiles of |net breadth|, so "how selective" means
        # the same thing whether the universe is 34 symbols or 506
        pcts = [0, 40, 60, 75, 85, 93]
        cands = sorted({float(np.percentile(absb, q)) if len(absb) else 0.0
                        for q in pcts})
    else:
        cands = [float(x) for x in args.candidates.split(",") if x.strip()]
    rng = (f"|net| median {absb.median():.0f}, p90 {absb.quantile(0.9):.0f}, "
           f"max {absb.max():.0f}" if len(absb) else "no breadth signal")

    stoch_tag = " + stoch gate on all rows" if args.stoch else ""
    print(f"# {args.strategy} breadth OOS  (lookback={args.lookback}, "
          f"split={args.split:g} @ {split_ts.date()}, {len(frames)} US stocks"
          f"{stoch_tag}, cost {args.slippage_bp:g}bp/side)")
    print(f"# breadth scale: {rng}")
    hdr = (f"{'min_net':>8} | {'n':>5} {'win%':>6} {'pnl':>11}  train | "
           f"{'n':>5} {'win%':>6} {'pnl':>11}  test")
    print(hdr)
    print("-" * len(hdr))

    base = _run_split(csvs, frames, breadth, args, 0.0, False, split_ts, slips)
    print(f"{'base':>8} | {_fmt(base['train'])}  train | {_fmt(base['test'])}  test")

    best_mn, best_train_pnl, rows = None, float("-inf"), {}
    for mn in cands:
        seg = _run_split(csvs, frames, breadth, args, mn, True, split_ts, slips)
        rows[mn] = seg
        marker = ""
        if seg["train"][2] > best_train_pnl:
            best_train_pnl, best_mn = seg["train"][2], mn
    for mn in cands:
        seg = rows[mn]
        star = " *" if mn == best_mn else "  "
        print(f"{mn:>8.4g}{star}| {_fmt(seg['train'])}  train | "
              f"{_fmt(seg['test'])}  test")

    print("-" * len(hdr))
    # Verdict: compare the train-selected gate against base on the TEST half.
    b_n, b_w, b_p = base["test"]
    g_n, g_w, g_p = rows[best_mn]["test"]
    base_test_win = b_w / b_n if b_n else 0.0
    gate_test_win = g_w / g_n if g_n else 0.0
    print(f"# selected on TRAIN by PnL: min_net={best_mn:g}  "
          f"(train PnL {best_train_pnl:+.2f})")
    print(f"# OOS (test) base -> gated:  PnL {b_p:+.2f} -> {g_p:+.2f}  "
          f"(Δ {g_p - b_p:+.2f});  win {base_test_win:.1%} -> {gate_test_win:.1%};  "
          f"trades {b_n} -> {g_n}")
    if g_p > b_p:
        print("# -> gate HELPS out-of-sample (improvement survived the split).")
    else:
        print("# -> gate does NOT help out-of-sample (likely in-sample fitting).")


if __name__ == "__main__":
    main()
