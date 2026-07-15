import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader import report  # noqa: E402
from gold_trader.config import Config  # noqa: E402


@dataclass
class FakeDeal:
    symbol: str
    magic: int
    profit: float
    commission: float
    swap: float
    time: int


@dataclass
class FakePosition:
    symbol: str
    type: int  # 0 buy, 1 sell
    volume: float
    price_open: float
    profit: float
    sl: float
    tp: float
    magic: int
    ticket: int


def _cfg(magic: int, strategy: str = "fibonacci", max_loss_pct: float = 2.0,
         max_consecutive_losses: int = 2) -> Config:
    cfg = Config()
    cfg.strategy = strategy
    cfg.execution.magic_number = magic
    cfg.daily_guard.max_loss_pct = max_loss_pct
    cfg.daily_guard.max_consecutive_losses = max_consecutive_losses
    return cfg


# ---------------------------------------------------------------------------
# load_magic_index
# ---------------------------------------------------------------------------


def test_load_magic_index_indexes_real_presets(tmp_path):
    (tmp_path / "fib_xauusd.yaml").write_text(
        "symbol: XAUUSD\ntimeframe: H1\nexecution:\n  magic_number: 111\n",
        encoding="utf-8",
    )
    idx = report.load_magic_index(tmp_path)
    assert 111 in idx
    assert idx[111].symbol == "XAUUSD"


def test_load_magic_index_skips_non_preset_yaml(tmp_path):
    # watchlist.yaml has no `symbol:` key - must not appear under any magic,
    # and must not collide with a real preset's default magic_number
    (tmp_path / "watchlist.yaml").write_text(
        "threshold_pct: 2.0\nextra_symbols: []\n", encoding="utf-8"
    )
    (tmp_path / "fib_btcusd.yaml").write_text(
        "symbol: BTCUSD\ntimeframe: H1\nexecution:\n  magic_number: 20260509\n",
        encoding="utf-8",
    )
    idx = report.load_magic_index(tmp_path)
    assert idx[20260509].symbol == "BTCUSD"
    assert len(idx) == 1


def test_load_magic_index_covers_real_config_dir():
    config_dir = Path(__file__).resolve().parents[1] / "config"
    idx = report.load_magic_index(config_dir)
    assert len(idx) >= 80
    assert all(isinstance(cfg, Config) for cfg in idx.values())


# ---------------------------------------------------------------------------
# strategy_of
# ---------------------------------------------------------------------------


def test_strategy_of_known_magic():
    idx = {111: _cfg(111, strategy="donchian")}
    assert report.strategy_of(111, idx) == "donchian"


def test_strategy_of_zero_magic_is_manual():
    assert report.strategy_of(0, {}) == "manual"


def test_strategy_of_unknown_nonzero_magic():
    assert report.strategy_of(99999, {}) == "unknown"


# ---------------------------------------------------------------------------
# group_closed_deals
# ---------------------------------------------------------------------------


def test_group_closed_deals_sums_pnl_and_counts():
    deals = [
        FakeDeal("XAUUSD", 111, profit=10.0, commission=-1.0, swap=0.0, time=100),
        FakeDeal("XAUUSD", 111, profit=-5.0, commission=-1.0, swap=0.0, time=200),
    ]
    idx = {111: _cfg(111)}
    groups = report.group_closed_deals(deals, idx, equity=100000.0)
    assert len(groups) == 1
    g = groups[0]
    assert g.symbol == "XAUUSD"
    assert g.trades == 2
    assert abs(g.pnl - (10.0 - 1.0 - 5.0 - 1.0)) < 1e-9
    assert g.strategy == "fibonacci"


def test_group_closed_deals_loss_streak_counts_from_most_recent():
    deals = [
        FakeDeal("EURUSD", 5, profit=10.0, commission=0, swap=0, time=100),  # win (oldest)
        FakeDeal("EURUSD", 5, profit=-1.0, commission=0, swap=0, time=200),  # loss
        FakeDeal("EURUSD", 5, profit=-1.0, commission=0, swap=0, time=300),  # loss (most recent)
    ]
    idx = {5: _cfg(5)}
    groups = report.group_closed_deals(deals, idx, equity=100000.0)
    assert groups[0].loss_streak == 2


def test_group_closed_deals_streak_resets_on_win():
    deals = [
        FakeDeal("EURUSD", 5, profit=-1.0, commission=0, swap=0, time=100),
        FakeDeal("EURUSD", 5, profit=10.0, commission=0, swap=0, time=200),  # most recent: win
    ]
    idx = {5: _cfg(5)}
    groups = report.group_closed_deals(deals, idx, equity=100000.0)
    assert groups[0].loss_streak == 0


def test_group_closed_deals_flags_guard_tripped_by_loss_pct():
    deals = [FakeDeal("XAUUSD", 111, profit=-3000.0, commission=0, swap=0, time=100)]
    idx = {111: _cfg(111, max_loss_pct=2.0)}  # 2% of 100000 = 2000 cap
    groups = report.group_closed_deals(deals, idx, equity=100000.0)
    assert groups[0].guard_tripped is True


def test_group_closed_deals_flags_guard_tripped_by_streak():
    deals = [
        FakeDeal("XAUUSD", 111, profit=-1.0, commission=0, swap=0, time=100),
        FakeDeal("XAUUSD", 111, profit=-1.0, commission=0, swap=0, time=200),
    ]
    idx = {111: _cfg(111, max_consecutive_losses=2, max_loss_pct=99.0)}
    groups = report.group_closed_deals(deals, idx, equity=100000.0)
    assert groups[0].guard_tripped is True


def test_group_closed_deals_not_tripped_when_within_limits():
    deals = [FakeDeal("XAUUSD", 111, profit=-10.0, commission=0, swap=0, time=100)]
    idx = {111: _cfg(111, max_loss_pct=2.0)}
    groups = report.group_closed_deals(deals, idx, equity=100000.0)
    assert groups[0].guard_tripped is False


def test_group_closed_deals_unknown_magic_never_trips_guard():
    deals = [FakeDeal("MRVL", 0, profit=-500000.0, commission=0, swap=0, time=100)]
    groups = report.group_closed_deals(deals, {}, equity=20000.0)
    assert groups[0].guard_tripped is False  # no config to check thresholds against
    assert groups[0].strategy == "manual"


def test_group_closed_deals_separates_by_symbol_and_magic():
    deals = [
        FakeDeal("XAUUSD", 111, profit=10.0, commission=0, swap=0, time=100),
        FakeDeal("EURUSD", 222, profit=-5.0, commission=0, swap=0, time=100),
    ]
    groups = report.group_closed_deals(deals, {}, equity=100000.0)
    assert len(groups) == 2
    assert {g.symbol for g in groups} == {"XAUUSD", "EURUSD"}


# ---------------------------------------------------------------------------
# to_position_snapshot
# ---------------------------------------------------------------------------


def test_to_position_snapshot_buy():
    pos = FakePosition("XAUUSD", 0, 0.02, 2400.0, 12.5, 2380.0, 2450.0, 111, 999)
    snap = report.to_position_snapshot(pos, {111: _cfg(111, strategy="donchian")})
    assert snap.side == "buy"
    assert snap.strategy == "donchian"
    assert snap.ticket == 999


def test_to_position_snapshot_sell():
    pos = FakePosition("EURUSD", 1, 0.01, 1.16, -2.0, 1.17, 0.0, 5, 1)
    snap = report.to_position_snapshot(pos, {})
    assert snap.side == "sell"
    assert snap.strategy == "unknown"


# ---------------------------------------------------------------------------
# format_report_email
# ---------------------------------------------------------------------------


def _sample_report(account="1") -> report.AccountReport:
    pos = report.PositionSnapshot(
        symbol="XAUUSD", side="buy", volume=0.02, price_open=2400.0,
        profit=1200.0, sl=2380.0, tp=2450.0, magic=111, strategy="donchian", ticket=1,
    )
    group = report.ClosedGroup(
        symbol="XAUUSD", magic=111, strategy="donchian", pnl=3100.0,
        trades=2, loss_streak=0, guard_tripped=False,
    )
    return report.AccountReport(
        account=account, equity=962000.0, balance=960000.0,
        realized_pnl_today=3100.0, trades_today=2,
        closed_groups=[group], open_positions=[pos], unprotected_positions=[],
    )


def test_format_report_email_includes_key_figures():
    subject, body = report.format_report_email([_sample_report()], "2026-07-16 06:00")
    assert "2026-07-16 06:00" in subject
    assert "1/1 accounts OK" in subject
    assert "XAUUSD" in body
    assert "donchian" in body
    assert "962,000" in body
    assert "UNPROTECTED" not in subject


def test_format_report_email_flags_unprotected_in_subject_and_body():
    r = _sample_report()
    bad_pos = report.PositionSnapshot(
        symbol="MRVL", side="buy", volume=0.1, price_open=260.4,
        profit=-50.0, sl=0.0, tp=0.0, magic=0, strategy="manual", ticket=42,
    )
    r.unprotected_positions = [bad_pos]
    subject, body = report.format_report_email([r], "2026-07-16 06:00")
    assert "UNPROTECTED" in subject
    assert "ticket=42" in body
    assert "MRVL" in body


def test_format_report_email_shows_account_error():
    err = report.AccountReport(account="3", error="authorization failed")
    subject, body = report.format_report_email([_sample_report(), err], "2026-07-16 06:00")
    assert "1/2 accounts OK" in subject
    assert "ERROR: authorization failed" in body


def test_format_report_email_strategy_totals_aggregate_across_accounts():
    r1 = _sample_report(account="1")
    r2 = _sample_report(account="2")
    r2.closed_groups = [
        report.ClosedGroup("EURUSD", 222, "fibonacci", 500.0, 1, 0, False)
    ]
    r2.realized_pnl_today = 500.0
    r2.trades_today = 1
    subject, body = report.format_report_email([r1, r2], "2026-07-16 06:00")
    assert "By strategy" in body
    assert "donchian" in body
    assert "fibonacci" in body


def test_format_report_email_no_open_positions_says_none():
    r = report.AccountReport(account="1", equity=100.0, balance=100.0)
    _, body = report.format_report_email([r], "2026-07-16 06:00")
    assert "open positions: none" in body
