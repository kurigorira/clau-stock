"""Small helpers shared by the CLI scripts."""
from __future__ import annotations

import glob


def expand_paths(patterns: list[str]) -> list[str]:
    """Expand glob patterns the shell didn't.

    PowerShell and cmd pass wildcards through literally (unlike POSIX shells),
    so `run_live.py config/us_fleet/*.yaml` arrives as the single argument
    'config/us_fleet/*.yaml'. Arguments containing *, ? or [ are globbed
    (sorted for a stable executor order); plain paths pass through untouched.
    A pattern matching nothing raises FileNotFoundError — silently launching
    an empty fleet would look like success.
    """
    out: list[str] = []
    for p in patterns:
        if any(ch in p for ch in "*?["):
            hits = sorted(glob.glob(p))
            if not hits:
                raise FileNotFoundError(f"no files match {p!r}")
            out.extend(hits)
        else:
            out.append(p)
    return out


def rank_by_spread(names, quote_fn, max_spread_bp=None, prefer=()):
    """Order symbols cheapest-to-trade first, dropping the untradeable ones.

    `quote_fn(name)` returns (bid, ask) or None when no quote is available.
    Spread is expressed in basis points of the mid, which is the same unit the
    cost analysis used — the base MACD strategy went from +42 to -211 at 5bp a
    side, so picking the fleet by spread is picking it by whether the edge
    survives at all.

    Symbols with no quote, a non-positive mid or a crossed book are dropped:
    they are typically synthetic/pre-IPO products or feeds this account cannot
    actually trade. `max_spread_bp` drops anything wider. `prefer` names (the
    curated large caps) win ties, so an equal-spread mega cap outranks an
    unknown micro cap.

    Returns (ranked, dropped) where ranked is [(name, spread_bp), ...] sorted
    ascending and dropped is [(name, reason), ...].
    """
    preferred = {p.lower() for p in prefer}
    ranked, dropped = [], []
    for name in names:
        try:
            quote = quote_fn(name)
        except Exception as exc:  # noqa: BLE001 — one bad symbol must not stop the scan
            dropped.append((name, f"quote failed: {exc}"))
            continue
        if not quote:
            dropped.append((name, "no quote"))
            continue
        bid, ask = float(quote[0]), float(quote[1])
        mid = (bid + ask) / 2.0
        if mid <= 0 or ask < bid:
            dropped.append((name, "no/!crossed market"))
            continue
        spread_bp = (ask - bid) / mid * 1e4
        if max_spread_bp is not None and spread_bp > max_spread_bp:
            dropped.append((name, f"spread {spread_bp:.1f}bp"))
            continue
        ranked.append((name, spread_bp))
    # cheapest first; curated names win ties; name last so the order is stable
    ranked.sort(key=lambda r: (r[1], r[0].lower() not in preferred, r[0]))
    return ranked, dropped
