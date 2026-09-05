"""Standalone HTML rendering of the monthly report (for GitHub Pages).

scripts/monthly_report.py --html writes the page produced here. It is a
single self-contained file: the figures are embedded as JSON and drawn by a
small inline script, so the published page needs no build step and no
network access beyond a webfont.

Everything the page states is DERIVED from the embedded figures - the
headline, the per-strategy totals, the account roles, and the automatic
checks. Nothing is hand-written commentary, because this file is
regenerated every month and stale prose would outlive the numbers it
described.
"""
from __future__ import annotations

import json
from typing import Any

from .monthly import AccountMonthly, mask_login

__all__ = ["render_html", "build_payload"]


def _account_payload(r: AccountMonthly, mask_logins: bool) -> dict[str, Any]:
    months = [
        {
            "m": m.month,
            "n": m.trades,
            "wins": m.wins,
            "win": round(m.win_rate, 1),
            "pf": ("inf" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"),
            "gp": round(m.gross_profit),
            "gl": round(m.gross_loss),
            "net": round(m.net),
            "ops": round(m.balance_ops),
            "bal": (None if m.end_balance is None else round(m.end_balance)),
        }
        for m in r.months
    ]
    by_strategy = [
        [m.month, strat, round(pnl), n]
        for m in r.months
        for strat, (pnl, n) in sorted(m.by_strategy.items())
    ]
    trades = sum(m.trades for m in r.months)
    wins = sum(m.wins for m in r.months)

    label = ""
    if r.login:
        label = mask_login(r.login) if mask_logins else str(r.login)

    return {
        "id": r.account,
        "mask": label,
        "balance": round(r.balance),
        "net": round(sum(m.net for m in r.months)),
        "trades": trades,
        "wins": wins,
        "win": round(100.0 * wins / trades, 1) if trades else 0.0,
        "months": months,
        "byStrategy": by_strategy,
        "error": r.error,
    }


def build_payload(
    reports: list[AccountMonthly], generated_at: str, *, mask_logins: bool = True
) -> dict[str, Any]:
    """The JSON the page draws itself from."""
    accounts = [
        _account_payload(r, mask_logins) for r in reports if r.error is None and r.months
    ]
    skipped = [
        {"id": r.account, "error": r.error} for r in reports if r.error is not None
    ]

    totals: dict[str, list] = {}
    for a in accounts:
        for _month, strat, net, n in a["byStrategy"]:
            row = totals.setdefault(strat, [0, 0])
            row[0] += net
            row[1] += n
    strategies = [
        {"name": k, "net": v[0], "n": v[1]}
        for k, v in sorted(totals.items(), key=lambda kv: kv[1][0])
    ]

    trades = sum(a["trades"] for a in accounts)
    wins = sum(a["wins"] for a in accounts)
    return {
        "generatedAt": generated_at,
        "accounts": accounts,
        "skipped": skipped,
        "strategies": strategies,
        "totals": {
            "net": sum(a["net"] for a in accounts),
            "trades": trades,
            "wins": wins,
            "win": round(100.0 * wins / trades, 1) if trades else 0.0,
        },
    }


def render_html(
    reports: list[AccountMonthly], generated_at: str, *, mask_logins: bool = True
) -> str:
    payload = build_payload(reports, generated_at, mask_logins=mask_logins)
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    # </script> inside the JSON would end the tag early; escape the only
    # sequence that can do that.
    blob = blob.replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA_JSON__", blob).replace(
        "__GENERATED_AT__", generated_at
    )


_TEMPLATE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>clau-stock 運用統計</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Shippori+Mincho:wght@600;700&family=IBM+Plex+Sans+JP:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
  :root {
    color-scheme: light;
    --ground:      #F2F5F3;
    --surface:     #FFFFFF;
    --surface-sub: #E9EEEB;
    --ink:         #131817;
    --ink-2:       #4A5754;
    --ink-3:       #7B8783;
    --rule:        #DCE3E0;
    --rule-strong: #C3CDC9;
    --profit:      #1B9E77;
    --loss:        #C0392E;
    --profit-soft: #E4F2ED;
    --loss-soft:   #F8E6E3;
    --on-mark:     #FFFFFF;
    --f-display: "Shippori Mincho", "Hiragino Mincho ProN", "Yu Mincho", serif;
    --f-body: "IBM Plex Sans JP", "Hiragino Kaku Gothic ProN", "Yu Gothic", Meiryo, sans-serif;
    --f-mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Consolas, monospace;
    --measure: 34rem;
    --page: 68rem;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --ground:      #0E1211;
      --surface:     #161B1A;
      --surface-sub: #1E2523;
      --ink:         #E7ECEA;
      --ink-2:       #A5AFAC;
      --ink-3:       #717C79;
      --rule:        #262E2C;
      --rule-strong: #38423F;
      --profit:      #35A98D;
      --loss:        #D9635B;
      --profit-soft: #14302A;
      --loss-soft:   #331D1B;
      --on-mark:     #0E1211;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --ground:#0E1211; --surface:#161B1A; --surface-sub:#1E2523;
    --ink:#E7ECEA; --ink-2:#A5AFAC; --ink-3:#717C79;
    --rule:#262E2C; --rule-strong:#38423F;
    --profit:#35A98D; --loss:#D9635B;
    --profit-soft:#14302A; --loss-soft:#331D1B; --on-mark:#0E1211;
  }
  * { box-sizing: border-box; }
  html { -webkit-text-size-adjust: 100%; }
  body {
    margin: 0; background: var(--ground); color: var(--ink);
    font-family: var(--f-body); font-size: 15px; line-height: 1.75;
    -webkit-font-smoothing: antialiased;
  }
  img { max-width: 100%; }
  .page {
    max-width: var(--page); margin: 0 auto;
    padding: clamp(1.5rem, 4vw, 3.5rem) clamp(1.1rem, 4vw, 2.5rem) 5rem;
    display: flex; flex-direction: column; gap: clamp(2.5rem, 5vw, 3.75rem);
  }
  .masthead { display: flex; flex-direction: column; gap: 1rem; }
  .eyebrow {
    font-family: var(--f-mono); font-size: 0.7rem; letter-spacing: 0.16em;
    text-transform: uppercase; color: var(--ink-3);
  }
  h1 {
    font-family: var(--f-display); font-weight: 700;
    font-size: clamp(2rem, 5vw, 3rem); line-height: 1.2;
    letter-spacing: 0.01em; margin: 0; text-wrap: balance;
  }
  .standfirst { margin: 0; max-width: var(--measure); color: var(--ink-2); }
  .meta-strip {
    display: flex; flex-wrap: wrap; gap: 0.5rem 1.75rem; padding-top: 1rem;
    border-top: 1px solid var(--rule); font-family: var(--f-mono);
    font-size: 0.78rem; color: var(--ink-3);
  }
  .meta-strip b { color: var(--ink-2); font-weight: 500; }
  section { display: flex; flex-direction: column; gap: 1.25rem; }
  h2 {
    font-family: var(--f-display); font-weight: 600; font-size: 1.4rem;
    margin: 0; letter-spacing: 0.01em;
  }
  .section-head { display: flex; flex-direction: column; gap: 0.35rem; }
  .section-note { margin: 0; max-width: var(--measure); font-size: 0.86rem; color: var(--ink-2); }
  .headline {
    background: var(--surface); border: 1px solid var(--rule);
    padding: 1.5rem 1.75rem; display: flex; flex-wrap: wrap;
    gap: 1.5rem 3rem; align-items: baseline;
  }
  .headline.is-loss { border-left: 3px solid var(--loss); }
  .headline.is-profit { border-left: 3px solid var(--profit); }
  .headline .figure {
    font-family: var(--f-mono); font-weight: 500;
    font-size: clamp(2rem, 6vw, 3rem); line-height: 1;
    font-variant-numeric: tabular-nums;
  }
  .headline .caption { font-size: 0.86rem; color: var(--ink-2); max-width: 26rem; }
  .tiles {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(15.5rem, 1fr));
    gap: 1px; background: var(--rule); border: 1px solid var(--rule);
  }
  .tile { background: var(--surface); padding: 1.25rem 1.35rem; display: flex; flex-direction: column; gap: 0.9rem; }
  .tile-id { display: flex; align-items: baseline; gap: 0.6rem; }
  .tile-id .no { font-family: var(--f-mono); font-size: 0.72rem; letter-spacing: 0.1em; color: var(--ink-3); }
  .tile-id .role {
    display: block; font-size: 0.9rem; font-weight: 600;
    line-height: 1.4; min-height: 2.8em;
  }
  .tile-net {
    font-family: var(--f-mono); font-weight: 500; font-size: 1.5rem;
    line-height: 1; font-variant-numeric: tabular-nums;
  }
  .tile-rows { display: flex; flex-direction: column; gap: 0.3rem; }
  .tile-row {
    display: flex; justify-content: space-between; gap: 1rem; font-size: 0.8rem;
    color: var(--ink-2); border-top: 1px solid var(--rule); padding-top: 0.3rem;
  }
  .tile-row span:last-child { font-family: var(--f-mono); font-variant-numeric: tabular-nums; color: var(--ink); }
  .pos { color: var(--profit); }
  .neg { color: var(--loss); }
  .findings { display: flex; flex-direction: column; gap: 1rem; }
  .finding {
    background: var(--surface); border: 1px solid var(--rule); padding: 1.25rem 1.4rem;
    display: grid; grid-template-columns: max-content 1fr; gap: 0.4rem 1rem; align-items: start;
  }
  .finding > .flag { grid-column: 1; grid-row: 1; }
  .finding > h3 { grid-column: 2; grid-row: 1; }
  .finding > .body, .finding > pre { grid-column: 2; }
  .finding .flag {
    font-family: var(--f-mono); font-size: 0.65rem; letter-spacing: 0.12em;
    text-transform: uppercase; padding: 0.2rem 0.5rem; border-radius: 2px; white-space: nowrap;
  }
  .flag--alert { background: var(--loss-soft); color: var(--loss); }
  .flag--check { background: var(--surface-sub); color: var(--ink-2); }
  .flag--ok { background: var(--profit-soft); color: var(--profit); }
  .finding h3 { margin: 0; font-size: 1rem; font-weight: 600; align-self: center; }
  .finding .body { margin: 0; font-size: 0.9rem; color: var(--ink-2); }
  .finding .body strong { color: var(--ink); font-weight: 600; }
  code {
    font-family: var(--f-mono); font-size: 0.82em; background: var(--surface-sub);
    padding: 0.12em 0.4em; border-radius: 2px; color: var(--ink);
  }
  pre {
    margin: 0.6rem 0 0; padding: 0.75rem 0.9rem; background: var(--surface-sub);
    border-radius: 3px; overflow-x: auto; font-family: var(--f-mono);
    font-size: 0.78rem; line-height: 1.6; color: var(--ink);
  }
  pre code { background: none; padding: 0; }
  .chart-frame {
    background: var(--surface); border: 1px solid var(--rule);
    padding: 1.4rem 1.5rem 1.1rem; overflow-x: auto;
  }
  .chart-frame svg { display: block; width: 100%; height: auto; min-width: 30rem; }
  .panel-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(22rem, 1fr));
    gap: 1px; background: var(--rule); border: 1px solid var(--rule);
  }
  .panel { background: var(--surface); padding: 1.15rem 1.3rem 1rem; }
  .panel header { display: flex; flex-direction: column; gap: 0.15rem; margin-bottom: 0.5rem; }
  .panel .p-title { font-size: 0.9rem; font-weight: 600; }
  .panel .p-scale { font-family: var(--f-mono); font-size: 0.68rem; color: var(--ink-3); }
  .panel svg { display: block; width: 100%; height: auto; }
  .legend { display: flex; gap: 1.25rem; flex-wrap: wrap; font-size: 0.78rem; color: var(--ink-2); align-items: center; }
  .swatch { display: inline-block; width: 0.7rem; height: 0.7rem; border-radius: 2px; margin-right: 0.4rem; vertical-align: -1px; }
  .table-wrap { overflow-x: auto; background: var(--surface); border: 1px solid var(--rule); }
  table { border-collapse: collapse; width: 100%; min-width: 42rem; font-size: 0.84rem; }
  caption { text-align: left; padding: 1.1rem 1.3rem 0.75rem; font-size: 0.95rem; font-weight: 600; }
  caption .sub {
    display: block; font-weight: 400; font-size: 0.8rem; color: var(--ink-3);
    font-family: var(--f-mono); margin-top: 0.2rem;
  }
  th, td { padding: 0.5rem 0.85rem; text-align: right; white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  .t-strat th:nth-child(2), .t-strat td:nth-child(2) { text-align: left; }
  thead th {
    font-size: 0.72rem; font-weight: 500; letter-spacing: 0.04em;
    color: var(--ink-3); border-bottom: 1px solid var(--rule-strong); background: var(--surface);
  }
  tbody td { font-family: var(--f-mono); font-variant-numeric: tabular-nums; border-bottom: 1px solid var(--rule); }
  tbody td:first-child { font-family: var(--f-body); }
  tbody tr:last-child td { border-bottom: none; }
  tr.total td { font-weight: 500; background: var(--surface-sub); border-bottom: none; }
  tr.quiet td { color: var(--ink-3); }
  .acct-block { display: flex; flex-direction: column; gap: 1px; }
  .strat-cards {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(21rem, 1fr));
    gap: 1px; background: var(--rule); border: 1px solid var(--rule);
  }
  .strat-card { background: var(--surface); padding: 1.25rem 1.4rem; display: flex; flex-direction: column; gap: 0.6rem; }
  .strat-card .sc-head { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap; }
  .strat-card .sc-name { font-family: var(--f-mono); font-size: 1rem; font-weight: 500; }
  .strat-card .sc-kind {
    font-size: 0.68rem; letter-spacing: 0.08em; padding: 0.15rem 0.45rem;
    border-radius: 2px; background: var(--surface-sub); color: var(--ink-2);
  }
  .strat-card .sc-pnl { margin-left: auto; font-family: var(--f-mono); font-size: 0.85rem; font-variant-numeric: tabular-nums; }
  .strat-card p { margin: 0; font-size: 0.86rem; color: var(--ink-2); }
  .strat-card dl { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 0.8rem; font-size: 0.8rem; }
  .strat-card dt { color: var(--ink-3); }
  .strat-card dd { margin: 0; color: var(--ink-2); }
  .notes {
    background: var(--surface); border: 1px solid var(--rule);
    padding: 1.4rem 1.6rem; display: flex; flex-direction: column; gap: 0.9rem;
  }
  .notes h3 { margin: 0; font-size: 0.95rem; font-weight: 600; }
  .notes ul { margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: 0.5rem; }
  .notes li { font-size: 0.86rem; color: var(--ink-2); }
  .notes li strong { color: var(--ink); font-weight: 600; }
  footer {
    border-top: 1px solid var(--rule); padding-top: 1.25rem;
    font-family: var(--f-mono); font-size: 0.72rem; color: var(--ink-3); line-height: 1.8;
  }
  svg .bar { transition: opacity 0.15s ease; }
  svg .bar:hover { opacity: 0.82; }
  :focus-visible { outline: 2px solid var(--profit); outline-offset: 2px; }
</style>
</head>
<body>
<div class="page">
  <header class="masthead">
    <div class="eyebrow">clau-stock ／ 自動売買 運用記録</div>
    <h1>月次運用統計</h1>
    <p class="standfirst">
      MT5の約定履歴から自動生成した口座別の月次成績。
      1ポジション＝1取引（分割決済は合算）、損益は手数料とスワップを含むネット、月区切りは日本時間の暦月。
      このページの数値・判定はすべて約定履歴から機械的に算出しています。
    </p>
    <div class="meta-strip" id="meta"></div>
  </header>

  <section id="sec-headline"></section>

  <section>
    <div class="section-head">
      <h2>口座別サマリー</h2>
      <p class="section-note">累計損益は集計期間全体の値。役割名は直近に取引のあった月の主戦略から自動判定しています。</p>
    </div>
    <div class="tiles" id="tiles"></div>
  </section>

  <section>
    <div class="section-head">
      <h2>自動チェック</h2>
      <p class="section-note">集計値から機械的に判定した注意点。該当がなければ「指摘なし」と表示されます。</p>
    </div>
    <div class="findings" id="findings"></div>
  </section>

  <section>
    <div class="section-head">
      <h2>戦略別 累計損益</h2>
      <p class="section-note">全口座・全期間。棒の長さは損益の絶対額、基準線の左が損失、右が利益。</p>
    </div>
    <div class="chart-frame"><svg id="strategy-chart" role="img"></svg></div>
  </section>

  <section>
    <div class="section-head">
      <h2>戦略の内容</h2>
      <p class="section-note">上のグラフに出てくる戦略が、それぞれ何を根拠に売買しているかの説明。記録に現れた戦略だけを表示します。</p>
    </div>
    <div class="strat-cards" id="strategy-notes"></div>
  </section>

  <section>
    <div class="section-head">
      <h2>口座別 月次推移</h2>
      <p class="section-note">月ごとのネット損益。目盛は各パネルに表示。棒は基準線より上が利益、下が損失。</p>
    </div>
    <div class="legend">
      <span><span class="swatch" style="background: var(--profit)"></span>利益（基準線より上）</span>
      <span><span class="swatch" style="background: var(--loss)"></span>損失（基準線より下）</span>
    </div>
    <div class="panel-grid" id="panels"></div>
  </section>

  <section>
    <div class="section-head">
      <h2>口座別 明細</h2>
      <p class="section-note">取引のなかった月もゼロ行として表示。in/out は入出金で、損益には含めていません。</p>
    </div>
    <div class="acct-block" id="tables"></div>
  </section>

  <section class="notes">
    <h3>集計の定義と注意点</h3>
    <ul>
      <li><strong>1取引＝1ポジション。</strong>分割決済は1件に合算し、損益にはエントリー分を含む全約定の手数料とスワップを算入しています。</li>
      <li><strong>入出金は損益と分離。</strong>資金投入が「勝った月」に見えないようにしています。月末残高は現在残高から逆算した復元値です。</li>
      <li><strong>PF（プロフィットファクター）</strong>は総利益÷総損失。1.0を下回ると損失超過で、勝ちがない月は 0.00、負けがない月は inf と表示されます。</li>
      <li><strong>月境界のずれ。</strong>約定時刻はブローカーのサーバー時刻基準のため、日本時間の月初・月末に近い取引は隣の月に入ることがあります。月次の粒度では誤差の範囲です。</li>
      <li><strong>直近月は途中経過。</strong>生成時点までの取引しか含まないため、月末までの確定値ではありません。</li>
      <li><strong>過去の成績は将来の成績を保証しません。</strong>このページは運用記録であり、投資判断の助言ではありません。</li>
    </ul>
  </section>

  <footer id="foot"></footer>
</div>

<script type="application/json" id="payload">__DATA_JSON__</script>
<script>
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("payload").textContent);
  var SVG_NS = "http://www.w3.org/2000/svg";

  function yen(v) {
    var s = Math.abs(v).toLocaleString("en-US");
    if (v > 0) return "+¥" + s;
    if (v < 0) return "−¥" + s;
    return "¥0";
  }
  function sc(v) { return v > 0 ? "pos" : (v < 0 ? "neg" : ""); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function el(tag, attrs, text) {
    var n = document.createElementNS(SVG_NS, tag);
    for (var k in attrs) { if (Object.prototype.hasOwnProperty.call(attrs, k)) n.setAttribute(k, attrs[k]); }
    if (text !== undefined) { n.textContent = text; }
    return n;
  }
  function css(v) { return getComputedStyle(document.documentElement).getPropertyValue(v).trim(); }

  /* role = dominant strategy of the most recent month that traded */
  function roleOf(a) {
    var best = null;
    a.byStrategy.forEach(function (r) {
      if (!best || r[0] > best[0] || (r[0] === best[0] && r[3] > best[3])) { best = r; }
    });
    return best ? best[1] : "取引なし";
  }
  function monthsSpan() {
    var all = [];
    D.accounts.forEach(function (a) { a.months.forEach(function (m) { all.push(m.m); }); });
    all.sort();
    return all.length ? [all[0], all[all.length - 1]] : ["-", "-"];
  }

  /* ---------- masthead meta ---------- */
  (function () {
    var span = monthsSpan();
    document.getElementById("meta").innerHTML =
      "<span>集計 <b>" + esc(span[0]) + " → " + esc(span[1]) + "</b></span>" +
      "<span>生成 <b>" + esc(D.generatedAt) + "</b></span>" +
      "<span>通貨 <b>JPY</b></span>" +
      "<span>口座番号は下3桁のみ表示</span>";
    document.getElementById("foot").innerHTML =
      "scripts/monthly_report.py --html が MT5 の約定履歴から自動生成。<br>" +
      "口座番号は下3桁のみ表示。認証情報は含まれていません。";
  })();

  /* ---------- headline ---------- */
  (function () {
    var t = D.totals;
    var cls = t.net >= 0 ? "is-profit" : "is-loss";
    var col = t.net >= 0 ? "pos" : "neg";
    var ops = 0;
    D.accounts.forEach(function (a) { a.months.forEach(function (m) { ops += m.ops; }); });
    document.getElementById("sec-headline").innerHTML =
      '<div class="headline ' + cls + '">' +
        "<div>" +
          '<div class="eyebrow">全口座・全期間 累計損益</div>' +
          '<div class="figure ' + col + '">' + yen(t.net) + "</div>" +
        "</div>" +
        '<p class="caption">取引 ' + t.trades + "件、勝率 " + t.win.toFixed(1) + "%。" +
        "入出金 " + yen(ops) + " は損益から分離済み。" +
        (D.skipped.length ? "接続できなかった口座 " + D.skipped.length + " 件は集計外。" : "") +
        "</p>" +
      "</div>";
  })();

  /* ---------- tiles ---------- */
  (function () {
    var host = document.getElementById("tiles");
    D.accounts.forEach(function (a) {
      var t = document.createElement("div");
      t.className = "tile";
      t.innerHTML =
        '<div class="tile-id"><span class="no">口座' + esc(a.id) + " " + esc(a.mask) + "</span></div>" +
        '<div class="tile-id"><span class="role">' + esc(roleOf(a)) + "</span></div>" +
        '<div class="tile-net ' + sc(a.net) + '">' + yen(a.net) + "</div>" +
        '<div class="tile-rows">' +
          '<div class="tile-row"><span>現在残高</span><span>¥' + a.balance.toLocaleString("en-US") + "</span></div>" +
          '<div class="tile-row"><span>取引数</span><span>' + a.trades + "</span></div>" +
          '<div class="tile-row"><span>勝率</span><span>' + a.win.toFixed(1) + "%</span></div>" +
        "</div>";
      host.appendChild(t);
    });
  })();

  /* ---------- automatic checks ---------- */
  (function () {
    var host = document.getElementById("findings");
    var out = [];

    var losers = D.strategies.filter(function (s) { return s.net < 0; });
    if (losers.length) {
      var worst = losers[0];
      out.push({
        flag: "要対処", cls: "flag--alert",
        title: "累計でマイナスの戦略が " + losers.length + " 件",
        body: "最大の損失源は <strong>" + esc(worst.name) + "</strong>：" + worst.n +
              "取引で <strong>" + yen(worst.net) + "</strong>" +
              (worst.n ? "（1取引あたり " + yen(Math.round(worst.net / worst.n)) + "）" : "") +
              "。内訳は下の「戦略別 累計損益」を参照してください。"
      });
    }

    /* two accounts closing the same number of trades in the same month means a
       gate that is supposed to differentiate them is not differentiating */
    var latest = null;
    D.accounts.forEach(function (a) {
      a.months.forEach(function (m) { if (!latest || m.m > latest) { latest = m.m; } });
    });
    if (latest) {
      var byCount = {};
      D.accounts.forEach(function (a) {
        a.months.forEach(function (m) {
          if (m.m === latest && m.n > 0) {
            (byCount[m.n] = byCount[m.n] || []).push(a.id);
          }
        });
      });
      Object.keys(byCount).forEach(function (n) {
        if (byCount[n].length > 1) {
          out.push({
            flag: "要確認", cls: "flag--check",
            title: "口座 " + byCount[n].join("・") + " の取引数が " + latest + " で一致",
            body: "いずれも <strong>" + n + "取引</strong>。フィルタ条件を変えて比較しているA/B構成であれば、" +
                  "取引数には差が出るはずです。設定が反映されているか、" +
                  "またはこの期間にフィルタが一度も作動しなかったのかを確認してください。"
          });
        }
      });

      var thin = D.accounts.filter(function (a) {
        return a.months.some(function (m) { return m.m === latest && m.n > 0 && m.n < 40; });
      });
      if (thin.length) {
        out.push({
          flag: "経過観察", cls: "flag--check",
          title: "直近月（" + latest + "）はまだ標本が小さい",
          body: "直近月の取引数は各口座 40件未満で、月末までの確定値でもありません。" +
                "この期間の勝率やPFは結論ではなく初期観測値として扱ってください。"
        });
      }
    }

    if (!out.length) {
      out.push({ flag: "指摘なし", cls: "flag--ok", title: "自動チェックの該当なし",
                 body: "累計でマイナスの戦略、口座間の取引数一致、標本不足のいずれにも該当しませんでした。" });
    }

    host.innerHTML = out.map(function (f) {
      return '<div class="finding"><span class="flag ' + f.cls + '">' + esc(f.flag) + "</span>" +
             "<h3>" + esc(f.title) + '</h3><p class="body">' + f.body + "</p></div>";
    }).join("");
  })();

  /* ---------- strategy chart ---------- */
  (function () {
    var svg = document.getElementById("strategy-chart");
    var S = D.strategies;
    if (!S.length) { svg.parentNode.textContent = "戦略別の記録がありません"; return; }

    var W = 800, rowH = 46, padTop = 16, padBottom = 26;
    var H = padTop + S.length * rowH + padBottom;
    var labelW = 132, left = labelW + 34, right = W - 6;
    var maxNeg = 0, maxPos = 0;
    S.forEach(function (s) {
      if (s.net < 0) { maxNeg = Math.max(maxNeg, -s.net); }
      else { maxPos = Math.max(maxPos, s.net); }
    });
    var total = (maxNeg + maxPos) || 1;
    var span = right - left;
    var zeroX = left + (maxNeg / total) * span;

    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("aria-label",
      "戦略別の累計損益。" + S.map(function (s) { return s.name + " " + yen(s.net); }).join("、"));

    var profitC = css("--profit"), lossC = css("--loss"), ink = css("--ink"),
        ink2 = css("--ink-2"), ink3 = css("--ink-3"), rule = css("--rule-strong"),
        onMark = css("--on-mark");

    S.forEach(function (s, i) {
      var top = padTop + i * rowH, barH = 26;
      var w = Math.max(2, Math.abs(s.net) / total * span);
      var x = s.net < 0 ? zeroX - w : zeroX;

      svg.appendChild(el("text", { x: 0, y: top + 13, fill: ink, "font-size": 13,
        "font-weight": 600, "font-family": "var(--f-body)" }, s.name));
      svg.appendChild(el("text", { x: 0, y: top + 28, fill: ink3, "font-size": 10.5,
        "font-family": "var(--f-mono)" }, s.n + "件"));

      var bar = el("rect", { x: x, y: top, width: w, height: barH,
        fill: s.net < 0 ? lossC : profitC, rx: 2, "class": "bar" });
      bar.appendChild(el("title", {}, s.name + "：" + yen(s.net) + "（" + s.n + "取引）"));
      svg.appendChild(bar);

      var inside = w > 130;
      var tx, anchor, fill;
      if (s.net < 0) {
        tx = inside ? zeroX - 10 : x - 8; anchor = "end";
      } else {
        tx = inside ? zeroX + 10 : x + w + 8; anchor = "start";
      }
      fill = inside ? onMark : ink2;
      svg.appendChild(el("text", { x: tx, y: top + 17.5, fill: fill, "font-size": 12,
        "font-family": "var(--f-mono)", "text-anchor": anchor }, yen(s.net)));
    });

    svg.appendChild(el("line", { x1: zeroX, y1: padTop - 6, x2: zeroX,
      y2: H - padBottom + 4, stroke: rule, "stroke-width": 1 }));
    svg.appendChild(el("text", { x: zeroX, y: H - 8, fill: ink3, "font-size": 10.5,
      "font-family": "var(--f-mono)", "text-anchor": "middle" }, "¥0"));
    if (maxNeg > 0) {
      svg.appendChild(el("text", { x: left, y: H - 8, fill: ink3, "font-size": 10.5,
        "font-family": "var(--f-mono)", "text-anchor": "start" },
        "−¥" + maxNeg.toLocaleString("en-US")));
    }
    if (maxPos > 0) {
      svg.appendChild(el("text", { x: right, y: H - 8, fill: ink3, "font-size": 10.5,
        "font-family": "var(--f-mono)", "text-anchor": "end" },
        "+¥" + maxPos.toLocaleString("en-US")));
    }
  })();

  /* ---------- what each strategy actually does ---------- */
  (function () {
    var NOTES = {
      macd: {
        kind: "順張り（トレンド追随）",
        summary: "MACDヒストグラムがゼロを上抜けたら買い、下抜けたら売り。反対側のクロスで手仕舞いします。",
        entry: "MACDヒストグラムのゼロクロス",
        exit: "反対方向のクロス、またはATR基準の損切り",
        filter: "H4（4時間足）のトレンド判定（EMAの傾き＋ADX）に一致する方向のみ。上位足が上昇していないときの買いは見送ります",
        shape: "勝率は低め・1回の利幅が大きい型。検証時の想定勝率は約31%で、少数の大きな勝ちが多数の小さな負けを埋める設計です"
      },
      bollrci: {
        kind: "逆張り（平均回帰）",
        summary: "ボリンジャーバンドの下限を割り込み、かつRCIが売られすぎを示したときに買う、行き過ぎの反発を狙う手法です。",
        entry: "終値が20期間ボリンジャーバンドの−2σを下回り、同時にRCI（9期間の順位相関指数）が−60以下",
        exit: "ミドルバンド（20期間移動平均）まで戻したら利確、またはATR基準の損切り",
        filter: "macdと同じH4トレンドフィルタ。上昇トレンド中の押し目だけを買います",
        shape: "勝率は高め・1回の利幅が小さい型。検証時の想定勝率は約56%で、macdとは逆の損益カーブを描きます"
      },
      donchian: {
        kind: "順張り（ブレイクアウト）",
        summary: "直近N期間の高値を更新したら買い、安値を更新したら売る、古典的なブレイクアウト手法です。",
        entry: "ドンチアンチャネル（直近N期間の高値／安値）の突破＋ATRぶんのバッファ",
        exit: "反対側のチャネルへの回帰、またはATR基準の損切り",
        filter: "EMAの傾き、ADX、ATR％のレンジ判定",
        shape: "トレンドの初動を取りにいく型。レンジ相場では往復で削られます"
      },
      fibonacci: {
        kind: "順張り（押し目・戻り）",
        summary: "直近の値幅に対するフィボナッチ比率まで価格が押したところを、トレンド方向に買う（売る）手法です。",
        entry: "直近スイングの38.2%／50%／61.8%への押し戻しからの反転",
        exit: "戻り高値の更新、またはATR基準の損切り",
        filter: "EMAの傾きによるトレンド方向の一致",
        shape: "エントリー価格が有利になりやすい反面、押し目が来ないまま伸びる相場では機会を逃します"
      },
      kairi: {
        kind: "逆張り（平均回帰）",
        summary: "移動平均線からの乖離率が一定以上に開いたところで、平均への回帰を狙う手法です。",
        entry: "終値が25期間移動平均からATRの一定倍以上下方に乖離",
        exit: "移動平均線への回帰、またはATR基準の損切り",
        filter: "H4トレンドフィルタ",
        shape: "検証段階の戦略です"
      },
      manual: {
        kind: "自動売買ではない",
        summary: "ボットが出したものではない取引。手動で建てたポジション、またはボットのマジックナンバーと一致しない取引がここに入ります。",
        entry: "—（裁量）",
        exit: "—（裁量）",
        filter: "—",
        shape: "自動売買の成績を評価するときは、この行を除いて比較してください"
      },
      unknown: {
        kind: "識別できない取引",
        summary: "設定ファイルにないマジックナンバーの取引です。過去に稼働して現在は設定を削除した戦略の建玉などが該当します。",
        entry: "—", exit: "—", filter: "—",
        shape: "戦略別の評価には使えません"
      }
    };

    var host = document.getElementById("strategy-notes");
    var cards = D.strategies.map(function (s) {
      var note = NOTES[s.name];
      if (!note) {
        note = { kind: "詳細未登録", summary: "この戦略の説明はレポート側に登録されていません。",
                 entry: "—", exit: "—", filter: "—", shape: "—" };
      }
      return '<div class="strat-card">' +
        '<div class="sc-head"><span class="sc-name">' + esc(s.name) + "</span>" +
        '<span class="sc-kind">' + esc(note.kind) + "</span>" +
        '<span class="sc-pnl ' + sc(s.net) + '">' + yen(s.net) + " ／ " + s.n + "件</span></div>" +
        "<p>" + esc(note.summary) + "</p>" +
        "<dl>" +
          "<dt>仕掛け</dt><dd>" + esc(note.entry) + "</dd>" +
          "<dt>手仕舞い</dt><dd>" + esc(note.exit) + "</dd>" +
          "<dt>フィルタ</dt><dd>" + esc(note.filter) + "</dd>" +
          "<dt>性格</dt><dd>" + esc(note.shape) + "</dd>" +
        "</dl></div>";
    }).join("");
    host.innerHTML = cards || '<div class="strat-card"><p>記録された戦略がありません。</p></div>';
  })();

  /* ---------- monthly small multiples ---------- */
  (function () {
    var host = document.getElementById("panels");
    D.accounts.forEach(function (a) {
      var scale = 1;
      a.months.forEach(function (m) { scale = Math.max(scale, Math.abs(m.net)); });

      var panel = document.createElement("div");
      panel.className = "panel";
      var head = document.createElement("header");
      head.innerHTML =
        '<span class="p-title">口座' + esc(a.id) + "　" + esc(roleOf(a)) + "</span>" +
        '<span class="p-scale">目盛 ±¥' + scale.toLocaleString("en-US") + "</span>";
      panel.appendChild(head);

      var W = 320, H = 150, top = 14, bottom = 26;
      var half = (H - top - bottom) / 2, mid = top + half;
      var svg = el("svg", { viewBox: "0 0 " + W + " " + H, role: "img",
        "aria-label": "口座" + a.id + "の月次損益" });
      var slot = W / Math.max(a.months.length, 1);
      var barW = Math.min(30, slot * 0.52);
      var profitC = css("--profit"), lossC = css("--loss"),
          ink3 = css("--ink-3"), rule = css("--rule-strong");

      a.months.forEach(function (m, i) {
        var cx = slot * (i + 0.5);
        var h = Math.abs(m.net) / scale * half;
        if (m.net !== 0 && h < 1.5) { h = 1.5; }
        if (m.net !== 0) {
          var bar = el("rect", { x: cx - barW / 2, y: m.net >= 0 ? mid - h : mid,
            width: barW, height: h, fill: m.net > 0 ? profitC : lossC, rx: 2, "class": "bar" });
          bar.appendChild(el("title", {}, m.m + "：" + yen(m.net) + "（" + m.n + "取引）"));
          svg.appendChild(bar);
        }
        svg.appendChild(el("text", { x: cx, y: H - 13, fill: ink3, "font-size": 9.5,
          "font-family": "var(--f-mono)", "text-anchor": "middle" }, m.m.slice(5) + "月"));
        svg.appendChild(el("text", { x: cx, y: H - 3, fill: ink3, "font-size": 8.5,
          "font-family": "var(--f-mono)", "text-anchor": "middle" }, m.n + "件"));
      });
      svg.appendChild(el("line", { x1: 0, y1: mid, x2: W, y2: mid, stroke: rule, "stroke-width": 1 }));
      panel.appendChild(svg);
      host.appendChild(panel);
    });
  })();

  /* ---------- tables ---------- */
  (function () {
    var host = document.getElementById("tables");
    D.accounts.forEach(function (a) {
      var rows = a.months.map(function (m) {
        return "<tr" + (m.n === 0 ? ' class="quiet"' : "") + ">" +
          "<td>" + esc(m.m) + "</td><td>" + m.n + "</td><td>" + m.win.toFixed(1) + "</td>" +
          "<td>" + esc(m.pf) + "</td>" +
          '<td class="' + sc(m.gp) + '">' + yen(m.gp) + "</td>" +
          '<td class="' + sc(m.gl) + '">' + yen(m.gl) + "</td>" +
          '<td class="' + sc(m.net) + '">' + yen(m.net) + "</td>" +
          "<td>" + (m.ops === 0 ? "—" : yen(m.ops)) + "</td>" +
          "<td>" + (m.bal === null ? "—" : "¥" + m.bal.toLocaleString("en-US")) + "</td></tr>";
      }).join("");

      var wrap = document.createElement("div");
      wrap.className = "table-wrap";
      wrap.innerHTML =
        "<table><caption>口座" + esc(a.id) + "　" + esc(roleOf(a)) +
        '<span class="sub">' + esc(a.mask) + " ／ 現在残高 ¥" + a.balance.toLocaleString("en-US") +
        "</span></caption><thead><tr>" +
        "<th>月</th><th>取引</th><th>勝率%</th><th>PF</th><th>総利益</th><th>総損失</th>" +
        "<th>ネット</th><th>in/out</th><th>月末残高</th></tr></thead><tbody>" + rows +
        '<tr class="total"><td>合計</td><td>' + a.trades + "</td><td>" + a.win.toFixed(1) +
        '</td><td>—</td><td>—</td><td>—</td><td class="' + sc(a.net) + '">' + yen(a.net) +
        "</td><td>—</td><td>¥" + a.balance.toLocaleString("en-US") + "</td></tr></tbody></table>";
      host.appendChild(wrap);

      var strat = a.byStrategy.map(function (s) {
        return "<tr><td>" + esc(s[0]) + "</td><td>" + esc(s[1]) + '</td><td class="' +
          sc(s[2]) + '">' + yen(s[2]) + "</td><td>" + s[3] + "</td></tr>";
      }).join("");
      var sw = document.createElement("div");
      sw.className = "table-wrap";
      sw.innerHTML =
        '<table class="t-strat"><caption>　└ 戦略別内訳<span class="sub">口座' + esc(a.id) +
        "</span></caption><thead><tr><th>月</th><th>戦略</th><th>ネット</th><th>取引</th></tr></thead><tbody>" +
        (strat || '<tr><td colspan="4">記録なし</td></tr>') + "</tbody></table>";
      host.appendChild(sw);
    });
  })();
})();
</script>
</body>
</html>
"""
