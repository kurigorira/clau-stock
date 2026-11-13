"""Do two configs claim the same magic number?

A magic number is how a position is claimed. Two configs sharing one either
corrupt every magic -> strategy lookup (different symbols) or let two bots
manage and close the same position (same symbol). Neither is visible in a
log line; both are visible here.

Scans config/ and its fleet subdirectories by default.

Usage:
    python scripts/diag_magic_collisions.py
    python scripts/diag_magic_collisions.py config/us_fleet/*.yaml config/*.yaml
    python scripts/diag_magic_collisions.py --free-range 100   # suggest a base

Exits 1 on any collision, 2 when a same-symbol collision exists, so it can
gate a launch.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.magics import (  # noqa: E402
    find_collisions,
    format_collisions,
    scan_magics,
)

REPO = Path(__file__).resolve().parents[1]


def _default_paths() -> list[str]:
    cfg = REPO / "config"
    return [str(p) for p in sorted(cfg.rglob("*.yaml"))]


def _suggest_base(used: set[int], size: int) -> int:
    """Lowest 100-aligned base with `size` consecutive free magics above it."""
    base = (max(used) // 100 + 1) * 100 if used else 20270100
    while any(m in used for m in range(base, base + size)):
        base += 100
    return base


def main() -> None:
    p = argparse.ArgumentParser(description="find magic-number collisions")
    p.add_argument("configs", nargs="*", help="YAMLs to scan (default: config/**.yaml)")
    p.add_argument("--free-range", type=int, default=0, metavar="N",
                   help="also suggest a magic base with N consecutive free numbers")
    args = p.parse_args()

    paths = expand_paths(args.configs) if args.configs else _default_paths()
    entries = scan_magics(paths)
    print(f"scanned {len(paths)} file(s), {len(entries)} with a symbol and a magic")
    print()

    collisions = find_collisions(entries)
    print(format_collisions(collisions))

    if args.free_range > 0:
        used = {e.magic for e in entries}
        base = _suggest_base(used, args.free_range)
        print()
        print(f"a free block of {args.free_range}: --magic-base {base} "
              f"(covers {base}-{base + args.free_range - 1})")

    if any(c.same_symbol for c in collisions):
        sys.exit(2)
    sys.exit(1 if collisions else 0)


if __name__ == "__main__":
    main()
