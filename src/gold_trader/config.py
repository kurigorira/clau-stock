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


@dataclass
class BreakoutConfig:
    donchian_length: int = 20
    exit_donchian_length: int = 10


@dataclass
class RiskConfig:
    per_trade_pct: float = 0.5
    atr_length: int = 14
    atr_stop_mult: float = 2.0
    max_positions: int = 1


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
class Config:
    symbol: str = "BTCUSD"
    timeframe: str = "H1"
    trend: TrendConfig = field(default_factory=TrendConfig)
    breakout: BreakoutConfig = field(default_factory=BreakoutConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)

    def __post_init__(self) -> None:
        if self.timeframe not in _TIMEFRAME_NAMES:
            raise ValueError(
                f"timeframe must be one of {_TIMEFRAME_NAMES}, got {self.timeframe}"
            )

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        raw = yaml.safe_load(Path(path).read_text())
        return cls(
            symbol=raw.get("symbol", "BTCUSD"),
            timeframe=raw.get("timeframe", "H1"),
            trend=TrendConfig(**(raw.get("trend") or {})),
            breakout=BreakoutConfig(**(raw.get("breakout") or {})),
            risk=RiskConfig(**(raw.get("risk") or {})),
            session=_parse_session(raw.get("session") or {}),
            execution=ExecutionConfig(**(raw.get("execution") or {})),
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
