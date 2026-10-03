import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import alerts, notify  # noqa: E402


def _m1_bars(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="min", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.1 for c in closes],
            "low": [c - 0.1 for c in closes],
            "close": closes,
            "volume": 1,
        },
        index=idx,
    )


def _env() -> dict[str, str]:
    return {
        "GMAIL_USER": "bot@example.com",
        "GMAIL_APP_PASSWORD": "x" * 16,
        "NOTIFY_TO": "g5kurihara@gmail.com",
    }


def setup_function(_):
    notify.reset_throttle()


def test_evaluate_change_returns_pct_over_window():
    # 11 closes -> compare index -1 vs index -11 (10-min window)
    bars = _m1_bars([100.0] * 10 + [102.5])
    change = alerts.evaluate_change("X", bars, window_minutes=10)
    assert change is not None
    assert change.symbol == "X"
    assert change.current_price == 102.5
    assert change.prev_price == 100.0
    assert abs(change.change_pct - 2.5) < 1e-9


def test_evaluate_change_handles_negative_move():
    bars = _m1_bars([100.0] * 10 + [97.0])
    change = alerts.evaluate_change("X", bars, window_minutes=10)
    assert change is not None
    assert abs(change.change_pct - (-3.0)) < 1e-9


def test_evaluate_change_returns_none_when_too_few_bars():
    bars = _m1_bars([100.0] * 5)
    assert alerts.evaluate_change("X", bars, window_minutes=10) is None


def test_evaluate_change_returns_none_on_nan_prev():
    closes = [100.0] * 11
    closes[0] = np.nan  # 10 bars before the latest
    bars = _m1_bars(closes)
    assert alerts.evaluate_change("X", bars, window_minutes=10) is None


def test_should_alert_uses_abs_threshold():
    assert alerts.should_alert(2.5, 2.0) is True
    assert alerts.should_alert(-2.5, 2.0) is True
    assert alerts.should_alert(1.5, 2.0) is False
    assert alerts.should_alert(-1.5, 2.0) is False


# ---------------------------------------------------------------------------
# notify.send_alert_mail
# ---------------------------------------------------------------------------


def test_send_alert_mail_sends_with_correct_subject_and_body():
    smtp_inst = MagicMock()
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = smtp_inst
        sent = notify.send_alert_mail(
            symbol="XAUUSD",
            change_pct=2.34,
            current_price=2400.5,
            prev_price=2345.6,
            window_minutes=10,
            threshold_pct=2.0,
            throttle_sec=1800,
            log=logging.getLogger("test"),
        )
    assert sent is True
    msg = smtp_inst.send_message.call_args[0][0]
    assert msg["Subject"] == "[clau-stock alert] XAUUSD +2.34% in 10min"
    body = msg.get_content()
    assert "XAUUSD" in body
    assert "+2.34%" in body
    assert "2400.5" in body
    assert "2345.6" in body


def test_send_alert_mail_subject_for_negative_move():
    smtp_inst = MagicMock()
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = smtp_inst
        notify.send_alert_mail(
            symbol="BTCUSD",
            change_pct=-3.10,
            current_price=70000.0,
            prev_price=72240.0,
            window_minutes=10,
            threshold_pct=2.0,
            throttle_sec=1800,
            log=logging.getLogger("test"),
        )
    msg = smtp_inst.send_message.call_args[0][0]
    assert msg["Subject"] == "[clau-stock alert] BTCUSD -3.10% in 10min"


def test_send_alert_mail_throttles_same_symbol():
    # Use large absolute times so the initial `last=0` doesn't accidentally
    # fall inside the throttle window.
    times = iter([100000.0, 100500.0])  # 500s apart, within 1800s window
    smtp_inst = MagicMock()
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls, patch.object(notify, "_time", lambda: next(times)):
        smtp_cls.return_value.__enter__.return_value = smtp_inst
        a = notify.send_alert_mail(
            symbol="XAUUSD", change_pct=2.5, current_price=1.0, prev_price=1.0,
            window_minutes=10, threshold_pct=2.0, throttle_sec=1800,
            log=logging.getLogger("test"),
        )
        b = notify.send_alert_mail(
            symbol="XAUUSD", change_pct=-3.0, current_price=1.0, prev_price=1.0,
            window_minutes=10, threshold_pct=2.0, throttle_sec=1800,
            log=logging.getLogger("test"),
        )
    assert a is True
    assert b is False
    assert smtp_cls.call_count == 1


def test_send_alert_mail_per_symbol_throttle_is_independent():
    times = iter([100000.0, 100010.0])
    smtp_inst = MagicMock()
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls, patch.object(notify, "_time", lambda: next(times)):
        smtp_cls.return_value.__enter__.return_value = smtp_inst
        a = notify.send_alert_mail(
            symbol="XAUUSD", change_pct=2.5, current_price=1.0, prev_price=1.0,
            window_minutes=10, threshold_pct=2.0, throttle_sec=1800,
            log=logging.getLogger("test"),
        )
        b = notify.send_alert_mail(
            symbol="BTCUSD", change_pct=2.5, current_price=1.0, prev_price=1.0,
            window_minutes=10, threshold_pct=2.0, throttle_sec=1800,
            log=logging.getLogger("test"),
        )
    assert a is True
    assert b is True


def test_send_alert_mail_noop_when_env_missing():
    with patch.dict(
        "os.environ", {"GMAIL_USER": "", "GMAIL_APP_PASSWORD": "", "NOTIFY_TO": ""}, clear=False
    ), patch("smtplib.SMTP_SSL") as smtp_cls:
        sent = notify.send_alert_mail(
            symbol="XAUUSD", change_pct=2.5, current_price=1.0, prev_price=1.0,
            window_minutes=10, threshold_pct=2.0, throttle_sec=1800,
            log=logging.getLogger("test"),
        )
    assert sent is False
    smtp_cls.assert_not_called()
