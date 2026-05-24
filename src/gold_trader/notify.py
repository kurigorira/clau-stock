"""Gmail SMTP signal notifier.

Sends a one-line email to NOTIFY_TO whenever the executor opens a position.
Credentials live in env vars (GMAIL_USER, GMAIL_APP_PASSWORD, NOTIFY_TO) so
nothing sensitive is checked in. If any required var is missing the
notifier silently no-ops, so a broken email setup never stops the bot.

Throttled per (symbol, side) to avoid duplicate emails when the same bar
triggers more than once across a short loop window.
"""
from __future__ import annotations

import logging
import os
import smtplib
import time as time_mod
from email.message import EmailMessage
from typing import Optional

from .config import Config
from .strategy import Signal


_last_sent: dict[str, float] = {}


def _time() -> float:
    # indirection so tests can monkeypatch
    return time_mod.time()


def _build_message(
    symbol: str,
    side: str,
    signal: Signal,
    order_result: Optional[dict],
    cfg: Config,
    account: Optional[str],
    sender: str,
    recipient: str,
) -> EmailMessage:
    acc_tag = f"acc{account}" if account else "acc?"
    subject = f"[clau-stock {acc_tag}] {symbol} {side.upper()} signal"
    fill_price = order_result.get("price") if order_result else None
    fill_volume = order_result.get("volume") if order_result else None
    ticket = order_result.get("ticket") if order_result else None
    trend_label = {1: "UP", -1: "DOWN", 0: "FLAT"}.get(signal.h4_trend_dir, "?")
    body = (
        f"symbol      : {symbol}\n"
        f"side        : {side}\n"
        f"account     : {account}\n"
        f"H4 trend    : {trend_label} (dir={signal.h4_trend_dir})\n"
        f"entry ref   : {signal.entry_ref}\n"
        f"fill price  : {fill_price}\n"
        f"volume      : {fill_volume}\n"
        f"stop loss   : {signal.stop}\n"
        f"atr         : {signal.atr:.5f}\n"
        f"donch high  : {signal.donch_high}\n"
        f"donch low   : {signal.donch_low}\n"
        f"timeframe   : {cfg.timeframe} (higher={cfg.trend.higher_timeframe or 'OFF'})\n"
        f"magic       : {cfg.execution.magic_number}\n"
        f"ticket      : {ticket}\n"
    )
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)
    return msg


def send_signal_mail(
    symbol: str,
    side: str,
    signal: Signal,
    order_result: Optional[dict],
    cfg: Config,
    account: Optional[str],
    log: logging.Logger,
) -> bool:
    """Best-effort signal email. Returns True iff a message was actually sent."""
    if not cfg.notify.enabled:
        return False

    sender = os.environ.get("GMAIL_USER")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("NOTIFY_TO") or sender
    if not sender or not password or not recipient:
        log.debug("notify: GMAIL_USER / GMAIL_APP_PASSWORD / NOTIFY_TO not set; skipping")
        return False

    key = f"{symbol}:{side}"
    now = _time()
    last = _last_sent.get(key, 0.0)
    if now - last < cfg.notify.throttle_sec:
        log.debug("notify: throttled (%ds < %ds) for %s", now - last, cfg.notify.throttle_sec, key)
        return False

    msg = _build_message(symbol, side, signal, order_result, cfg, account, sender, recipient)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        log.warning("notify: send failed: %s", exc)
        return False

    _last_sent[key] = now
    log.info("notify: mail sent to %s for %s %s", recipient, symbol, side)
    return True


def reset_throttle() -> None:
    """Test helper: clear the per-symbol last-sent cache."""
    _last_sent.clear()
