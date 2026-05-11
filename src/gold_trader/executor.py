"""Live execution loop. Polls the latest closed bar and acts at most once per bar."""
from __future__ import annotations

import logging
import time as time_mod
from datetime import datetime, timezone

import pandas as pd

from . import mt5_client
from .config import Config
from .risk import position_volume
from .strategy import add_indicators, evaluate_last_bar, should_exit


_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class Executor:
    def __init__(self, cfg: Config, log: logging.Logger):
        self.cfg = cfg
        self.log = log
        self._last_bar_time: pd.Timestamp | None = None

    def _in_session(self, now: datetime) -> bool:
        s = self.cfg.session
        if _DAY_NAMES[now.weekday()] not in s.trade_days:
            return False
        t = now.time()
        return s.start_utc <= t <= s.end_utc

    def _bars(self) -> pd.DataFrame:
        warmup = max(
            self.cfg.trend.ema_length,
            self.cfg.breakout.donchian_length,
            self.cfg.risk.atr_length,
            self.cfg.filters.adx_length * 2,
            self.cfg.trend.ema_slope_lookback,
        )
        return mt5_client.fetch_ohlcv(self.cfg.symbol, self.cfg.timeframe, warmup * 4)

    def step(self) -> None:
        now = datetime.now(timezone.utc)
        if not self._in_session(now):
            return

        df = self._bars()
        if len(df) < 2:
            return
        # last row is the still-forming bar; evaluate the one before it
        closed = df.iloc[:-1]
        bar_time = closed.index[-1]
        if self._last_bar_time == bar_time:
            return
        self._last_bar_time = bar_time

        data = add_indicators(closed, self.cfg)
        signal = evaluate_last_bar(data, self.cfg)
        positions = mt5_client.open_positions(
            self.cfg.symbol, self.cfg.execution.magic_number
        )

        # exits first
        for p in positions:
            side = "buy" if p.type == 0 else "sell"  # POSITION_TYPE_BUY = 0
            if should_exit(side, data.iloc[-1]):
                self.log.info(f"exit {side} ticket={p.ticket}")
                mt5_client.close_position(
                    p,
                    deviation=self.cfg.execution.deviation_points,
                    comment=f"{self.cfg.execution.comment}_exit",
                )

        positions = mt5_client.open_positions(
            self.cfg.symbol, self.cfg.execution.magic_number
        )
        if signal.side is None or len(positions) >= self.cfg.risk.max_positions:
            return

        equity = mt5_client.account_equity()

        # Daily guard: skip entries after today's loss streak / cumulative loss
        # crosses configured limits. Resets at UTC midnight.
        realized_pnl, loss_streak = mt5_client.today_closed_pnl(
            self.cfg.symbol, self.cfg.execution.magic_number
        )
        guard = self.cfg.daily_guard
        if loss_streak >= guard.max_consecutive_losses:
            self.log.info(
                f"daily-guard: {loss_streak} consecutive losses today, skipping entry"
            )
            return
        loss_cap = equity * guard.max_loss_pct / 100.0
        if realized_pnl <= -loss_cap:
            self.log.info(
                f"daily-guard: realized loss {realized_pnl:.2f} >= "
                f"{guard.max_loss_pct:.2f}% of equity ({loss_cap:.2f}), skipping entry"
            )
            return

        meta = mt5_client.symbol_meta(self.cfg.symbol)
        stop_distance = abs(signal.entry_ref - signal.stop)
        volume = position_volume(
            equity=equity,
            risk_pct=self.cfg.risk.per_trade_pct,
            stop_distance_price=stop_distance,
            tick_value=meta["trade_tick_value"],
            tick_size=meta["trade_tick_size"],
            volume_min=meta["volume_min"],
            volume_max=meta["volume_max"],
            volume_step=meta["volume_step"],
        )
        if volume <= 0:
            risk_amount = equity * self.cfg.risk.per_trade_pct / 100.0
            money_per_lot = (
                (stop_distance / meta["trade_tick_size"]) * meta["trade_tick_value"]
                if meta["trade_tick_size"] > 0
                else 0.0
            )
            raw = risk_amount / money_per_lot if money_per_lot > 0 else 0.0
            self.log.warning(
                f"volume=0 (below volume_min): equity={equity:.2f} "
                f"risk_pct={self.cfg.risk.per_trade_pct} "
                f"risk_amount={risk_amount:.2f} stop_distance={stop_distance:.2f} "
                f"tick_value={meta['trade_tick_value']} tick_size={meta['trade_tick_size']} "
                f"money_per_lot={money_per_lot:.2f} raw_lots={raw:.4f} "
                f"volume_min={meta['volume_min']}. "
                f"Raise risk.per_trade_pct or lower risk.atr_stop_mult to enable entry."
            )
            return

        self.log.info(
            f"entry side={signal.side} vol={volume} ref={signal.entry_ref} "
            f"stop={signal.stop} atr={signal.atr:.3f}"
        )
        mt5_client.market_order(
            symbol=self.cfg.symbol,
            side=signal.side,
            volume=volume,
            sl=signal.stop,
            tp=None,
            magic=self.cfg.execution.magic_number,
            deviation=self.cfg.execution.deviation_points,
            comment=self.cfg.execution.comment,
        )

    def run_forever(self) -> None:
        # broad except so a transient error (network, broker hiccup) doesn't
        # kill the long-running loop
        self.log.info(f"executor started for {self.cfg.symbol} {self.cfg.timeframe}")
        while True:
            try:
                self.step()
            except Exception as exc:  # noqa: BLE001
                self.log.exception(f"step failed: {exc}")
            time_mod.sleep(self.cfg.execution.poll_seconds)
