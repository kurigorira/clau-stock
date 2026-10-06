"""The alert settings in config/watchlist.yaml: read, check, write.

One definition shared by the alert loop (which reads it) and the settings app
(which writes it), so the two cannot disagree about a default or a range.

Writing preserves the file's comments. watchlist.yaml is mostly explanation,
and a round trip through yaml.dump would strip every line of it - the next
person to open the file would find bare numbers with no idea what they do.
So values are replaced in place, line by line, and the result is re-read and
checked against what was meant before it replaces the original.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = ["FIELDS", "Field", "load", "validate", "save", "SettingsError"]


@dataclass(frozen=True)
class Field:
    key: str
    kind: str            # "float" | "int" | "bool"
    default: Any
    lo: float | None = None
    hi: float | None = None


# Ranges are generous on purpose: they exist to catch a typo (50 for 5.0, a
# negative throttle), not to second-guess a deliberate setting.
FIELDS: tuple[Field, ...] = (
    Field("threshold_pct", "float", 2.0, 0.1, 50.0),
    Field("window_minutes", "int", 10, 1, 1440),
    Field("poll_seconds", "int", 30, 5, 3600),
    Field("throttle_sec", "int", 1800, 0, 86400),
    Field("streak_threshold_pct", "float", 5.0, 0.1, 50.0),
    Field("streak_days", "int", 2, 1, 10),
    Field("streak_same_direction", "bool", True),
)
_BY_KEY = {f.key: f for f in FIELDS}

# Broker symbol names as they appear in MT5: NVIDIA.24H, Cocoa-Cr, HK50.r.
_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,31}$")
MAX_EXTRA_SYMBOLS = 200


class SettingsError(Exception):
    """The file could not be read, or a write did not come out as intended."""


def load(path: str | Path) -> dict[str, Any]:
    """Settings with defaults filled in. Raises SettingsError if unreadable."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise SettingsError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SettingsError(f"{path} is not a mapping of settings")
    out: dict[str, Any] = {}
    for f in FIELDS:
        value = raw.get(f.key, f.default)
        try:
            out[f.key] = _coerce(f, value)
        except (TypeError, ValueError):
            out[f.key] = f.default
    out["extra_symbols"] = [str(s) for s in (raw.get("extra_symbols") or [])]
    return out


def _coerce(f: Field, value: Any) -> Any:
    if f.kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("true", "1", "yes", "on"):
                return True
            if v in ("false", "0", "no", "off", ""):
                return False
            raise ValueError(value)
        return bool(value)
    if f.kind == "int":
        if isinstance(value, bool):
            raise ValueError(value)
        as_float = float(value)
        if as_float != int(as_float):
            raise ValueError(value)       # 2.5 days is a typo, not a setting
        return int(as_float)
    return float(value)


def validate(values: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """(clean settings, {key: problem}). Clean is only usable if no problems."""
    clean: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for f in FIELDS:
        if f.key not in values:
            errors[f.key] = "missing"
            continue
        try:
            v = _coerce(f, values[f.key])
        except (TypeError, ValueError):
            errors[f.key] = (
                "must be a whole number" if f.kind == "int"
                else "must be true or false" if f.kind == "bool"
                else "must be a number"
            )
            continue
        if f.lo is not None and v < f.lo:
            errors[f.key] = f"must be at least {_fmt(f.lo)}"
            continue
        if f.hi is not None and v > f.hi:
            errors[f.key] = f"must be at most {_fmt(f.hi)}"
            continue
        clean[f.key] = v

    syms_in = values.get("extra_symbols") or []
    if isinstance(syms_in, str):
        syms_in = syms_in.split()
    syms: list[str] = []
    bad: list[str] = []
    for s in syms_in:
        s = str(s).strip()
        if not s:
            continue
        if not _SYMBOL.match(s):
            bad.append(s)
        elif s not in syms:
            syms.append(s)
    if bad:
        errors["extra_symbols"] = "not a symbol name: " + ", ".join(bad[:5])
    elif len(syms) > MAX_EXTRA_SYMBOLS:
        errors["extra_symbols"] = f"at most {MAX_EXTRA_SYMBOLS} symbols"
    else:
        clean["extra_symbols"] = syms
    return clean, errors


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def _yaml_scalar(f: Field, v: Any) -> str:
    if f.kind == "bool":
        return "true" if v else "false"
    if f.kind == "int":
        return str(int(v))
    return repr(float(v))


def _replace_scalar(lines: list[str], key: str, text: str) -> bool:
    """Swap the value on `key:`'s line, keeping its indentation and comment."""
    pat = re.compile(rf"^(\s*{re.escape(key)}:)([^#\n]*?)(\s*)(#.*)?$")
    for i, line in enumerate(lines):
        m = pat.match(line.rstrip("\n"))
        if not m or line.startswith((" ", "\t")):
            continue  # only top-level keys
        head, old, gap, comment = m.group(1), m.group(2), m.group(3), m.group(4)
        new = f"{head} {text}"
        if comment:
            # keep the comment where it was when the new value still fits
            column = len(head) + len(old) + len(gap)
            new = new.ljust(max(column, len(new) + 1)) + comment
        lines[i] = new + "\n"
        return True
    return False


def _replace_symbols(lines: list[str], symbols: list[str]) -> bool:
    """Rewrite the extra_symbols list. Comment lines around it are left be."""
    for i, line in enumerate(lines):
        if re.match(r"^extra_symbols:", line):
            j = i + 1
            # consume the old list items, but not comments or the next key
            while j < len(lines) and re.match(r"^\s*-\s", lines[j]):
                j += 1
            if symbols:
                block = ["extra_symbols:\n"] + [f"  - {s}\n" for s in symbols]
            else:
                block = ["extra_symbols: []\n"]
            lines[i:j] = block
            return True
    return False


def save(path: str | Path, clean: dict[str, Any]) -> None:
    """Write validated settings, keeping every comment in the file.

    Written to a temporary file, re-read, and compared with what was meant;
    only then does it replace the original, which is kept as .bak. A write
    that does not read back as intended raises and leaves the file alone.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SettingsError(f"cannot read {path}: {exc}") from exc
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"

    missing: list[str] = []
    for f in FIELDS:
        if f.key in clean and not _replace_scalar(
            lines, f.key, _yaml_scalar(f, clean[f.key])
        ):
            missing.append(f"{f.key}: {_yaml_scalar(f, clean[f.key])}\n")
    if "extra_symbols" in clean and not _replace_symbols(lines, clean["extra_symbols"]):
        syms = clean["extra_symbols"]
        missing.extend(["extra_symbols:\n"] + [f"  - {s}\n" for s in syms]
                       if syms else ["extra_symbols: []\n"])
    if missing:
        lines.append("\n# added by the alert settings app\n")
        lines.extend(missing)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    try:
        got = load(tmp)
    except SettingsError as exc:
        tmp.unlink(missing_ok=True)
        raise SettingsError(f"the rewritten file did not parse: {exc}") from exc
    wrong = [k for k, v in clean.items() if got.get(k) != v]
    if wrong:
        tmp.unlink(missing_ok=True)
        raise SettingsError(
            "the rewritten file did not read back as intended for: "
            + ", ".join(wrong)
        )
    shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    os.replace(tmp, path)
