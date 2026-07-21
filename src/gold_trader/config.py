from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import List

import yaml


_TIMEFRAME_NAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1")


@dataclass
class TrendConfig:
    ema_length: int = 200
    ema_slope_lookback: int = 3
    # H4 trend filter: only take H1 breakouts that agree with the H4 trend
    # direction (EMA-slope + ADX on H4). Set to "" to disable the filter.
    higher_timeframe: str = "H4"


@dataclass
class BreakoutConfig:
    donchian_length: int = 20
    exit_donchian_length: int = 10
    atr_buffer_mult: float = 0.1


@dataclass
class RiskConfig:
    per_trade_pct: float = 3.0
    atr_length: int = 14
    atr_stop_mult: float = 2.0
    max_positions: int = 1


@dataclass
class FilterConfig:
    adx_length: int = 14
    adx_min: float = 20.0
    atr_pct_min: float = 0.003
    atr_pct_max: float = 0.10


@dataclass
class DailyGuardConfig:
    max_consecutive_losses: int = 2
    max_loss_pct: float = 3.0


@dataclass
class SessionConfig:
    start_utc: time = time(0, 0)
    end_utc: time = time(23, 59)
    trade_days: List[str] = field(
        default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    )


@dataclass
class ExecutionConfig:
    magic_number: int = 20260509
    deviation_points: int = 20
    poll_seconds: int = 30
    comment: str = "btc_breakout"


@dataclass
class FibonacciConfig:
    """Parameters for strategy: "fibonacci" (retrace entry + extension TP).

    The H4 swing is the high/low of the last `swing_lookback` closed H4 bars.
    A long fires when H1 pulls back into the retrace_min..retrace_max zone of
    that swing, closes higher `bounce_bars` times in a row, prints above-average
    volume, and the MACD histogram is turning back up — all while the H4 trend
    filter (EMA slope + ADX, shared with the donchian strategy) points up.
    """
    swing_lookback: int = 20
    retrace_min: float = 0.382
    retrace_max: float = 0.786
    extension_tp: float = 1.618
    bounce_bars: int = 2
    vol_mult: float = 1.2          # 0 disables the volume filter
    vol_sma_length: int = 20
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    use_macd: bool = True
    stop_atr_buffer: float = 0.2   # SL sits this many ATRs beyond the swing


@dataclass
class MacdConfig:
    """Parameters for strategy: "macd" (MACD/signal cross entries).

    Entry on the histogram crossing zero (= MACD line crossing the signal
    line): long when it flips from <=0 to >0, short on the reverse. Exit on
    the opposite cross, with an ATR stop (risk.atr_stop_mult) as a safety
    net. use_h4_filter=true additionally requires the H4 trend to agree.
    """
    fast: int = 12
    slow: int = 26
    signal: int = 9
    use_h4_filter: bool = True   # false = pure MACD, no trend gate


_STRATEGY_NAMES = ("donchian", "fibonacci", "macd")


@dataclass
class NotifyConfig:
    # When enabled, signal entries trigger an email via Gmail SMTP. SMTP
    # credentials come from env vars (GMAIL_USER, GMAIL_APP_PASSWORD,
    # NOTIFY_TO); if any are missing the notifier silently no-ops so the
    # bot still trades.
    enabled: bool = True
    # dry_run is reserved for a future "notify-only" mode that skips
    # mt5.order_send entirely; the executor does not consult it yet.
    dry_run: bool = False
    throttle_sec: int = 60


@dataclass
class Config:
    symbol: str = "BTCUSD"
    timeframe: str = "H1"
    strategy: str = "donchian"
    trend: TrendConfig = field(default_factory=TrendConfig)
    breakout: BreakoutConfig = field(default_factory=BreakoutConfig)
    fibonacci: FibonacciConfig = field(default_factory=FibonacciConfig)
    macd: MacdConfig = field(default_factory=MacdConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    daily_guard: DailyGuardConfig = field(default_factory=DailyGuardConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)

    def __post_init__(self) -> None:
        if self.timeframe not in _TIMEFRAME_NAMES:
            raise ValueError(
                f"timeframe must be one of {_TIMEFRAME_NAMES}, got {self.timeframe}"
            )
        if self.strategy not in _STRATEGY_NAMES:
            raise ValueError(
                f"strategy must be one of {_STRATEGY_NAMES}, got {self.strategy}"
            )
        if self.trend.higher_timeframe and self.trend.higher_timeframe not in _TIMEFRAME_NAMES:
            raise ValueError(
                f"trend.higher_timeframe must be one of {_TIMEFRAME_NAMES} or '' to disable,"
                f" got {self.trend.higher_timeframe}"
            )
        if self.strategy == "fibonacci" and not self.trend.higher_timeframe:
            raise ValueError(
                "strategy 'fibonacci' needs trend.higher_timeframe (the swing/trend timeframe)"
            )
        f = self.fibonacci
        if not (0.0 < f.retrace_min < f.retrace_max <= 1.0):
            raise ValueError(
                f"fibonacci retrace zone must satisfy 0 < min < max <= 1,"
                f" got [{f.retrace_min}, {f.retrace_max}]"
            )
        if f.extension_tp <= 1.0:
            raise ValueError(
                f"fibonacci.extension_tp must be > 1.0, got {f.extension_tp}"
            )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        # explicit utf-8 so Japanese-locale Windows (cp932 default) reads it
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(
            symbol=raw.get("symbol", "BTCUSD"),
            timeframe=raw.get("timeframe", "H1"),
            strategy=raw.get("strategy", "donchian"),
            trend=TrendConfig(**(raw.get("trend") or {})),
            breakout=BreakoutConfig(**(raw.get("breakout") or {})),
            fibonacci=FibonacciConfig(**(raw.get("fibonacci") or {})),
            macd=MacdConfig(**(raw.get("macd") or {})),
            risk=RiskConfig(**(raw.get("risk") or {})),
            filters=FilterConfig(**(raw.get("filters") or {})),
            daily_guard=DailyGuardConfig(**(raw.get("daily_guard") or {})),
            session=_parse_session(raw.get("session") or {}),
            execution=ExecutionConfig(**(raw.get("execution") or {})),
            notify=NotifyConfig(**(raw.get("notify") or {})),
        )


def _parse_session(raw: dict) -> SessionConfig:
    def _t(s: str) -> time:
        h, m = s.split(":")
        return time(int(h), int(m))

    return SessionConfig(
        start_utc=_t(raw.get("start_utc", "00:00")),
        end_utc=_t(raw.get("end_utc", "23:59")),
        trade_days=raw.get(
            "trade_days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        ),
    )
