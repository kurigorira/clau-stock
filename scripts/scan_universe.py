"""What US stocks does this broker offer that we aren't trading?

Trade frequency scales with universe size, so the cleanest way to trade more
without loosening a gate is to trade more symbols. This lists the broker's US
equity symbols (found via MT5's symbol `path`, e.g. "Stocks\\US\\AAPL", which
is far more reliable than guessing from names) and splits them into:

  TRADED   — in breadth.US_STOCKS and offered here (the current fleet)
  MISSING  — offered here but NOT in US_STOCKS (free frequency, one edit away)
  ABSENT   — in US_STOCKS but not offered by this broker (dead entries)

`--print-list` emits a ready-to-paste US_STOCKS tuple covering everything the
broker offers.

IMPORTANT after expanding: breadth.min_net is an absolute symbol count, so a
bigger universe makes the same min_net a *relatively* weaker filter. Re-run
scripts/oos_breadth.py once the new CSVs are dumped and re-select min_net —
the tuned value for 34 symbols is not the tuned value for 60.

Usage:
    python scripts/scan_universe.py --account 1
    python scripts/scan_universe.py --account 1 --print-list
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.breadth import US_STOCKS, is_universe_member  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402


def _stem(name: str) -> str:
    return name.lower().split(".")[0]


def main() -> None:
    p = argparse.ArgumentParser(description="scan the broker for US equity symbols")
    p.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    p.add_argument("--path-contains", default="us",
                   help="substring identifying US equities in the symbol path "
                        "(default 'us'; try 'stock' if your broker differs)")
    p.add_argument("--print-list", action="store_true",
                   help="print a US_STOCKS tuple covering every offered symbol")
    args = p.parse_args()

    load_dotenv()
    suffix = f"_{args.account}" if args.account else ""
    try:
        creds = MT5Credentials(
            login=int(os.environ[f"MT5_LOGIN{suffix}"]),
            password=os.environ[f"MT5_PASSWORD{suffix}"],
            server=os.environ[f"MT5_SERVER{suffix}"],
            path=os.environ.get(f"MT5_PATH{suffix}") or None,
        )
    except KeyError as missing:
        sys.stderr.write(f"missing env var {missing}\n")
        sys.exit(2)

    needle = args.path_contains.lower()
    with connect(creds) as mt5:
        syms = mt5.symbols_get() or []
        equities = []
        for s in syms:
            path = (getattr(s, "path", "") or "").lower()
            # keep US-equity groups; drop index/FX/crypto buckets
            if needle in path and not any(
                x in path for x in ("index", "indices", "forex", "crypto", "commodit")
            ):
                equities.append(s.name)

    if not equities:
        sys.stderr.write(
            f"no symbols whose path contains {args.path_contains!r}. "
            "Inspect paths in MT5 (Market Watch > Symbols) and pass "
            "--path-contains accordingly.\n"
        )
        sys.exit(2)

    offered_stems = {}
    for name in equities:
        st = _stem(name)
        # prefer the plain market-hours feed over venue variants (NVIDIA.24h)
        if st not in offered_stems or len(name) < len(offered_stems[st]):
            offered_stems[st] = name

    traded = sorted(n for st, n in offered_stems.items() if is_universe_member(st))
    missing = sorted(n for st, n in offered_stems.items() if not is_universe_member(st))
    absent = sorted(set(US_STOCKS) - set(offered_stems))

    print(f"# broker offers {len(offered_stems)} US equity symbols "
          f"(path contains {args.path_contains!r})")
    print(f"\nTRADED  ({len(traded)}) — in US_STOCKS and offered here")
    print("  " + (", ".join(traded) if traded else "(none)"))
    print(f"\nMISSING ({len(missing)}) — offered here but NOT in US_STOCKS")
    print("  " + (", ".join(missing) if missing else "(none)"))
    if absent:
        print(f"\nABSENT  ({len(absent)}) — in US_STOCKS but not offered here")
        print("  " + ", ".join(absent))

    if missing:
        factor = len(offered_stems) / max(len(traded), 1)
        print(f"\n# adding all {len(missing)} would take the universe "
              f"{len(traded)} -> {len(offered_stems)} symbols ({factor:.1f}x), "
              "scaling trades/week by roughly the same factor.")
        print("# then: dump_history for the new symbols, re-run oos_breadth to "
              "re-select min_net (an absolute count — a bigger universe makes "
              "the old value weaker), then gen_us_fleet.")

    if args.print_list:
        stems = sorted(offered_stems)
        print("\n# paste into src/gold_trader/breadth.py")
        print("US_STOCKS = (")
        for i in range(0, len(stems), 6):
            print("    " + ", ".join(f'"{s}"' for s in stems[i:i + 6]) + ",")
        print(")")


if __name__ == "__main__":
    main()
