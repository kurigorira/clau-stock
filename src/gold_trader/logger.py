from __future__ import annotations

import logging
import sys
from pathlib import Path


def setup_logging(level: str = "INFO", log_file: str | Path | None = None) -> logging.Logger:
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    # Force UTF-8 on stdout so non-ASCII characters in log messages don't crash
    # the logger on Japanese-locale Windows (cp932 default). errors="replace"
    # is a belt-and-braces fallback if reconfigure isn't available.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    return logging.getLogger("gold_trader")
