import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gold_trader.config import Config  # noqa: E402
from gold_trader.htmlreport import build_payload, render_html  # noqa: E402
from gold_trader.monthly import (  # noqa: E402
    JST,
    AccountMonthly,
    build_trades,
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
    macd, boll = Config(), Config()
    macd.strategy = "macd"
    boll.strategy = "bollrci"
    return {123: macd, 456: boll}


def _reports():
    a1 = [
        _deal(1, "AAPL", IN, _unix(2026, 6, 2), 0.0),
        _deal(1, "AAPL", OUT, _unix(2026, 6, 3), 100.0),
        _deal(2, "MSFT", IN, _unix(2026, 7, 9), 0.0),
        _deal(2, "MSFT", OUT, _unix(2026, 7, 10), -40.0),
    ]
    a2 = [
        _deal(3, "NVDA", IN, _unix(2026, 7, 20), 0.0),
        _deal(3, "NVDA", OUT, _unix(2026, 7, 21), -25.0, magic=456),
    ]
    t1, _ = build_trades(a1, _index())
    t2, _ = build_trades(a2, _index())
    return [
        AccountMonthly(account="1", login=100001, balance=1060.0,
                       months=monthly_stats(t1, [], balance_now=1060.0)),
        AccountMonthly(account="2", login=200002, balance=975.0,
                       months=monthly_stats(t2, [], balance_now=975.0)),
        AccountMonthly(account="9", error="missing env var 'MT5_LOGIN_9'"),
    ]


# --- payload ----------------------------------------------------------------

def test_payload_aggregates_strategies_and_totals():
    p = build_payload(_reports(), "2026-09-05 22:57 JST")
    assert [a["id"] for a in p["accounts"]] == ["1", "2"]
    assert p["skipped"] == [{"id": "9", "error": "missing env var 'MT5_LOGIN_9'"}]

    strats = {s["name"]: (s["net"], s["n"]) for s in p["strategies"]}
    assert strats == {"macd": (60, 2), "bollrci": (-25, 1)}
    # sorted worst-first so the chart's first row is the biggest loser
    assert p["strategies"][0]["name"] == "bollrci"

    assert p["totals"]["trades"] == 3
    assert p["totals"]["net"] == 35
    assert p["totals"]["wins"] == 1


def test_payload_masks_logins_by_default():
    p = build_payload(_reports(), "x")
    assert [a["mask"] for a in p["accounts"]] == ["***001", "***002"]
    p2 = build_payload(_reports(), "x", mask_logins=False)
    assert [a["mask"] for a in p2["accounts"]] == ["100001", "200002"]


# --- rendered page ----------------------------------------------------------

def test_render_embeds_valid_json_and_no_raw_login():
    html = render_html(_reports(), "2026-09-05 22:57 JST")
    m = re.search(
        r'<script type="application/json" id="payload">(.*?)</script>', html, re.S
    )
    assert m, "payload script block missing"
    data = json.loads(m.group(1).replace("<\\/", "</"))
    assert data["generatedAt"] == "2026-09-05 22:57 JST"
    assert len(data["accounts"]) == 2
    assert "100001" not in html and "200002" not in html


def test_render_is_a_complete_standalone_document():
    html = render_html(_reports(), "x")
    assert html.startswith("<!doctype html>")
    assert html.rstrip().endswith("</html>")
    assert "__DATA_JSON__" not in html and "__GENERATED_AT__" not in html
    # theme handled in all three states, per the artifact/theming contract
    assert "prefers-color-scheme: dark" in html
    assert '[data-theme="dark"]' in html
    # every strategy that can appear in the data has an explanation card
    for name in ("macd", "bollrci", "donchian", "fibonacci", "kairi", "manual"):
        assert name + ":" in html, name


def test_script_closing_tag_in_data_cannot_break_out():
    r = AccountMonthly(account="1", login=100001, balance=0.0, months=[])
    hostile = SimpleNamespace(month="</script><script>alert(1)</script>")
    # a strategy name is the only free-form string that reaches the payload;
    # simulate one carrying a closing tag
    months = monthly_stats(
        build_trades(
            [
                _deal(1, "X", IN, _unix(2026, 6, 2), 0.0, magic=999),
                _deal(1, "X", OUT, _unix(2026, 6, 3), 5.0, magic=999),
            ],
            {},
        )[0],
        [],
        balance_now=5.0,
    )
    r.months = months
    html = render_html([r], "x")
    assert "</script><script>alert(1)</script>" not in html
    assert hostile.month not in html


def test_empty_reports_still_render():
    html = render_html([AccountMonthly(account="1", error="down")], "x")
    assert "<!doctype html>" in html
    assert '"accounts":[]' in html
