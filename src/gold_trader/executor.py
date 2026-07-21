"""Live execution loop. Polls the latest closed bar and acts at most once per bar."""
from __future__ import annotations

import logging
import time as time_mod
from datetime import datetime, timezone

import pandas as pd

from . import mt5_client, notify
from .config import Config
from .risk import position_volume
from .strategy import (
    _atr,
    add_indicators,
    evaluate_fib_entry,
    evaluate_last_bar,
    evaluate_macd_entry,
    should_exit,
    should_exit_macd,
)


_DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Refresh the H4 frame at most once per this many seconds. H4 bars only
# close every 4 hours so a 15-min refresh is plenty and slashes the MT5
# copy_rates_from_pos calls per executor by ~30x at poll_seconds=30.
_H4_REFRESH_SEC = 900


class Executor:
    def __init__(self, cfg: Config, log: logging.Logger, account: str | None = None):
        self.cfg = cfg
        self.log = log
        self.account = account
        self._last_bar_time: pd.Timestamp | None = None
        self._h4_cache: pd.DataFrame | None = None
        self._h4_cache_at: float = 0.0

    def _in_session(self, now: datetime) -> bool:
        s = self.cfg.session
        if _DAY_NAMES[now.weekday()] not in s.trade_days:
            return False
        t = now.time()
        return s.start_utc <= t <= s.end_utc

    def _warmup_bars(self) -> int:
        return max(
            self.cfg.trend.ema_length,
            self.cfg.breakout.donchian_length,
            self.cfg.risk.atr_length,
            self.cfg.filters.adx_length * 2,
            self.cfg.trend.ema_slope_lookback,
        )

    def _bars(self) -> pd.DataFrame:
        return mt5_client.fetch_ohlcv(self.cfg.symbol, self.cfg.timeframe, self._warmup_bars() * 4)

    def _bars_h4(self) -> pd.DataFrame | None:
        tf = self.cfg.trend.higher_timeframe
        if not tf:
            return None
        now = time_mod.time()
        if self._h4_cache is not None and (now - self._h4_cache_at) < _H4_REFRESH_SEC:
            return self._h4_cache
        try:
            df = mt5_client.fetch_ohlcv(self.cfg.symbol, tf, self._warmup_bars() * 4)
        except Exception as exc:  # noqa: BLE001
            # If H4 fetch fails, fall back to H1-only for this bar (do not block trading)
            self.log.warning(f"h4 fetch failed, MTF filter disabled this step: {exc}")
            return None
        self._h4_cache = df
        self._h4_cache_at = now
        return df

    def _ensure_stop_losses(self, closed: pd.DataFrame) -> None:
        """Attach an ATR-based stop to any of our positions missing one."""
        positions = mt5_client.open_positions(
            self.cfg.symbol, self.cfg.execution.magic_number
        )
        unprotected = [p for p in positions if not p.sl or p.sl <= 0]
        if not unprotected:
            return
        atr = float(_atr(closed, self.cfg.risk.atr_length).iloc[-1])
        close = float(closed["close"].iloc[-1])
        if not (atr > 0):  # also False for NaN
            self.log.warning(
                f"{len(unprotected)} position(s) without SL but ATR unavailable; retrying next poll"
            )
            return
        for p in unprotected:
            side = "buy" if p.type == 0 else "sell"  # POSITION_TYPE_BUY = 0
            stop = (
                close - self.cfg.risk.atr_stop_mult * atr
                if side == "buy"
                else close + self.cfg.risk.atr_stop_mult * atr
            )
            self.log.warning(
                f"position {p.ticket} ({side}) has NO stop-loss; attaching {stop:.5f}"
            )
            try:
                mt5_client.modify_position_sl(p, stop)
            except Exception as exc:  # noqa: BLE001
                self.log.error(f"failed to attach SL to ticket {p.ticket}: {exc}")

    def step(self) -> None:
        now = datetime.now(timezone.utc)
        if not self._in_session(now):
            return

        df = self._bars()
        if len(df) < 2:
            return
        # last row is the still-forming bar; evaluate the one before it
        closed = df.iloc[:-1]

        # Stop-loss safety sweep: runs EVERY poll (not just on new bars) so a
        # position that somehow lost its SL - manual edit, manual order on our
        # magic, partial broker glitch - is re-protected within poll_seconds.
        self._ensure_stop_losses(closed)

        bar_time = closed.index[-1]
        if self._last_bar_time == bar_time:
            return
        self._last_bar_time = bar_time

        data = add_indicators(closed, self.cfg)

        # MTF: fetch H4 (cached), drop the still-forming bar, attach indicators.
        h4_raw = self._bars_h4()
        data_h4 = None
        if h4_raw is not None and len(h4_raw) >= 2:
            data_h4 = add_indicators(h4_raw.iloc[:-1], self.cfg)

        if self.cfg.strategy == "fibonacci":
            signal = evaluate_fib_entry(data, data_h4, self.cfg)
        elif self.cfg.strategy == "macd":
            signal = evaluate_macd_entry(data, data_h4, self.cfg)
        else:
            signal = evaluate_last_bar(data, self.cfg, data_h4)
        positions = mt5_client.open_positions(
            self.cfg.symbol, self.cfg.execution.magic_number
        )

        # exits first — macd uses the opposite-cross exit; every other strategy
        # uses the Donchian reverse-channel exit.
        exit_fn = should_exit_macd if self.cfg.strategy == "macd" else should_exit
        for p in positions:
            side = "buy" if p.type == 0 else "sell"  # POSITION_TYPE_BUY = 0
            if exit_fn(side, data.iloc[-1]):
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
            f"entry strategy={self.cfg.strategy} side={signal.side} vol={volume} "
            f"ref={signal.entry_ref} stop={signal.stop} tp={signal.tp} "
            f"atr={signal.atr:.3f} h4_trend={signal.h4_trend_dir} "
            f"fib_level={signal.fib_level:.3f}"
        )
        order_result = mt5_client.market_order(
            symbol=self.cfg.symbol,
            side=signal.side,
            volume=volume,
            sl=signal.stop,
            tp=signal.tp,
            magic=self.cfg.execution.magic_number,
            deviation=self.cfg.execution.deviation_points,
            comment=self.cfg.execution.comment,
        )
        # Best-effort email notification; never raises.
        notify.send_signal_mail(
            symbol=self.cfg.symbol,
            side=signal.side,
            signal=signal,
            order_result=order_result,
            cfg=self.cfg,
            account=self.account,
            log=self.log,
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
