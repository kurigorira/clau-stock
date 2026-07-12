import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402


def test_default_strategy_is_donchian():
    assert Config().strategy == "donchian"


def test_invalid_strategy_rejected():
    with pytest.raises(ValueError, match="strategy"):
        Config(strategy="martingale")


def test_fibonacci_requires_higher_timeframe():
    cfg = Config()
    with pytest.raises(ValueError, match="higher_timeframe"):
        Config(strategy="fibonacci", trend=type(cfg.trend)(higher_timeframe=""))


def test_invalid_retrace_zone_rejected():
    cfg = Config()
    fib = type(cfg.fibonacci)(retrace_min=0.8, retrace_max=0.5)
    with pytest.raises(ValueError, match="retrace"):
        Config(fibonacci=fib)


def test_invalid_extension_rejected():
    cfg = Config()
    fib = type(cfg.fibonacci)(extension_tp=0.9)
    with pytest.raises(ValueError, match="extension_tp"):
        Config(fibonacci=fib)


def test_from_yaml_parses_fibonacci_section(tmp_path):
    yaml_path = tmp_path / "fib.yaml"
    yaml_path.write_text(
        """
symbol: XAUUSD
timeframe: H1
strategy: fibonacci
fibonacci:
  swing_lookback: 30
  retrace_min: 0.5
  retrace_max: 0.786
  extension_tp: 1.272
  vol_mult: 0
  use_macd: false
execution:
  magic_number: 99999999
""",
        encoding="utf-8",
    )
    cfg = Config.from_yaml(yaml_path)
    assert cfg.strategy == "fibonacci"
    assert cfg.fibonacci.swing_lookback == 30
    assert cfg.fibonacci.retrace_min == 0.5
    assert cfg.fibonacci.extension_tp == 1.272
    assert cfg.fibonacci.vol_mult == 0
    assert cfg.fibonacci.use_macd is False
    assert cfg.execution.magic_number == 99999999


def test_all_fib_presets_parse_and_have_unique_magics():
    # fib_*.yaml files are the fleet presets; after the backtest-driven
    # re-assignment some of them run strategy: donchian (the file name is
    # historical). All must parse and every magic_number must be unique.
    config_dir = Path(__file__).resolve().parents[1] / "config"
    presets = sorted(config_dir.glob("fib_*.yaml"))
    assert len(presets) == 71  # 50 rollout + eurusd_small + 20 non-tech stocks
    magics: dict[int, str] = {}
    for p in presets:
        cfg = Config.from_yaml(p)
        assert cfg.strategy in ("donchian", "fibonacci"), p.name
        m = cfg.execution.magic_number
        assert m not in magics, f"{p.name} reuses magic {m} of {magics.get(m)}"
        magics[m] = p.name


def test_backtest_winners_run_donchian():
    config_dir = Path(__file__).resolve().parents[1] / "config"
    donchian_winners = [
        "fib_xauusd.yaml", "fib_xagusd.yaml", "fib_jpn225ft.yaml",
        "fib_nzdusd.yaml", "fib_usdcad.yaml", "fib_amd.yaml",
        "fib_msft.yaml", "fib_nflx.yaml", "fib_nvidia.yaml", "fib_meta.yaml",
        "fib_cvx.yaml", "fib_bac.yaml", "fib_unh.yaml", "fib_exxon.yaml",
    ]
    for name in donchian_winners:
        assert Config.from_yaml(config_dir / name).strategy == "donchian", name
