"""Is an A/B pair actually an A/B? Diff two fleets' settings.

Two fleets meant to differ by exactly one gate should differ by exactly
that gate. This loads both sides, matches them by symbol, and reports every
setting that differs - and, more usefully, every setting that does NOT
differ when it was supposed to.

Reads the YAMLs only; it never connects to MT5, so it works with the market
shut and without credentials.

Usage:
    python scripts/diag_fleet_diff.py config/us_fleet/*.yaml -- config/us_fleet_a2/*.yaml
    python scripts/diag_fleet_diff.py --expect stoch.use \\
        config/us_fleet/*.yaml -- config/us_fleet_a2/*.yaml
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402


def flatten(cfg: Config) -> dict[str, object]:
    """Config -> {'stoch.use': True, 'risk.per_trade_pct': 0.25, ...}."""
    out: dict[str, object] = {}

    def walk(obj, prefix: str) -> None:
        for f in fields(obj):
            value = getattr(obj, f.name)
            key = f"{prefix}{f.name}"
            if is_dataclass(value):
                walk(value, key + ".")
            else:
                out[key] = value

    walk(cfg, "")
    return out


def split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    """Everything before '--' is side A, everything after is side B."""
    if "--" not in argv:
        return argv, []
    i = argv.index("--")
    return argv[:i], argv[i + 1:]


def main() -> None:
    p = argparse.ArgumentParser(
        description="diff two fleets' settings",
        epilog="separate the two fleets with --",
    )
    p.add_argument("--expect", action="append", default=[], metavar="KEY",
                   help="a setting that MUST differ (e.g. stoch.use). Repeatable. "
                        "Exits non-zero if it does not differ on every symbol")
    p.add_argument("--ignore", action="append", default=["execution.magic_number"],
                   metavar="KEY", help="settings expected to differ; not reported")
    known, rest = p.parse_known_args()
    left_args, right_args = split_argv(rest)

    if not left_args or not right_args:
        sys.stderr.write(
            "need two fleets separated by --, e.g.\n"
            "  python scripts/diag_fleet_diff.py config/us_fleet/*.yaml -- "
            "config/us_fleet_a2/*.yaml\n"
        )
        sys.exit(2)

    left = {Config.from_yaml(x).symbol: flatten(Config.from_yaml(x))
            for x in expand_paths(left_args)}
    right = {Config.from_yaml(x).symbol: flatten(Config.from_yaml(x))
             for x in expand_paths(right_args)}

    shared = sorted(set(left) & set(right))
    only_left = sorted(set(left) - set(right))
    only_right = sorted(set(right) - set(left))

    print(f"fleet A: {len(left)} symbols    fleet B: {len(right)} symbols    "
          f"shared: {len(shared)}")
    if only_left or only_right:
        print(f"  only in A ({len(only_left)}): {', '.join(only_left[:10])}"
              f"{' ...' if len(only_left) > 10 else ''}")
        print(f"  only in B ({len(only_right)}): {', '.join(only_right[:10])}"
              f"{' ...' if len(only_right) > 10 else ''}")
        print("  a live A/B needs the same symbols on both sides")
    if not shared:
        sys.exit(1)

    # key -> how many shared symbols differ on it, plus one example
    counts: dict[str, int] = {}
    example: dict[str, tuple[str, object, object]] = {}
    for sym in shared:
        a, b = left[sym], right[sym]
        for key in sorted(set(a) | set(b)):
            if key in known.ignore:
                continue
            va, vb = a.get(key, "<missing>"), b.get(key, "<missing>")
            if va != vb:
                counts[key] = counts.get(key, 0) + 1
                example.setdefault(key, (sym, va, vb))

    print()
    if counts:
        print("settings that differ:")
        for key, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            sym, va, vb = example[key]
            scope = "all" if n == len(shared) else f"{n}/{len(shared)}"
            print(f"  {key:<34} {scope:>8} symbols   A={va!r}  B={vb!r}  (e.g. {sym})")
    else:
        print("settings that differ: NONE")
        print("  the two fleets are identical apart from the ignored keys, so "
              "they are not testing anything against each other")

    failed = False
    for key in known.expect:
        n = counts.get(key, 0)
        if n == len(shared):
            print(f"\nOK  {key} differs on all {n} shared symbols")
        else:
            failed = True
            print(f"\nFAIL {key} differs on only {n}/{len(shared)} shared symbols")
            a_val = left[shared[0]].get(key, "<missing>")
            b_val = right[shared[0]].get(key, "<missing>")
            print(f"     A={a_val!r}  B={b_val!r} on {shared[0]}")
            print("     the A/B is not isolating this setting; regenerate the "
                  "B fleet with the flag that sets it")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
