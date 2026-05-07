"""Entry point: start the live trading loop.

Usage:
    python scripts/run_live.py config/example.yaml
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.executor import Executor  # noqa: E402
from gold_trader.logger import setup_logging  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: run_live.py <config.yaml>", file=sys.stderr)
        sys.exit(2)
    load_dotenv()
    cfg = Config.from_yaml(sys.argv[1])
    log = setup_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        log_file="logs/live.log",
    )
    creds = MT5Credentials(
        login=int(os.environ["MT5_LOGIN"]),
        password=os.environ["MT5_PASSWORD"],
        server=os.environ["MT5_SERVER"],
        path=os.environ.get("MT5_PATH") or None,
    )
    with connect(creds):
        Executor(cfg, log).run_forever()


if __name__ == "__main__":
    main()
