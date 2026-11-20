"""A/B test: does a US-stock market-breadth regime gate help, fleet-wide?

Breadth = (# US stocks making a new `lookback`-bar high) − (# making a new low),
per timestamp, computed once from every US-stock CSV in data/ (see
gold_trader.breadth). Used as a regime filter: a long is allowed only when
breadth > min_net (the group is broadly making new highs), a short only when
breadth < -min_net. The gate is only applied to US stocks — the universe it is
built from — so this script restricts itself to those CSVs.

For each US stock it runs the chosen strategy twice on identical data — gate off
vs on — and prints win-rate and PnL side by side, then an AGGREGATE verdict.

Usage:
    python scripts/ab_breadth.py                       # donchian, all US stocks
    python scripts/ab_breadth.py --strategy fibonacci
    python scripts/ab_breadth.py --lookback 100 --min-net 2
    python scripts/ab_breadth.py --strategy fibonacci --sweep 0,1,2,3,5
"""
from __future__ import annotations

import argparse
import copy
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.breadth import compute_breadth, is_universe_member  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def _config_for_csv(csv_path: Path) -> Path | None:
    slug = re.sub(r"[^a-z0-9]", "_", csv_path.stem.removesuffix("_h1").lower())
    candidate = CONFIG_DIR / f"fib_{slug}.yaml"
    return candidate if candidate.exists() else None


def _base_cfg(csv_path: Path, args) -> Config:
    matched = _config_for_csv(csv_path)
    cfg = Config.from_yaml(matched) if matched else Config()
    cfg.strategy = args.strategy
    cfg.breadth.lookback = args.lookback
    cfg.breadth.min_net = args.min_net
    return cfg


def _aggregate(csvs, frames, breadth, args, min_net, use):
    """Return (n, trade-weighted win rate, total PnL) over every US stock."""
    wins = n = 0
    pnl = 0.0
    for csv_path in csvs:
        cfg = _base_cfg(csv_path, args)
        cfg.breadth.min_net = min_net
        cfg.breadth.use = use
        try:
            r = run_backtest(frames[csv_path.stem], cfg, breadth=breadth)
        except Exception:  # noqa: BLE001
            continue
        wins += round(r["win_rate"] * r["n"]); n += r["n"]
        pnl += r["total_pnl_price"]
    return n, (wins / n if n else 0.0), pnl


def main() -> None:
    p = argparse.ArgumentParser(description="US-stock breadth regime-gate A/B")
    p.add_argument("--strategy", default="donchian",
                   choices=("donchian", "fibonacci", "macd"))
    p.add_argument("--data-dir", default="data")
    p.add_argument("--lookback", type=int, default=100,
                   help="bars defining a new high / new low (default 100)")
    p.add_argument("--min-net", type=float, default=0.0,
                   help="required |net breadth| to allow a trade (default 0)")
    p.add_argument("--sweep", default=None,
                   help="comma list of min-net thresholds; one AGGREGATE row each")
    args = p.parse_args()

    all_csvs = sorted(Path(args.data_dir).glob("*_h1.csv"))
    csvs = [c for c in all_csvs if is_universe_member(c.stem)]
    if not csvs:
        sys.stderr.write(
            f"no US-stock CSVs in {args.data_dir}/ (looked for the US_STOCKS "
            "universe) — run dump_history.py first\n"
        )
        sys.exit(2)

    frames = {c.stem: load_csv(c) for c in csvs}
    breadth = compute_breadth(frames, args.lookback)
    print(f"# breadth built from {len(frames)} US stocks, lookback={args.lookback} "
          f"(net range {int(breadth.min())}..{int(breadth.max())})")

    if args.sweep is not None:
        thresholds = [float(x) for x in args.sweep.split(",") if x.strip()]
        bn, bw, bp = _aggregate(csvs, frames, breadth, args, args.min_net, use=False)
        print(f"# {args.strategy} breadth-gate SWEEP over min_net")
        hdr = f"{'min_net':>8} | {'n':>5} {'win%':>6} {'pnl':>12} | {'Δn':>5} {'Δwin':>6} {'Δpnl':>12}"
        print(hdr)
        print("-" * len(hdr))
        print(f"{'base':>8} | {bn:>5} {bw:>6.1%} {bp:>12.2f} | {'':>5} {'':>6} {'':>12}")
        for mn in thresholds:
            n, w, pnl = _aggregate(csvs, frames, breadth, args, mn, use=True)
            print(f"{mn:>8g} | {n:>5} {w:>6.1%} {pnl:>12.2f} | "
                  f"{n - bn:>+5} {w - bw:>+6.1%} {pnl - bp:>+12.2f}")
        return

    hdr = (
        f"{'symbol':<12} | {'n':>4} {'win%':>6} {'pnl':>10}  (base) | "
        f"{'n':>4} {'win%':>6} {'pnl':>10}  (breadth) | {'Δwin':>6} {'Δpnl':>10}"
    )
    print(f"# {args.strategy} breadth-gate A/B  (min_net={args.min_net:g})")
    print(hdr)
    print("-" * len(hdr))

    base_wins = base_n = g_wins = g_n = 0
    base_pnl = g_pnl = 0.0
    lifted = hurt = 0
    for csv_path in csvs:
        symbol = csv_path.stem.replace("_h1", "")
        base = copy.deepcopy(_base_cfg(csv_path, args)); base.breadth.use = False
        gated = copy.deepcopy(_base_cfg(csv_path, args)); gated.breadth.use = True
        try:
            rb = run_backtest(frames[csv_path.stem], base, breadth=breadth)
            rg = run_backtest(frames[csv_path.stem], gated, breadth=breadth)
        except Exception as exc:  # noqa: BLE001
            print(f"{symbol:<12} | ERROR: {exc}")
            continue
        dwin = rg["win_rate"] - rb["win_rate"]
        dpnl = rg["total_pnl_price"] - rb["total_pnl_price"]
        print(
            f"{symbol:<12} | {rb['n']:>4} {rb['win_rate']:>6.1%} "
            f"{rb['total_pnl_price']:>10.2f}  (base) | "
            f"{rg['n']:>4} {rg['win_rate']:>6.1%} "
            f"{rg['total_pnl_price']:>10.2f}  (breadth) | "
            f"{dwin:>+6.1%} {dpnl:>+10.2f}"
        )
        base_wins += round(rb["win_rate"] * rb["n"]); base_n += rb["n"]
        g_wins += round(rg["win_rate"] * rg["n"]); g_n += rg["n"]
        base_pnl += rb["total_pnl_price"]; g_pnl += rg["total_pnl_price"]
        if rb["n"] and rg["n"]:
            lifted += dwin > 0
            hurt += dwin < 0

    bw = base_wins / base_n if base_n else 0.0
    gw = g_wins / g_n if g_n else 0.0
    print("-" * len(hdr))
    print(
        f"{'AGGREGATE':<12} | {base_n:>4} {bw:>6.1%} {base_pnl:>10.2f}  (base) | "
        f"{g_n:>4} {gw:>6.1%} {g_pnl:>10.2f}  (breadth) | "
        f"{gw - bw:>+6.1%} {g_pnl - base_pnl:>+10.2f}"
    )
    print(
        f"# trade-weighted win rate {bw:.1%} -> {gw:.1%}; "
        f"symbols lifted : {lifted}, hurt : {hurt}; total trades {base_n} -> {g_n}"
    )


if __name__ == "__main__":
    main()
