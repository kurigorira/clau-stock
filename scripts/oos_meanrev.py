"""Out-of-sample comparison: kairi (6-2) vs bollrci (6-6) vs the incumbent macd.

Both new strategies are mean reversion — the opposite P&L shape from the
trend-following incumbent — so the interesting outcomes are (a) either one
beating zero on the held-out half after costs, and (b) how they compare to the
macd fleet on the same symbols, same period, same costs.

Discipline is the same as oos_stoch/oos_breadth, learned the hard way here:
the key knob is chosen on the in-sample (train) half by PnL, and only the
held-out (test) result of that train-chosen value counts. Reading the test
column to pick a parameter is self-deception.

  * kairi   knob: threshold_atr_mult (how stretched from the MA before entry)
  * bollrci knob: rci_threshold      (how exhausted RCI must confirm)

Both run with their H4 filter ON (revert toward the H4 trend), the
configuration this project's evidence consistently favours.

Usage:
    python scripts/oos_meanrev.py --configs config/us_fleet/*.yaml --slippage-bp 5
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

FLEET_CFGS: dict = {}

KAIRI_CANDS = (1.5, 2.0, 2.5, 3.0)
BOLLRCI_CANDS = (60.0, 70.0, 80.0, 90.0)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", text.lower())


def _cfg_for(csv_path: Path, strategy: str, knob: float | None) -> Config:
    live = FLEET_CFGS.get(_slug(csv_path.stem.removesuffix("_h1")))
    cfg = copy.deepcopy(live) if live is not None else Config()
    cfg.strategy = strategy
    cfg.breadth.use = False
    if strategy == "kairi" and knob is not None:
        cfg.kairi.threshold_atr_mult = knob
    if strategy == "bollrci" and knob is not None:
        cfg.bollrci.rci_threshold = knob
    # the incumbent row keeps the fleet's own stoch/macd settings untouched
    return cfg


def _run_split(csvs, frames, strategy, knob, split_ts, slips):
    seg = {"train": [0, 0, 0.0], "test": [0, 0, 0.0]}
    for csv_path in csvs:
        cfg = _cfg_for(csv_path, strategy, knob)
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
    p = argparse.ArgumentParser(description="kairi vs bollrci vs incumbent, OOS")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--split", type=float, default=0.6)
    p.add_argument("--configs", nargs="*", default=[],
                   help="fleet configs supplying the symbols and incumbent "
                        "settings (e.g. config/us_fleet/*.yaml)")
    p.add_argument("--slippage-bp", type=float, default=0.0)
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

    print(f"# mean-reversion OOS  (split={args.split:g} @ {split_ts.date()}, "
          f"{len(frames)} symbols, cost {args.slippage_bp:g}bp/side, "
          "H4 filter ON for kairi/bollrci)")
    hdr = (f"{'row':<18} | {'n':>5} {'win%':>6} {'pnl':>11}  train | "
           f"{'n':>5} {'win%':>6} {'pnl':>11}  test")
    print(hdr)
    print("-" * len(hdr))

    incumbent = _run_split(csvs, frames, "macd", None, split_ts, slips)
    print(f"{'macd (incumbent)':<18} | {_fmt(incumbent['train'])}  train | "
          f"{_fmt(incumbent['test'])}  test")

    picks = {}
    for strategy, cands, label in (
        ("kairi", KAIRI_CANDS, "kairi k={:g}"),
        ("bollrci", BOLLRCI_CANDS, "bollrci thr={:g}"),
    ):
        rows, best, best_train = {}, None, float("-inf")
        for knob in cands:
            seg = _run_split(csvs, frames, strategy, knob, split_ts, slips)
            rows[knob] = seg
            if seg["train"][2] > best_train:
                best_train, best = seg["train"][2], knob
        for knob in cands:
            star = " *" if knob == best else "  "
            print(f"{label.format(knob):<16}{star} | {_fmt(rows[knob]['train'])}  train | "
                  f"{_fmt(rows[knob]['test'])}  test")
        picks[strategy] = (best, rows[best])

    print("-" * len(hdr))
    inc_test = incumbent["test"][2]
    for strategy, (best, seg) in picks.items():
        t_n, t_w, t_p = seg["test"]
        verdict = ("POSITIVE out-of-sample" if t_p > 0 else "negative out-of-sample")
        vs = "beats" if t_p > inc_test else "does not beat"
        print(f"# {strategy}: train-selected knob {best:g} -> test PnL {t_p:+.2f} "
              f"on {t_n} trades ({verdict}; {vs} the macd incumbent's {inc_test:+.2f})")
    print("# deploy nothing that is not positive on TEST; a mean-reversion book "
          "only earns its slot by adding PnL with a different shape, not by "
          "merely existing.")


if __name__ == "__main__":
    main()
