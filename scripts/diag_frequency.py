"""Where do entries die? A signal funnel for trade frequency.

Live trade counts feeling low has two very different causes — a bug/misconfig,
or the gates doing exactly what they were tuned to do — and guessing wrong
leads to loosening a filter that was carrying the edge. This counts, over the
backtest CSVs, how many candidate entries survive each stage:

    bars -> raw MACD crosses -> pass ATR%% band -> pass stoch -> pass breadth
         -> actual trades (the rest were suppressed: a cross that fires while
            already in a position doesn't open anything — macd rides to the
            opposite cross)

Per-stage survivors are printed with their per-week rate, so the lever with the
most headroom is obvious. A projection then shows what universe size would be
needed to hit a target weekly trade count at the measured per-symbol rate.

Stages are computed from the same indicator columns and gate helpers the
executor uses; the final row comes from an actual run_backtest, so the
funnel can't silently drift from what really trades.

Usage:
    python scripts/diag_frequency.py                        # macd, min_net 1
    python scripts/diag_frequency.py --min-net 0 --stoch
    python scripts/diag_frequency.py --want-per-week 20
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.breadth import compute_breadth, is_universe_member  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402
from gold_trader.strategy import add_indicators  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _config_for_csv(csv_path: Path) -> Path | None:
    slug = re.sub(r"[^a-z0-9]", "_", csv_path.stem.removesuffix("_h1").lower())
    candidate = CONFIG_DIR / f"fib_{slug}.yaml"
    return candidate if candidate.exists() else None


def _cfg(csv_path: Path, args) -> Config:
    matched = _config_for_csv(csv_path)
    cfg = Config.from_yaml(matched) if matched else Config()
    cfg.strategy = "macd"
    cfg.stoch.use = args.stoch
    cfg.stoch.overbought = args.overbought
    cfg.stoch.oversold = args.oversold
    cfg.breadth.use = True
    cfg.breadth.lookback = args.lookback
    cfg.breadth.min_net = args.min_net
    return cfg


def main() -> None:
    p = argparse.ArgumentParser(description="entry-funnel frequency diagnosis")
    p.add_argument("--data-dir", default="data")
    p.add_argument("--min-net", type=float, default=1.0)
    p.add_argument("--lookback", type=int, default=100)
    p.add_argument("--stoch", action="store_true", help="include the stoch gate")
    p.add_argument("--overbought", type=float, default=80.0)
    p.add_argument("--oversold", type=float, default=20.0)
    p.add_argument("--want-per-week", type=float, default=None,
                   help="target fleet trades/week; prints the universe size needed")
    args = p.parse_args()

    csvs = [c for c in sorted(Path(args.data_dir).glob("*_h1.csv"))
            if is_universe_member(c.stem)]
    if not csvs:
        sys.stderr.write(f"no US-stock CSVs in {args.data_dir}/\n")
        sys.exit(2)

    frames = {c.stem: load_csv(c) for c in csvs}
    breadth = compute_breadth(frames, args.lookback)
    start = min(df.index[0] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    weeks = max((end - start).total_seconds() / (7 * 86400.0), 1e-9)

    bars = crosses = pass_atr = pass_stoch = pass_breadth = trades = 0
    for csv_path in csvs:
        stem = csv_path.stem
        cfg = _cfg(csv_path, args)
        # force the optional columns to exist so every stage is measurable
        col_cfg = Config.from_yaml(_config_for_csv(csv_path)) if _config_for_csv(csv_path) else Config()
        col_cfg.strategy = "macd"
        col_cfg.stoch.use = True
        col_cfg.stoch.k, col_cfg.stoch.smooth = cfg.stoch.k, cfg.stoch.smooth
        data = add_indicators(frames[stem], col_cfg)

        hist = data["macd_hist"]
        prev = hist.shift(1)
        up = (prev <= 0) & (hist > 0)
        down = (prev >= 0) & (hist < 0)
        cross = (up | down) & hist.notna() & prev.notna()

        atr_pct = data["atr_pct"]
        in_band = (atr_pct >= cfg.filters.atr_pct_min) & (atr_pct <= cfg.filters.atr_pct_max)
        # NaN atr/atr_pct bail out before the band check in the evaluator
        valid = data["atr"].notna() & atr_pct.notna()

        k = data["stoch_k"]
        # stoch blocks longs at/above overbought, shorts at/below oversold; NaN blocks
        stoch_ok = (
            (up & (k < cfg.stoch.overbought)) | (down & (k > cfg.stoch.oversold))
        ) & k.notna()
        if not args.stoch:
            stoch_ok = cross  # gate off: everything that crossed passes

        bval = breadth.reindex(data.index)
        # breadth blocks a long unless net > min_net, a short unless net < -min_net;
        # unknown (NaN) never blocks, matching breadth_blocks
        b_ok = (
            (up & ((bval > cfg.breadth.min_net) | bval.isna()))
            | (down & ((bval < -cfg.breadth.min_net) | bval.isna()))
        )

        s1 = cross & valid
        s2 = s1 & in_band
        s3 = s2 & stoch_ok
        s4 = s3 & b_ok

        bars += len(data)
        crosses += int(s1.sum())
        pass_atr += int(s2.sum())
        pass_stoch += int(s3.sum())
        pass_breadth += int(s4.sum())
        try:
            trades += run_backtest(frames[stem], cfg, breadth=breadth)["n"]
        except Exception:  # noqa: BLE001
            pass

    n_sym = len(csvs)
    gate_tag = "stoch+breadth" if args.stoch else "breadth"
    print(f"# macd entry funnel — {n_sym} US stocks, {weeks:.1f} weeks, "
          f"gates: {gate_tag} (min_net={args.min_net:g})")
    hdr = f"{'stage':<34} {'count':>7} {'/week':>8} {'kept':>7}"
    print(hdr)
    print("-" * len(hdr))

    def row(label, n, base):
        kept = f"{n / base:.0%}" if base else "-"
        print(f"{label:<34} {n:>7} {n / weeks:>8.1f} {kept:>7}")

    print(f"{'bars evaluated':<34} {bars:>7} {bars / weeks:>8.0f} {'':>7}")
    row("raw MACD crosses", crosses, crosses)
    row("  pass ATR% band", pass_atr, crosses)
    row("  pass stoch gate", pass_stoch, crosses)
    row("  pass breadth gate", pass_breadth, crosses)
    row("actual entries (backtest)", trades, crosses)
    print("-" * len(hdr))

    suppressed = pass_breadth - trades
    if suppressed > 0:
        print(f"# {suppressed} eligible signals ({suppressed / max(pass_breadth,1):.0%}) "
              "fired while already in a position — macd rides to the opposite "
              "cross, so they open nothing.")
    per_sym_wk = trades / weeks / n_sym if n_sym else 0.0
    print(f"# measured rate: {trades / weeks:.1f} trades/week over {n_sym} symbols "
          f"= {per_sym_wk:.2f} per symbol per week")
    if args.want_per_week and per_sym_wk > 0:
        need = args.want_per_week / per_sym_wk
        print(f"# to reach {args.want_per_week:g} trades/week at this rate you would "
              f"need ~{int(np.ceil(need))} symbols ({need / n_sym:.1f}x the current "
              "universe).")


if __name__ == "__main__":
    main()
