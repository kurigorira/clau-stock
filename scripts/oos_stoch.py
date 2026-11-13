"""Out-of-sample validation of the stochastic gate.

ab_stoch.py picks a threshold on the same data it scores on. Every gate in this
project that looked good in-sample (breadth at 34 symbols, most notably) either
shrank or reversed once held-out data was involved, so the stochastic gate gets
the same treatment before it goes anywhere near the live fleet: choose the
overbought level on the in-sample half by PnL, then report what that choice did
on the held-out half.

Breadth is deliberately OFF here. On the liquid 100-symbol fleet the breadth
gate lost out-of-sample (base test PnL +316 vs +115 at its best threshold), so
the question now is whether stoch adds anything to that ungated base.

Symmetric thresholds: each candidate `ob` pairs with oversold = 100 - ob, so one
number describes how much room the entry demands.

Usage:
    python scripts/oos_stoch.py --configs config/us_fleet/*.yaml --slippage-bp 5
    python scripts/oos_stoch.py --candidates 70,75,80,85,90 --strategy macd
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.breadth import is_universe_member  # noqa: E402
from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", text.lower())


# slug -> the live config for that symbol, populated from --configs. Validating
# against fib_*.yaml/defaults instead would silently test a different strategy:
# the fleet sets macd.use_h4_filter false, the default is true.
FLEET_CFGS: dict = {}


def _base_cfg(csv_path: Path, args) -> Config:
    slug = _slug(csv_path.stem.removesuffix("_h1"))
    live = FLEET_CFGS.get(slug)
    if live is not None:
        cfg = copy.deepcopy(live)          # exactly what the fleet trades
    else:
        matched = CONFIG_DIR / f"fib_{slug}.yaml"
        cfg = Config.from_yaml(matched) if matched.exists() else Config()
    cfg.strategy = args.strategy
    cfg.breadth.use = False   # the gate that lost OOS on this fleet
    return cfg


def _run_split(csvs, frames, args, overbought, use, split_ts, slips):
    """Pooled (n, wins, pnl) per segment, trades bucketed by entry time."""
    seg = {"train": [0, 0, 0.0], "test": [0, 0, 0.0]}
    for csv_path in csvs:
        cfg = _base_cfg(csv_path, args)
        cfg.stoch.use = use
        cfg.stoch.overbought = overbought
        cfg.stoch.oversold = 100.0 - overbought
        try:
            r = run_backtest(frames[csv_path.stem], cfg,
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
    return f"{n:>5} {(wins / n if n else 0.0):>6.1%} {pnl:>11.2f}"


def main() -> None:
    p = argparse.ArgumentParser(description="out-of-sample stochastic-gate validation")
    p.add_argument("--strategy", default="macd",
                   choices=("donchian", "fibonacci", "macd"))
    p.add_argument("--data-dir", default="data")
    p.add_argument("--split", type=float, default=0.6)
    p.add_argument("--candidates", default="70,75,80,85,90",
                   help="overbought levels to choose among; oversold = 100 - ob")
    p.add_argument("--configs", nargs="*", default=[],
                   help="restrict to these configs' symbols (e.g. "
                        "config/us_fleet/*.yaml) so the test matches what trades")
    p.add_argument("--slippage-bp", type=float, default=0.0,
                   help="per-side cost in bp of each symbol's median price")
    args = p.parse_args()

    csvs = [c for c in sorted(Path(args.data_dir).glob("*_h1.csv"))
            if is_universe_member(c.stem)]
    if args.configs:
        for p_ in expand_paths(args.configs):
            live = Config.from_yaml(p_)
            FLEET_CFGS[_slug(live.symbol)] = live
        csvs = [c for c in csvs if _slug(c.stem.removesuffix("_h1")) in FLEET_CFGS]
    if not csvs:
        sys.stderr.write(f"no US-stock CSVs in {args.data_dir}/\n")
        sys.exit(2)

    frames = {c.stem: load_csv(c) for c in csvs}
    slips = {s: float(df["close"].median()) * args.slippage_bp / 1e4
             for s, df in frames.items()}
    index = sorted({t for df in frames.values() for t in df.index})
    split_ts = index[int(len(index) * args.split)]
    cands = [float(x) for x in args.candidates.split(",") if x.strip()]

    print(f"# {args.strategy} stoch OOS  (split={args.split:g} @ {split_ts.date()}, "
          f"{len(frames)} symbols, cost {args.slippage_bp:g}bp/side, breadth OFF)")
    hdr = (f"{'OB/OS':>9} | {'n':>5} {'win%':>6} {'pnl':>11}  train | "
           f"{'n':>5} {'win%':>6} {'pnl':>11}  test")
    print(hdr)
    print("-" * len(hdr))

    base = _run_split(csvs, frames, args, 100.0, False, split_ts, slips)
    print(f"{'base':>9} | {_fmt(base['train'])}  train | {_fmt(base['test'])}  test")

    rows, best_ob, best_train = {}, None, float("-inf")
    for ob in cands:
        seg = _run_split(csvs, frames, args, ob, True, split_ts, slips)
        rows[ob] = seg
        if seg["train"][2] > best_train:
            best_train, best_ob = seg["train"][2], ob
    for ob in cands:
        star = " *" if ob == best_ob else "  "
        print(f"{ob:>4.0f}/{100 - ob:<4.0f}{star}| {_fmt(rows[ob]['train'])}  train | "
              f"{_fmt(rows[ob]['test'])}  test")

    print("-" * len(hdr))
    b_n, b_w, b_p = base["test"]
    g_n, g_w, g_p = rows[best_ob]["test"]
    print(f"# selected on TRAIN by PnL: OB={best_ob:g}/OS={100 - best_ob:g} "
          f"(train PnL {best_train:+.2f})")
    print(f"# OOS (test) base -> gated:  PnL {b_p:+.2f} -> {g_p:+.2f} "
          f"(Δ {g_p - b_p:+.2f});  win {(b_w / b_n if b_n else 0):.1%} -> "
          f"{(g_w / g_n if g_n else 0):.1%};  trades {b_n} -> {g_n}")
    print("# -> stoch HELPS out-of-sample." if g_p > b_p
          else "# -> stoch does NOT help out-of-sample; keep the gate off.")


if __name__ == "__main__":
    main()
