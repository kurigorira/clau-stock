import logging
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.executor import Executor  # noqa: E402


def _executor(cap: int) -> Executor:
    cfg = Config()
    cfg.symbol = "AAPL"
    cfg.risk.max_total_positions = cap
    return Executor(cfg, logging.getLogger("test"), account="1")


def test_cap_zero_is_off_and_never_calls_mt5():
    ex = _executor(0)
    with patch("gold_trader.executor.mt5_client.positions_total_count") as count:
        assert ex._portfolio_cap_reached() is False
        count.assert_not_called()


def test_cap_blocks_at_and_above_limit():
    ex = _executor(3)
    with patch("gold_trader.executor.mt5_client.positions_total_count",
               return_value=3):
        assert ex._portfolio_cap_reached() is True
    with patch("gold_trader.executor.mt5_client.positions_total_count",
               return_value=7):
        assert ex._portfolio_cap_reached() is True


def test_cap_allows_below_limit():
    ex = _executor(3)
    with patch("gold_trader.executor.mt5_client.positions_total_count",
               return_value=2):
        assert ex._portfolio_cap_reached() is False


def test_cap_fails_open_on_count_error():
    ex = _executor(3)
    with patch("gold_trader.executor.mt5_client.positions_total_count",
               side_effect=RuntimeError("terminal gone")):
        assert ex._portfolio_cap_reached() is False
