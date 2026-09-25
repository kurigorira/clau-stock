import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import notify  # noqa: E402
from gold_trader.config import Config  # noqa: E402
from gold_trader.strategy import Signal  # noqa: E402


def _signal() -> Signal:
    return Signal(
        side="buy",
        stop=1800.0,
        entry_ref=1820.0,
        atr=5.5,
        donch_high=1819.0,
        donch_low=1790.0,
        h4_trend_dir=1,
    )


def _log() -> logging.Logger:
    return logging.getLogger("test_notify")


def _env(**kw: str) -> dict[str, str]:
    base = {
        "GMAIL_USER": "bot@example.com",
        "GMAIL_APP_PASSWORD": "x" * 16,
        "NOTIFY_TO": "g5kurihara@gmail.com",
    }
    base.update(kw)
    return base


def setup_function(_):
    notify.reset_throttle()


def test_send_signal_mail_sends_when_env_set():
    cfg = Config()
    smtp_instance = MagicMock()
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = smtp_instance
        sent = notify.send_signal_mail(
            symbol="XAUUSD",
            side="buy",
            signal=_signal(),
            order_result={"ticket": 123, "price": 1820.5, "volume": 0.01},
            cfg=cfg,
            account="1",
            log=_log(),
        )
    assert sent is True
    smtp_cls.assert_called_once_with("smtp.gmail.com", 465, timeout=15)
    smtp_instance.login.assert_called_once_with("bot@example.com", "x" * 16)
    smtp_instance.send_message.assert_called_once()
    sent_msg = smtp_instance.send_message.call_args[0][0]
    assert sent_msg["Subject"] == "[clau-stock acc1] XAUUSD BUY signal"
    assert sent_msg["To"] == "g5kurihara@gmail.com"
    body = sent_msg.get_content()
    assert "XAUUSD" in body
    assert "ticket      : 123" in body
    assert "H4 trend    : UP" in body
    assert "stop loss   : 1800.0" in body
    assert "fill price  : 1820.5" in body


def test_send_signal_mail_noop_when_env_missing():
    cfg = Config()
    with patch.dict("os.environ", {"GMAIL_USER": "", "GMAIL_APP_PASSWORD": "", "NOTIFY_TO": ""}, clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls:
        sent = notify.send_signal_mail(
            symbol="XAUUSD", side="buy", signal=_signal(),
            order_result=None, cfg=cfg, account="1", log=_log(),
        )
    assert sent is False
    smtp_cls.assert_not_called()


def test_send_signal_mail_noop_when_disabled():
    cfg = Config()
    cfg.notify.enabled = False
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls:
        sent = notify.send_signal_mail(
            symbol="XAUUSD", side="buy", signal=_signal(),
            order_result=None, cfg=cfg, account="1", log=_log(),
        )
    assert sent is False
    smtp_cls.assert_not_called()


def test_throttle_blocks_second_send_within_window():
    cfg = Config()
    cfg.notify.throttle_sec = 60
    times = iter([1000.0, 1030.0])  # 30s apart, within throttle window
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls, patch.object(notify, "_time", lambda: next(times)):
        smtp_cls.return_value.__enter__.return_value = MagicMock()
        first = notify.send_signal_mail(
            symbol="XAUUSD", side="buy", signal=_signal(),
            order_result=None, cfg=cfg, account="1", log=_log(),
        )
        second = notify.send_signal_mail(
            symbol="XAUUSD", side="buy", signal=_signal(),
            order_result=None, cfg=cfg, account="1", log=_log(),
        )
    assert first is True
    assert second is False
    # Only one SMTP session was opened
    assert smtp_cls.call_count == 1


def test_throttle_allows_send_after_window():
    cfg = Config()
    cfg.notify.throttle_sec = 60
    times = iter([1000.0, 1100.0])  # 100s apart, past the 60s window
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls, patch.object(notify, "_time", lambda: next(times)):
        smtp_cls.return_value.__enter__.return_value = MagicMock()
        first = notify.send_signal_mail(
            symbol="XAUUSD", side="buy", signal=_signal(),
            order_result=None, cfg=cfg, account="1", log=_log(),
        )
        second = notify.send_signal_mail(
            symbol="XAUUSD", side="buy", signal=_signal(),
            order_result=None, cfg=cfg, account="1", log=_log(),
        )
    assert first is True
    assert second is True
    assert smtp_cls.call_count == 2


def test_throttle_is_per_symbol_side():
    cfg = Config()
    cfg.notify.throttle_sec = 60
    times = iter([1000.0, 1010.0])  # different keys, both within window
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls, patch.object(notify, "_time", lambda: next(times)):
        smtp_cls.return_value.__enter__.return_value = MagicMock()
        a = notify.send_signal_mail(
            symbol="XAUUSD", side="buy", signal=_signal(),
            order_result=None, cfg=cfg, account="1", log=_log(),
        )
        b = notify.send_signal_mail(
            symbol="EURUSD", side="sell", signal=_signal(),
            order_result=None, cfg=cfg, account="1", log=_log(),
        )
    assert a is True
    assert b is True
    assert smtp_cls.call_count == 2


def test_smtp_failure_does_not_raise():
    cfg = Config()
    with patch.dict("os.environ", _env(), clear=False), patch(
        "smtplib.SMTP_SSL"
    ) as smtp_cls:
        smtp_cls.side_effect = RuntimeError("smtp boom")
        sent = notify.send_signal_mail(
            symbol="XAUUSD", side="buy", signal=_signal(),
            order_result=None, cfg=cfg, account="1", log=_log(),
        )
    assert sent is False
