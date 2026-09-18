"""What US stocks does this broker offer that we aren't trading?

Trade frequency scales with universe size, so the cleanest way to trade more
without loosening a gate is to trade more symbols. This lists the broker's US
equity symbols (found via MT5's symbol `path`, e.g. "Stocks\\US\\AAPL", which
is far more reliable than guessing from names) and splits them into:

  TRADED   — in breadth.US_STOCKS and offered here (the current fleet)
  MISSING  — offered here but NOT in US_STOCKS (free frequency, one edit away)
  ABSENT   — in US_STOCKS but not offered by this broker (dead entries)

`--print-list` emits ready-to-paste _COMPANY_ROWS entries covering everything
the broker offers. Non-equities that share the "US" path (spot metals, oil,
index CFDs, notes) and duplicate feeds of one company (AAPL vs AAPLUSD vs
ABBV.24H) are filtered and collapsed, so the count is companies, not feeds.

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

from gold_trader.breadth import (  # noqa: E402
    UNIVERSE_FILE,
    is_universe_member,
    looks_like_equity,
    normalize_stem,
)
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402


def _curated_companies() -> set[str]:
    from gold_trader.breadth import _COMPANY_ROWS
    return {row[0] for row in _COMPANY_ROWS}


_CURATED_COMPANIES = _curated_companies()


def _key(name: str) -> str:
    """Company-level key: 'ABBV.24H', 'ABBVIE' and 'ABBVUSD' all collapse here.

    Deduping by raw stem (the earlier behaviour) double-listed the same company
    once per feed, inflating the offered count."""
    from gold_trader.breadth import _VARIANT_TO_COMPANY
    stem = normalize_stem(name)
    return _VARIANT_TO_COMPANY.get(stem) or stem


def main() -> None:
    p = argparse.ArgumentParser(description="scan the broker for US equity symbols")
    p.add_argument("--account", default=None, help="env-var suffix (MT5_LOGIN_N ...)")
    p.add_argument("--path-contains", default="us",
                   help="substring identifying US equities in the symbol path "
                        "(default 'us'; try 'stock' if your broker differs)")
    p.add_argument("--write-universe", nargs="?", const=str(UNIVERSE_FILE),
                   default=None, metavar="PATH",
                   help="write the discovered symbols to PATH (default "
                        "config/us_universe.txt), which breadth.py auto-loads — "
                        "this is how the universe scales without hand-typing "
                        "tickers into the source")
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
            if needle not in path or any(
                x in path for x in ("index", "indices", "forex", "crypto", "commodit")
            ):
                continue
            # spot metals, oil, index CFDs and notes also live under "US"
            if not looks_like_equity(s.name):
                continue
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
        st = _key(name)
        # prefer the plain market-hours feed over venue variants (NVIDIA.24h)
        if st not in offered_stems or len(name) < len(offered_stems[st]):
            offered_stems[st] = name

    traded = sorted(n for st, n in offered_stems.items() if is_universe_member(st))
    missing = sorted(n for st, n in offered_stems.items() if not is_universe_member(st))
    # compare CANONICAL companies, not alias spellings: keying the curated
    # variants against company keys listed 'amazon' as absent while AMAZON traded
    absent = sorted(_CURATED_COMPANIES - set(offered_stems))

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

    if args.write_universe:
        dest = Path(args.write_universe)
        dest.parent.mkdir(parents=True, exist_ok=True)
        lines = ["# US equity symbols discovered on this broker "
                 f"(path contains {args.path_contains!r}).",
                 "# Written by scripts/scan_universe.py --write-universe; "
                 "auto-loaded by breadth.py.",
                 "# Duplicate feeds of one company and non-equities are already "
                 "filtered out.", ""]
        lines += sorted(offered_stems.values())
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\n# wrote {len(offered_stems)} symbols to {dest}")
        print("# next: dump_history for the new symbols, re-run oos_breadth to "
              "re-select min_net, then gen_us_fleet.")

    if args.print_list:
        # emit _COMPANY_ROWS rows (US_STOCKS is derived from them, so pasting a
        # flat US_STOCKS tuple would no longer wire anything up)
        keys = sorted(offered_stems)
        print("\n# paste into _COMPANY_ROWS in src/gold_trader/breadth.py")
        print("    # --- discovered on this broker ---")
        for i in range(0, len(keys), 6):
            row = ", ".join(f'("{k}",)' for k in keys[i:i + 6])
            print(f"    {row},")


if __name__ == "__main__":
    main()
