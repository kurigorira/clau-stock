import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.monthly import (  # noqa: E402
    JST,
    AccountMonthly,
    build_trades,
    format_monthly_markdown,
    format_monthly_report,
    mask_login,
    monthly_csv_rows,
    monthly_stats,
)

IN, OUT = 0, 1


def _deal(pos, symbol, entry, t, profit, commission=0.0, swap=0.0, magic=123):
    return SimpleNamespace(
        position_id=pos, symbol=symbol, entry=entry, time=int(t),
        profit=profit, commission=commission, swap=swap, magic=magic,
    )


def _unix(y, mo, d, h=12):
    return int(datetime(y, mo, d, h, tzinfo=JST).timestamp())


def _index():
    cfg = Config()
    cfg.strategy = "macd"
    return {123: cfg}


# --- build_trades -----------------------------------------------------------

def test_partial_close_is_one_trade_with_entry_costs():
    deals = [
        _deal(1, "AAPL", IN, _unix(2026, 8, 3), 0.0, commission=-2.0),
        _deal(1, "AAPL", OUT, _unix(2026, 8, 4), 50.0, commission=-1.0),
        _deal(1, "AAPL", OUT, _unix(2026, 8, 5), 30.0, commission=-1.0, swap=-3.0),
    ]
    trades, ops = build_trades(deals, _index())
    assert ops == []
    assert len(trades) == 1
    t = trades[0]
    assert t.net == 50 + 30 - 2 - 1 - 1 - 3
    assert t.close_time.day == 5  # dated by the LAST closing deal
    assert t.strategy == "macd"


def test_open_position_is_dropped_and_balance_ops_split_out():
    deals = [
        _deal(2, "MSFT", IN, _unix(2026, 8, 10), 0.0, commission=-2.0),  # still open
        SimpleNamespace(position_id=0, symbol="", entry=0, time=_unix(2026, 8, 1),
                        profit=100000.0, commission=0.0, swap=0.0, magic=0),
    ]
    trades, ops = build_trades(deals, _index())
    assert trades == []
    assert len(ops) == 1 and ops[0].profit == 100000.0


def test_close_time_uses_jst_month():
    # 2026-07-31 16:30 UTC = 2026-08-01 01:30 JST -> August
    t_unix = int(datetime(2026, 7, 31, 16, 30, tzinfo=timezone.utc).timestamp())
    deals = [
        _deal(3, "NVDA", IN, t_unix - 3600, 0.0),
        _deal(3, "NVDA", OUT, t_unix, 10.0),
    ]
    trades, _ = build_trades(deals, _index())
    months = monthly_stats(trades, [])
    assert [m.month for m in months] == ["2026-08"]


# --- monthly_stats ----------------------------------------------------------

def _two_month_trades():
    deals = [
        # June: one win, one loss
        _deal(1, "AAPL", IN, _unix(2026, 6, 2), 0.0),
        _deal(1, "AAPL", OUT, _unix(2026, 6, 3), 100.0),
        _deal(2, "MSFT", IN, _unix(2026, 6, 9), 0.0),
        _deal(2, "MSFT", OUT, _unix(2026, 6, 10), -40.0),
        # August: one win (July is silent)
        _deal(3, "NVDA", IN, _unix(2026, 8, 20), 0.0),
        _deal(3, "NVDA", OUT, _unix(2026, 8, 21), 60.0, magic=0),
    ]
    trades, _ = build_trades(deals, _index())
    return trades


def test_monthly_stats_metrics_and_gap_fill():
    ops = [SimpleNamespace(position_id=0, symbol="", entry=0,
                           time=_unix(2026, 6, 1), profit=100000.0,
                           commission=0.0, swap=0.0, magic=0)]
    months = monthly_stats(_two_month_trades(), ops, balance_now=100120.0)
    assert [m.month for m in months] == ["2026-06", "2026-07", "2026-08"]

    jun, jul, aug = months
    assert (jun.trades, jun.wins) == (2, 1)
    assert jun.win_rate == 50.0
    assert jun.gross_profit == 100.0 and jun.gross_loss == -40.0
    assert jun.net == 60.0
    assert jun.profit_factor == 100.0 / 40.0
    assert jun.balance_ops == 100000.0
    assert jun.by_strategy == {"macd": [60.0, 2]}

    assert jul.trades == 0 and jul.net == 0.0  # silent month still listed

    assert aug.by_strategy == {"manual": [60.0, 1]}  # magic 0 -> manual
    assert aug.profit_factor == float("inf")

    # end balances walk back from balance_now: aug 100120, jul 100060, jun 100060
    assert aug.end_balance == 100120.0
    assert jul.end_balance == 100060.0
    assert jun.end_balance == 100060.0


def test_monthly_stats_empty():
    assert monthly_stats([], []) == []


# --- formatting / csv -------------------------------------------------------

def test_format_and_csv_smoke():
    months = monthly_stats(_two_month_trades(), [], balance_now=1000.0)
    reports = [
        AccountMonthly(account="1", login=100001, balance=1000.0, months=months),
        AccountMonthly(account="9", error="missing env var 'MT5_LOGIN_9'"),
    ]
    body = format_monthly_report(reports, "2026-09-03 09:00 JST")
    assert "Account 1 (100001)" in body
    assert "TOTAL" in body and "by strategy:" in body
    assert "ERROR: missing env var" in body

    rows = monthly_csv_rows(reports)  # error account contributes no rows
    assert [r["month"] for r in rows] == ["2026-06", "2026-07", "2026-08"]
    assert rows[0]["account"] == "1" and rows[0]["trades"] == 2
    assert rows[2]["profit_factor"] == ""  # inf -> blank in csv


# --- markdown (published to the repo) ---------------------------------------

def test_mask_login_keeps_last_three_digits():
    assert mask_login(100001) == "***001"
    assert mask_login(12) == "***"


def _md_reports():
    months = monthly_stats(_two_month_trades(), [], balance_now=1000.0)
    return [
        AccountMonthly(account="1", login=100001, balance=1000.0, months=months),
        AccountMonthly(account="9", error="missing env var 'MT5_LOGIN_9'"),
    ]


def test_markdown_masks_logins_by_default():
    md = format_monthly_markdown(_md_reports(), "2026-09-04 21:00 JST")
    assert "***001" in md
    assert "100001" not in md  # the full account number never reaches the file
    assert "## Account 1 (***001)" in md
    assert "| 2026-06 | 2 | 50.0 |" in md
    assert "**total**" in md
    assert "Not reported: missing env var" in md
    assert "By strategy:" in md


def test_markdown_can_opt_into_full_logins():
    md = format_monthly_markdown(
        _md_reports(), "2026-09-04 21:00 JST", mask_logins=False
    )
    assert "## Account 1 (100001)" in md


def test_markdown_summary_totals_match_month_rows():
    md = format_monthly_markdown(_md_reports(), "x")
    # 3 trades total (2 in June, 0 in July, 1 in August), 2 of them winners
    summary = [ln for ln in md.splitlines() if ln.startswith("| 1 (***001) |")]
    assert len(summary) == 1
    cells = [c.strip() for c in summary[0].strip("|").split("|")]
    assert cells[1:4] == ["3", "3", "66.7"]  # months, trades, win%
    assert cells[5] == "+120"                # net = 100 - 40 + 60


# --- live exit reasons ------------------------------------------------------

def _deal_r(pos, entry, t, profit, reason=None, magic=123):
    ns = SimpleNamespace(position_id=pos, symbol="AAPL", entry=entry, time=int(t),
                         profit=profit, commission=0.0, swap=0.0, magic=magic)
    if reason is not None:
        ns.reason = reason
    return ns


def test_exit_reason_and_hold_from_closing_deal():
    t0 = _unix(2026, 9, 1)
    deals = [
        _deal_r(1, IN, t0, 0.0, 3), _deal_r(1, OUT, t0 + 3600 * 6, -100.0, 4),
        _deal_r(2, IN, t0, 0.0, 3), _deal_r(2, OUT, t0 + 3600 * 40, 250.0, 3),
        _deal_r(3, IN, t0, 0.0, 3), _deal_r(3, OUT, t0 + 3600 * 2, -30.0, 0),
        _deal_r(4, IN, t0, 0.0), _deal_r(4, OUT, t0 + 3600 * 5, 10.0),
    ]
    trades, _ = build_trades(deals, _index())
    by_id = {t.position_id: t for t in trades}
    assert by_id[1].exit_reason == "sl" and by_id[1].hours_held == 6.0
    assert by_id[2].exit_reason == "expert" and by_id[2].hours_held == 40.0
    assert by_id[3].exit_reason == "manual"
    # a terminal build without a reason field must not guess
    assert by_id[4].exit_reason == "unknown"


def test_hours_held_is_none_without_an_opening_deal():
    # the entry deal fell outside the queried window
    deals = [_deal_r(9, OUT, _unix(2026, 9, 2), 5.0, 3)]
    trades, _ = build_trades(deals, _index())
    assert trades[0].hours_held is None
    assert trades[0].exit_reason == "expert"
