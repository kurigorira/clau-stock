"""Grid A/B: which combination of the shared gates wins, per strategy?

Runs the chosen strategy over the US-stock universe once per gate combination —
stoch (entry timing / exhaustion), trendline (the symbol's own trend
cleanliness), breadth (whole-market regime) — and prints one aggregate row per
combo, so "which indicator combination maximises win rate" is answered by
measurement instead of taste. The three gates read different information, which
is why stacking them can help; but every extra gate shrinks the trade count, so
a high win% on a thin combo is noise — rows under --min-trades are tagged and
excluded from the best-win%% ranking.

Restricted to US stocks so every combo is comparable (breadth only means
anything inside the universe it is built from).

ret%% sums each trade's unlevered return (pnl / entry price, one equal-weight
unit per trade); ~wk%% divides that by the weeks the data spans. Rows whose
~wk%% clears --target-wk (default 0.5, the weekly profit goal) are marked. It
is a rough per-position yardstick, not an account equity curve — position
sizing / leverage (risk:) decides account returns.

At a 0.5%%/week target transaction costs decide feasibility, so --slippage-bp
charges every entry AND exit that many basis points of the symbol's median
price (a spread+commission proxy); rerun with e.g. 5 and see which combos
survive.

Usage:
    python scripts/ab_combo.py --strategy macd
    python scripts/ab_combo.py --strategy macd --slippage-bp 5
    python scripts/ab_combo.py --strategy macd --min-net 2 --r2-min 0.7
    python scripts/ab_combo.py --strategy fibonacci
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.backtest import run_backtest  # noqa: E402
from gold_trader.breadth import compute_breadth, is_universe_member  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

# every subset of the three shared gates, base first
COMBOS = (
    ("base", ()),
    ("stoch", ("stoch",)),
    ("trend", ("trendline",)),
    ("breadth", ("breadth",)),
    ("stoch+trend", ("stoch", "trendline")),
    ("stoch+breadth", ("stoch", "breadth")),
    ("trend+breadth", ("trendline", "breadth")),
    ("all three", ("stoch", "trendline", "breadth")),
)


def _config_for_csv(csv_path: Path) -> Path | None:
    slug = re.sub(r"[^a-z0-9]", "_", csv_path.stem.removesuffix("_h1").lower())
    candidate = CONFIG_DIR / f"fib_{slug}.yaml"
    return candidate if candidate.exists() else None


def _cfg(csv_path: Path, args, gates: tuple[str, ...]) -> Config:
    matched = _config_for_csv(csv_path)
    cfg = Config.from_yaml(matched) if matched else Config()
    cfg.strategy = args.strategy
    # thresholds are fixed across combos; only the .use flags vary
    cfg.stoch.overbought = args.overbought
    cfg.stoch.oversold = args.oversold
    cfg.trendline.length = args.tl_length
    cfg.trendline.r2_min = args.r2_min
    cfg.breadth.lookback = args.lookback
    cfg.breadth.min_net = args.min_net
    cfg.stoch.use = "stoch" in gates
    cfg.trendline.use = "trendline" in gates
    cfg.breadth.use = "breadth" in gates
    return cfg


def main() -> None:
    p = argparse.ArgumentParser(description="gate-combination grid A/B (US stocks)")
    p.add_argument("--strategy", default="macd",
                   choices=("donchian", "fibonacci", "macd"))
    p.add_argument("--data-dir", default="data")
    p.add_argument("--min-net", type=float, default=1.0,
                   help="breadth threshold (default 1, the measured MACD best)")
    p.add_argument("--lookback", type=int, default=100, help="breadth lookback")
    p.add_argument("--r2-min", type=float, default=0.5, help="trendline R^2 gate")
    p.add_argument("--tl-length", type=int, default=50, help="trendline window")
    p.add_argument("--overbought", type=float, default=80.0)
    p.add_argument("--oversold", type=float, default=20.0)
    p.add_argument("--min-trades", type=int, default=30,
                   help="combos with fewer trades are tagged thin and excluded "
                        "from the best-win%% ranking (default 30)")
    p.add_argument("--target-wk", type=float, default=0.5,
                   help="weekly return goal in %%; rows meeting it are marked "
                        "(default 0.5)")
    p.add_argument("--slippage-bp", type=float, default=0.0,
                   help="per-side cost in basis points of each symbol's median "
                        "price, charged on entry and exit (default 0)")
    args = p.parse_args()

    csvs = [c for c in sorted(Path(args.data_dir).glob("*_h1.csv"))
            if is_universe_member(c.stem)]
    if not csvs:
        sys.stderr.write(f"no US-stock CSVs in {args.data_dir}/\n")
        sys.exit(2)

    frames = {c.stem: load_csv(c) for c in csvs}
    breadth = compute_breadth(frames, args.lookback)
    # per-symbol per-side cost in price units (bp of the median close)
    slips = {s: float(df["close"].median()) * args.slippage_bp / 1e4
             for s, df in frames.items()}
    start = min(df.index[0] for df in frames.values())
    end = max(df.index[-1] for df in frames.values())
    weeks = max((end - start).total_seconds() / (7 * 86400.0), 1e-9)

    print(f"# {args.strategy} gate-combo grid over {len(frames)} US stocks, "
          f"{weeks:.1f} weeks of data; target {args.target_wk:g}%/wk, "
          f"cost {args.slippage_bp:g}bp/side")
    print(f"# thresholds: breadth min_net={args.min_net:g}/lb={args.lookback}, "
          f"trendline r2_min={args.r2_min:g}/len={args.tl_length}, "
          f"stoch OB/OS={args.overbought:g}/{args.oversold:g}")
    hdr = (f"{'combo':<14} | {'n':>5} {'win%':>6} {'pnl':>11} "
           f"{'ret%':>8} {'~wk%':>7}")
    print(hdr)
    print("-" * len(hdr))

    rows = []
    for label, gates in COMBOS:
        n = wins = 0
        pnl = ret = 0.0
        for csv_path in csvs:
            stem = csv_path.stem
            try:
                r = run_backtest(
                    frames[stem], _cfg(csv_path, args, gates),
                    slippage_price=slips[stem], breadth=breadth,
                )
            except Exception:  # noqa: BLE001
                continue
            for t in r["trades"]:
                n += 1
                wins += 1 if t.pnl_price > 0 else 0
                pnl += t.pnl_price
                ret += 100.0 * t.pnl_price / t.entry_price
        win = wins / n if n else 0.0
        wk = ret / weeks
        thin = " (thin)" if n < args.min_trades else ""
        hit = "  <- meets target" if wk >= args.target_wk and not thin else ""
        rows.append((label, n, win, pnl, ret))
        print(f"{label:<14} | {n:>5} {win:>6.1%} {pnl:>11.2f} "
              f"{ret:>8.2f} {wk:>7.3f}{thin}{hit}")

    print("-" * len(hdr))
    solid = [r for r in rows[1:] if r[1] >= args.min_trades]
    if solid:
        bw = max(solid, key=lambda r: r[2])
        bp = max(rows[1:], key=lambda r: r[3])
        base = rows[0]
        print(f"# best win% (n>={args.min_trades}): {bw[0]}  "
              f"{base[2]:.1%} -> {bw[2]:.1%} on {bw[1]} trades")
        print(f"# best PnL:                {bp[0]}  "
              f"{base[3]:+.2f} -> {bp[3]:+.2f}")
    hits = [r[0] for r in rows if r[1] >= args.min_trades
            and r[4] / weeks >= args.target_wk]
    print(f"# combos meeting {args.target_wk:g}%/wk (n>={args.min_trades}): "
          f"{', '.join(hits) if hits else 'NONE'}")
    print("# ret% = sum of per-trade unlevered returns (equal-weight units); "
          "~wk% = ret%/weeks — a rough per-position yardstick, not account equity.")


if __name__ == "__main__":
    main()
