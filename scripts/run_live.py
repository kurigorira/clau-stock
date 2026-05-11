"""Entry point: start the live trading loop for one or more configs.

Usage:
    python scripts/run_live.py config/example.yaml
    python scripts/run_live.py config/example.yaml config/eurusd.yaml

When multiple configs are given they run in a single process with one shared
MT5 connection. Each instance gets its own child logger so log lines from
different symbols are distinguishable.
"""
from __future__ import annotations

import os
import sys
import time as time_mod
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.executor import Executor  # noqa: E402
from gold_trader.logger import setup_logging  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: run_live.py <config.yaml> [<config.yaml> ...]",
            file=sys.stderr,
        )
        sys.exit(2)
    load_dotenv()
    configs = [Config.from_yaml(p) for p in sys.argv[1:]]
    log = setup_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        log_file=os.environ.get("LOG_FILE") or "logs/live.log",
    )
    creds = MT5Credentials(
        login=int(os.environ["MT5_LOGIN"]),
        password=os.environ["MT5_PASSWORD"],
        server=os.environ["MT5_SERVER"],
        path=os.environ.get("MT5_PATH") or None,
    )
    with connect(creds):
        executors = [Executor(cfg, log.getChild(cfg.symbol)) for cfg in configs]
        for ex in executors:
            log.info(
                f"executor started for {ex.cfg.symbol} {ex.cfg.timeframe} "
                f"(magic={ex.cfg.execution.magic_number})"
            )
        # Use the smallest poll interval so the most aggressive symbol sets the tempo.
        poll = min(c.execution.poll_seconds for c in configs)
        while True:
            for ex in executors:
                try:
                    ex.step()
                except Exception as exc:  # noqa: BLE001
                    log.exception(f"step failed for {ex.cfg.symbol}: {exc}")
            time_mod.sleep(poll)


if __name__ == "__main__":
    main()
