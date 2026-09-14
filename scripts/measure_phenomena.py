"""Does the effect exist in THIS universe, and what survives costs?

Measures two phenomena on the dumped H1 data. Neither is a strategy and
neither fits a parameter - the point is to find out whether there is anything
to build on before building.

  1. overnight vs intraday
     US equity returns have historically accrued between the close and the
     next open rather than during the session: payment for carrying gap risk,
     not a forecast, which is why it survived being known. On a CFD the
     financing charge falls on exactly that window, so what matters is the
     figure net of YOUR swap, not the published effect.

  2. cross-sectional reversal
     Buying 100 large caps at once is one bet on the market wearing the
     costume of a hundred. Ranking them and going long the weakest against
     the strongest removes the common factor. The gain is less in return than
     in evidence: one roughly independent observation per session instead of
     one per position, so a real effect announces itself in weeks rather than
     quarters.

Both are reported across a sweep of costs, because at this horizon the honest
answer is usually that the effect is real and the spread eats it - and the
sweep says exactly where the line is.

Usage:
    python scripts/measure_phenomena.py config/us_fleet/*.yaml
    python scripts/measure_phenomena.py --lookback 5 config/us_fleet/*.yaml
    python scripts/measure_phenomena.py --trials 20 config/us_fleet/*.yaml
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.data import load_csv  # noqa: E402
from gold_trader.phenomena import (  # noqa: E402
    cross_sectional_reversal,
    expected_max_sharpe,
    overnight_intraday,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
COSTS = (0.0, 2.0, 5.0, 10.0)


def _csv_for(symbol: str) -> Path | None:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", symbol.lower())
    alnum = "".join(c for c in symbol.lower() if c.isalnum())
    for name in (safe, alnum):
        p = DATA_DIR / f"{name}_h1.csv"
        if p.exists():
            return p
    return None


def _line(label: str, s, bar: float) -> str:
    verdict = "clears" if s.sharpe > bar else "under"
    return (f"  {label:<12} {s.n:>7} {s.mean * 10_000:>10.2f} {s.win_rate * 100:>8.1f} "
            f"{s.t_stat:>8.2f} {s.sharpe:>8.2f}  {verdict}")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    p = argparse.ArgumentParser(description="measure phenomena, not strategies")
    p.add_argument("configs", nargs="+")
    p.add_argument("--lookback", type=int, default=1,
                   help="sessions the reversal ranks on (default 1)")
    p.add_argument("--quantile", type=float, default=0.2,
                   help="fraction of the universe in each leg (default 0.2)")
    p.add_argument("--trials", type=int, default=20,
                   help="how many strategy variants you have judged on this data; "
                        "sets the Sharpe a worthless idea already reaches (default 20)")
    args = p.parse_args()

    cfgs = [Config.from_yaml(x) for x in expand_paths(args.configs)]
    frames: dict = {}
    for cfg in cfgs:
        csv = _csv_for(cfg.symbol)
        if csv is None:
            continue
        df = load_csv(csv)
        if len(df) >= 100:
            frames[cfg.symbol] = df
    if len(frames) < 4:
        sys.stderr.write("need at least 4 symbols with dumped data - "
                         "run scripts/dump_history.py first\n")
        sys.exit(2)

    span = max(df.index.max() for df in frames.values()) - \
        min(df.index.min() for df in frames.values())
    print(f"phenomena on {len(frames)} symbols, {span.days} days of H1 bars")
    print()

    # ---- 1. overnight vs intraday -----------------------------------------
    print("1. OVERNIGHT vs INTRADAY  (per-session legs, pooled over symbols)")
    print(f"  {'':<12} {'n':>7} {'mean bp':>10} {'win %':>8} {'t':>8} {'sharpe':>8}")
    for cost in COSTS:
        over, intra, _ = overnight_intraday(frames, cost_bp=cost)
        bar = expected_max_sharpe(args.trials, over.n)
        print(f"  --- {cost:g}bp per side (bar for {args.trials} trials: "
              f"sharpe {bar:.2f}) ---")
        print(_line("overnight", over, bar))
        print(_line("intraday", intra, bar))
    print()
    print("  Pooled legs share each day's market move, so n overstates the")
    print("  independent evidence and t is optimistic. Read the SIGN and the")
    print("  size; treat t as an upper bound.")
    print()

    # ---- 2. cross-sectional reversal --------------------------------------
    print(f"2. CROSS-SECTIONAL REVERSAL  (rank on {args.lookback} session(s), "
          f"long/short the extreme {args.quantile:.0%}, held one session)")
    print(f"  {'':<12} {'days':>7} {'mean bp':>10} {'win %':>8} {'t':>8} {'sharpe':>8}")
    for cost in COSTS:
        st, n_sym = cross_sectional_reversal(
            frames, lookback=args.lookback, quantile=args.quantile, cost_bp=cost
        )
        bar = expected_max_sharpe(args.trials, st.n)
        print(_line(f"{cost:g}bp/side", st, bar))
    print()
    st, n_sym = cross_sectional_reversal(frames, lookback=args.lookback,
                                         quantile=args.quantile)
    if st.n:
        print(f"  One observation per session, {n_sym} symbols netted against each")
        print(f"  other, so these {st.n} days are close to independent - unlike the")
        print("  per-trade counts everywhere else in this repo, where 100 open")
        print("  positions in one direction are a single bet on the market.")
    print()
    print("Reading this: 'under' means the figure does not clear what the best of")
    print(f"{args.trials} worthless variants would already show on a sample this")
    print("size. Only a result that clears it is worth building on, and only the")
    print("cost column you actually pay counts.")


if __name__ == "__main__":
    main()
