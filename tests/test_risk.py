import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.risk import position_volume  # noqa: E402


_BASE = dict(
    equity=10_000.0,
    stop_distance_price=10.0,
    tick_value=1.0,
    tick_size=0.01,
    volume_min=0.01,
    volume_max=100.0,
    volume_step=0.01,
)


def test_volume_scales_with_risk_pct():
    v_low = position_volume(risk_pct=0.5, **_BASE)
    v_high = position_volume(risk_pct=1.0, **_BASE)
    assert v_high > v_low
    # 1% of 10k = 100; cost per 1 lot = (10/0.01)*1 = 1000 -> 0.10 lot
    assert abs(v_high - 0.10) < 1e-9


def test_returns_zero_when_below_min():
    args = {**_BASE, "equity": 100.0, "stop_distance_price": 50.0, "volume_min": 0.10}
    assert position_volume(risk_pct=0.5, **args) == 0.0


def test_zero_stop_yields_zero():
    args = {**_BASE, "stop_distance_price": 0.0}
    assert position_volume(risk_pct=0.5, **args) == 0.0


def test_volume_capped_by_max():
    args = {**_BASE, "equity": 10_000_000.0, "volume_max": 5.0}
    assert position_volume(risk_pct=1.0, **args) == 5.0
