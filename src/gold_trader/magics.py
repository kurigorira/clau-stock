"""Magic-number collision detection.

A magic number is how a position is claimed: the executor looks up its own
positions by (symbol, magic), reports attribute a closed deal to a strategy
by magic, and the daily guard counts losses by magic. Two configs sharing
one therefore break things in two quite different ways:

- **Different symbols** — position ownership is still unambiguous, because
  the symbol differs. What breaks is every magic -> strategy lookup: the
  index keeps one config per magic, so trades get filed under whichever
  config happened to load last. Reports lie; trading is unaffected.

- **Same symbol** — the two configs are indistinguishable at the broker.
  Whichever bot polls first can manage, and close, the other's position.
  This one is a live-trading hazard, not a reporting one.

Both are worth refusing to launch over, but only the second is urgent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

__all__ = ["ConfigMagic", "Collision", "scan_magics", "find_collisions", "format_collisions"]


@dataclass(frozen=True)
class ConfigMagic:
    path: str
    symbol: str
    magic: int
    strategy: str = ""


@dataclass
class Collision:
    magic: int
    entries: list[ConfigMagic] = field(default_factory=list)

    @property
    def same_symbol(self) -> bool:
        """True when the clash is over one instrument - the dangerous case."""
        return len({e.symbol for e in self.entries}) < len(self.entries)

    @property
    def symbols(self) -> list[str]:
        seen, out = set(), []
        for e in self.entries:
            if e.symbol not in seen:
                seen.add(e.symbol)
                out.append(e.symbol)
        return out


def scan_magics(paths) -> list[ConfigMagic]:
    """Read `symbol` / `execution.magic_number` / `strategy` from each YAML.

    Files without both a symbol and a magic are skipped: they are not
    presets and cannot own a position (watchlist.yaml and friends).
    """
    out: list[ConfigMagic] = []
    for p in sorted({Path(x) for x in paths}):
        try:
            raw = yaml.safe_load(Path(p).read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            continue
        if not isinstance(raw, dict):
            continue
        symbol = raw.get("symbol")
        magic = (raw.get("execution") or {}).get("magic_number")
        if not isinstance(symbol, str) or not isinstance(magic, int):
            continue
        out.append(
            ConfigMagic(path=str(p), symbol=symbol, magic=magic,
                        strategy=str(raw.get("strategy", "")))
        )
    return out


def find_collisions(entries: list[ConfigMagic]) -> list[Collision]:
    """Magics claimed by more than one config, dangerous ones first."""
    by_magic: dict[int, list[ConfigMagic]] = {}
    for e in entries:
        by_magic.setdefault(e.magic, []).append(e)
    out = [Collision(magic=m, entries=v) for m, v in by_magic.items() if len(v) > 1]
    out.sort(key=lambda c: (not c.same_symbol, c.magic))
    return out


def format_collisions(collisions: list[Collision], *, limit: int = 40) -> str:
    if not collisions:
        return "no magic-number collisions"

    danger = [c for c in collisions if c.same_symbol]
    rest = [c for c in collisions if not c.same_symbol]
    lines: list[str] = [
        f"{len(collisions)} magic number(s) claimed by more than one config "
        f"({len(danger)} on the SAME symbol)",
        "",
    ]
    if danger:
        lines.append("SAME SYMBOL - two bots can manage and close one position:")
        for c in danger[:limit]:
            lines.append(f"  {c.magic}  {c.symbols[0]}")
            for e in c.entries:
                lines.append(f"      {e.path}  strategy={e.strategy or '?'}")
        if len(danger) > limit:
            lines.append(f"  ... and {len(danger) - limit} more")
        lines.append("")
    if rest:
        lines.append("different symbols - trading is safe, but every magic -> "
                     "strategy lookup is unreliable:")
        for c in rest[:limit]:
            lines.append(f"  {c.magic}  {', '.join(c.symbols)}")
        if len(rest) > limit:
            lines.append(f"  ... and {len(rest) - limit} more")
    return "\n".join(lines)
