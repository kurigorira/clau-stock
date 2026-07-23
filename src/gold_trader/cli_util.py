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
