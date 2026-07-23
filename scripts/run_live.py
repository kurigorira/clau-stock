"""Entry point: start the live trading loop for one or more configs.

Usage:
    # single-account (legacy .env with MT5_LOGIN, MT5_PASSWORD, ...)
    python scripts/run_live.py config/example.yaml config/eurusd.yaml

    # multi-account (use MT5_LOGIN_1, MT5_PASSWORD_1, ... in .env)
    python scripts/run_live.py --account 1 config/example.yaml config/eurusd.yaml
    python scripts/run_live.py --account 2 config/nvidia.yaml config/sp500ft.yaml

When multiple configs are given they run in a single process with one shared
MT5 connection. To trade two accounts at once, run two separate processes,
each with its own --account flag pointing at a different MT5 terminal.
"""
from __future__ import annotations

import argparse
import os
import sys
import time as time_mod
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.cli_util import expand_paths  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.executor import Executor  # noqa: E402
from gold_trader.logger import setup_logging  # noqa: E402
from gold_trader.mt5_client import MT5Credentials, connect  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="clau-stock live trader")
    parser.add_argument(
        "--account",
        default=None,
        help=(
            "suffix for MT5_* env vars when running multiple accounts "
            "(e.g. --account 1 reads MT5_LOGIN_1, MT5_PASSWORD_1, MT5_SERVER_1, MT5_PATH_1)."
            " Omit for single-account mode (uses MT5_LOGIN etc. without suffix)."
        ),
    )
    parser.add_argument("configs", nargs="+")
    args = parser.parse_args()

    load_dotenv()
    try:
        config_paths = expand_paths(args.configs)  # PowerShell passes globs literally
    except FileNotFoundError as exc:
        sys.stderr.write(f"{exc}\n")
        sys.exit(2)
    configs = [Config.from_yaml(p) for p in config_paths]

    log_file_default = (
        f"logs/account{args.account}.log" if args.account else "logs/live.log"
    )
    log = setup_logging(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        log_file=os.environ.get("LOG_FILE") or log_file_default,
    )

    suffix = f"_{args.account}" if args.account else ""
    try:
        creds = MT5Credentials(
            login=int(os.environ[f"MT5_LOGIN{suffix}"]),
            password=os.environ[f"MT5_PASSWORD{suffix}"],
            server=os.environ[f"MT5_SERVER{suffix}"],
            path=os.environ.get(f"MT5_PATH{suffix}") or None,
        )
    except KeyError as missing:
        sys.stderr.write(
            f"missing env var {missing}. Did you set MT5_LOGIN{suffix} / "
            f"MT5_PASSWORD{suffix} / MT5_SERVER{suffix} in .env?\n"
        )
        sys.exit(2)

    with connect(creds):
        executors = [
            Executor(cfg, log.getChild(cfg.symbol), account=args.account) for cfg in configs
        ]
        account_tag = f" account={args.account}" if args.account else ""
        for ex in executors:
            log.info(
                f"executor started for {ex.cfg.symbol} {ex.cfg.timeframe} "
                f"(magic={ex.cfg.execution.magic_number}){account_tag}"
            )
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
