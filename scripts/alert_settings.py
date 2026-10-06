"""Alert settings app: edit config/watchlist.yaml from a page in the browser.

    python scripts/alert_settings.py          (or double-click alert_settings.bat)

Opens http://127.0.0.1:8766 . Saving writes watchlist.yaml in place - every
comment kept - and the running alert loop (scripts/run_alerts.py) re-reads
it on its next poll, so there is nothing to restart. The page then watches
the alert log and says when the change was actually picked up, rather than
assuming it was.

Only this machine can reach it: the server binds to 127.0.0.1, refuses any
other Host header, and every write carries a per-launch token, so a web page
open in another tab cannot post settings to it.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import secrets
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from gold_trader import notify, watchlist  # noqa: E402

TOKEN = secrets.token_urlsafe(24)
log = logging.getLogger("alert_settings")


# --- Japanese messages for the validator's English ones ----------------------

def _ja(message: str) -> str:
    m = re.match(r"must be at least (.+)", message)
    if m:
        return f"{m.group(1)} 以上にしてください"
    m = re.match(r"must be at most (.+)", message)
    if m:
        return f"{m.group(1)} 以下にしてください"
    m = re.match(r"not a symbol name: (.+)", message)
    if m:
        return f"銘柄名として使えません: {m.group(1)}"
    m = re.match(r"at most (\d+) symbols", message)
    if m:
        return f"{m.group(1)} 銘柄までです"
    return {
        "missing": "入力してください",
        "must be a whole number": "整数で入力してください",
        "must be a number": "数値で入力してください",
        "must be true or false": "オン／オフで指定してください",
    }.get(message, message)


# --- what the page needs to know ---------------------------------------------

def fleet_symbol_count() -> int | None:
    """Symbols the alerts always watch via config/us_fleet. None if absent."""
    d = REPO / "config" / "us_fleet"
    if not d.is_dir():
        return None
    return len(list(d.glob("*.yaml")))


def alert_log() -> Path | None:
    """The alert loop's log, newest first if there are several accounts."""
    logs = sorted((REPO / "logs").glob("alerts*.log"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def last_reload_line() -> dict:
    """The alert loop's latest word on the settings: reloaded or refused.

    This is what lets the page say "picked up at 23:41" instead of trusting
    that a save took effect. Read from the tail only; the log grows forever.
    """
    path = alert_log()
    if path is None:
        return {"state": "no-log"}
    try:
        with path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - 64_000))
            tail = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return {"state": "no-log"}
    for line in reversed(tail):
        if "settings reloaded" in line or "was refused" in line:
            state = "reloaded" if "settings reloaded" in line else "refused"
            return {"state": state, **_stamp(line), "line": line[-300:]}
        if "alerts: watching" in line:
            return {"state": "started", **_stamp(line)}
    return {"state": "quiet"}


def _stamp(line: str) -> dict:
    """A log line's time, as display text and as epoch seconds.

    logging writes "2026-10-06 23:41:05,123" - the comma before the
    milliseconds is not ISO 8601 and browsers parse it inconsistently, so
    the page gets a number it can compare with its own clock instead.
    """
    raw = line.split(" | ", 1)[0].strip()
    try:
        t = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S,%f")
    except ValueError:
        return {"at": raw, "epoch": None}
    return {"at": t.strftime("%m/%d %H:%M:%S"), "epoch": t.timestamp()}


# --- HTTP --------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "AlertSettings/1"

    def log_message(self, fmt, *args):  # keep the console readable
        log.debug("%s - " + fmt, self.address_string(), *args)

    def _host_ok(self) -> bool:
        # DNS rebinding: a hostile page can resolve its own name to 127.0.0.1,
        # but it cannot make the browser send "Host: 127.0.0.1:<port>".
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (
            f"127.0.0.1:{port}", f"localhost:{port}"
        )

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        if self.path in ("/", "/index.html"):
            return self._send(200, render_page().encode("utf-8"),
                              "text/html; charset=utf-8")
        if self.path == "/api/status":
            return self._json(200, last_reload_line())
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):  # noqa: N802
        if not self._host_ok():
            return self._send(403, b"forbidden", "text/plain")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 100_000)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"ok": False, "message": "不正なリクエストです"})
        if not secrets.compare_digest(str(body.get("token", "")), TOKEN):
            return self._json(403, {"ok": False,
                                    "message": "ページを開き直してください（期限切れ）"})

        if self.path == "/api/save":
            return self._save(body.get("values") or {})
        if self.path == "/api/test-mail":
            return self._test_mail()
        return self._json(404, {"ok": False, "message": "not found"})

    def _save(self, values: dict) -> None:
        path = self.server.watchlist_path
        clean, errors = watchlist.validate(values)
        if errors:
            return self._json(200, {
                "ok": False,
                "errors": {k: _ja(v) for k, v in errors.items()},
                "message": "入力を確認してください",
            })
        try:
            watchlist.save(path, clean)
        except watchlist.SettingsError as exc:
            log.error("save failed: %s", exc)
            return self._json(200, {"ok": False,
                                    "message": f"保存できませんでした: {exc}"})
        log.info("saved %s", path)
        return self._json(200, {"ok": True, "values": watchlist.load(path)})

    def _test_mail(self) -> None:
        load_dotenv(REPO / ".env")
        import os
        if not (os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD")):
            return self._json(200, {
                "ok": False,
                "message": ".env に GMAIL_USER と GMAIL_APP_PASSWORD が設定されていません。"
                           "この状態ではアラートメールも届きません。",
            })
        to = os.environ.get("NOTIFY_TO") or os.environ.get("GMAIL_USER")
        sent = notify._send_via_gmail(
            "[clau-stock] テストメール",
            "アラート設定アプリからのテスト送信です。\n"
            "これが届いていれば、アラートメールも同じ宛先に届きます。\n",
            log,
        )
        if sent:
            return self._json(200, {"ok": True, "message": f"{to} に送信しました"})
        return self._json(200, {
            "ok": False,
            "message": "送信に失敗しました。アプリ用パスワードと宛先を確認してください"
                       "（詳細はこの窓のログ）。",
        })


# --- the page ----------------------------------------------------------------

def render_page() -> str:
    path = Server.current.watchlist_path
    try:
        values = watchlist.load(path)
        load_error = ""
    except watchlist.SettingsError as exc:
        values = {f.key: f.default for f in watchlist.FIELDS}
        values["extra_symbols"] = []
        load_error = str(exc)
    boot = {
        "token": TOKEN,
        "values": values,
        "fleet": fleet_symbol_count(),
        "path": str(Path(path).relative_to(REPO)) if Path(path).is_relative_to(REPO)
                else str(path),
        "loadError": load_error,
        "ranges": {f.key: [f.lo, f.hi] for f in watchlist.FIELDS},
    }
    # </script> inside a JSON string would end the block early
    data = json.dumps(boot, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace("__BOOT__", data).replace("__PATH__", html.escape(boot["path"]))


class Server(ThreadingHTTPServer):
    current: "Server"
    daemon_threads = True

    def __init__(self, addr, watchlist_path: Path):
        super().__init__(addr, Handler)
        self.watchlist_path = watchlist_path
        Server.current = self


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    p = argparse.ArgumentParser(description="alert settings app")
    p.add_argument("--watchlist", default=str(REPO / "config" / "watchlist.yaml"))
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--no-browser", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level="INFO", format="%(asctime)s | %(message)s")

    path = Path(args.watchlist)
    if not path.is_file():
        sys.stderr.write(f"{path} が見つかりません\n")
        sys.exit(2)

    try:
        srv = Server(("127.0.0.1", args.port), path)
    except OSError:
        srv = Server(("127.0.0.1", 0), path)   # port taken: let the OS choose
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"アラート設定: {url}")
    print(f"編集対象    : {path}")
    print("この窓を閉じると終了します。")
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


PAGE = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>アラート設定</title>
<style>
  :root {
    --bg: #f6f7f9; --surface: #ffffff; --ink: #16181d; --ink-2: #4a505c;
    --ink-3: #7a8190; --rule: #e3e6eb; --accent: #2457d6; --accent-ink: #fff;
    --ok: #127a4a; --ok-bg: #e6f4ec; --bad: #b42318; --bad-bg: #fdecea;
    --warn: #8a5a00; --warn-bg: #fdf3dc; --field: #fbfcfd;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #101216; --surface: #181b21; --ink: #e9ecf1; --ink-2: #b4bac5;
      --ink-3: #858c99; --rule: #2a2f38; --accent: #6e95ff; --accent-ink: #0c1020;
      --ok: #5fd39a; --ok-bg: #12291e; --bad: #ff8a80; --bad-bg: #2f1513;
      --warn: #f0c26a; --warn-bg: #2c2412; --field: #13161b;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: system-ui, -apple-system, "Segoe UI", "Hiragino Sans",
                 "Yu Gothic UI", Meiryo, sans-serif;
    font-size: 15px; line-height: 1.6;
  }
  main { max-width: 760px; margin: 0 auto; padding: 28px 16px 120px; }
  header h1 { margin: 0 0 4px; font-size: 1.45rem; letter-spacing: .01em; }
  header p { margin: 0; color: var(--ink-3); font-size: .85rem; }
  header code { font-size: .8rem; }
  .card {
    background: var(--surface); border: 1px solid var(--rule);
    border-radius: 10px; padding: 18px 20px 6px; margin-top: 18px;
  }
  .card h2 { margin: 0 0 2px; font-size: 1.02rem; }
  .card .lede { margin: 0 0 14px; color: var(--ink-2); font-size: .88rem; }
  .row {
    display: grid; grid-template-columns: 1fr 230px; gap: 6px 16px;
    align-items: center; padding: 12px 0; border-top: 1px solid var(--rule);
  }
  .row:first-of-type { border-top: 0; }
  .row label { font-weight: 600; font-size: .92rem; }
  .row .help { grid-column: 1 / -1; color: var(--ink-3); font-size: .8rem; margin-top: -4px; }
  .row .err { grid-column: 1 / -1; color: var(--bad); font-size: .82rem; display: none; }
  .row.bad .err { display: block; }
  .row.bad input { border-color: var(--bad); }
  .unit { display: flex; align-items: center; gap: 8px; }
  .unit span { color: var(--ink-3); font-size: .85rem; white-space: nowrap; }
  input[type=number], textarea {
    width: 100%; font: inherit; color: var(--ink); background: var(--field);
    border: 1px solid var(--rule); border-radius: 7px; padding: 7px 10px;
  }
  input[type=number] { text-align: right; font-variant-numeric: tabular-nums; }
  input:focus, textarea:focus, button:focus-visible {
    outline: 2px solid var(--accent); outline-offset: 1px;
  }
  textarea { min-height: 120px; resize: vertical; font-family: ui-monospace, Consolas, monospace; }
  .wide { grid-template-columns: 1fr; }
  .toggle { display: flex; gap: 0; border: 1px solid var(--rule); border-radius: 8px; overflow: hidden; }
  .toggle button {
    flex: 1; font: inherit; font-size: .86rem; padding: 7px 8px; border: 0;
    background: var(--field); color: var(--ink-2); cursor: pointer; white-space: nowrap;
  }
  .toggle button[aria-pressed=true] { background: var(--accent); color: var(--accent-ink); font-weight: 600; }
  .summary {
    margin: 4px 0 14px; padding: 10px 12px; border-radius: 8px;
    background: var(--bg); color: var(--ink-2); font-size: .88rem;
  }
  .summary b { color: var(--ink); }
  .fixed { color: var(--ink-3); font-size: .84rem; margin: 0 0 12px; }
  .bar {
    position: fixed; left: 0; right: 0; bottom: 0; background: var(--surface);
    border-top: 1px solid var(--rule); padding: 12px 16px;
  }
  .bar .inner { max-width: 760px; margin: 0 auto; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .btn {
    font: inherit; font-weight: 600; font-size: .92rem; padding: 9px 18px;
    border-radius: 8px; border: 1px solid var(--rule); background: var(--field);
    color: var(--ink); cursor: pointer;
  }
  .btn.primary { background: var(--accent); border-color: var(--accent); color: var(--accent-ink); }
  .btn:disabled { opacity: .5; cursor: default; }
  .spacer { flex: 1; }
  .msg { font-size: .86rem; padding: 6px 10px; border-radius: 7px; display: none; }
  .msg.show { display: inline-block; }
  .msg.ok { background: var(--ok-bg); color: var(--ok); }
  .msg.bad { background: var(--bad-bg); color: var(--bad); }
  .msg.warn { background: var(--warn-bg); color: var(--warn); }
  .status { margin-top: 18px; font-size: .84rem; color: var(--ink-3); }
  .status b { color: var(--ink-2); }
  .banner { margin-top: 16px; padding: 10px 12px; border-radius: 8px; background: var(--bad-bg); color: var(--bad); font-size: .88rem; display: none; }
  @media (max-width: 560px) {
    .row { grid-template-columns: 1fr; }
    .bar .inner { gap: 8px; }
    .btn { padding: 9px 14px; }
  }
</style>
</head>
<body>
<main>
  <header>
    <h1>アラート設定</h1>
    <p>編集対象 <code>__PATH__</code> ・ 保存すると稼働中のアラートに自動で反映されます</p>
  </header>
  <div class="banner" id="loadError"></div>

  <section class="card">
    <h2>急な値動き</h2>
    <p class="lede">短い時間で大きく動いた銘柄を知らせます（1分足）。</p>
    <div class="summary" id="sumIntraday"></div>
    <div class="row" data-key="threshold_pct">
      <label for="threshold_pct">変動率のしきい値</label>
      <div class="unit"><input type="number" id="threshold_pct" step="0.1" min="0.1" max="50"><span>%</span></div>
      <div class="help">上下どちらでも、この率以上動いたら通知します。</div>
      <div class="err"></div>
    </div>
    <div class="row" data-key="window_minutes">
      <label for="window_minutes">比べる時間</label>
      <div class="unit"><input type="number" id="window_minutes" step="1" min="1" max="1440"><span>分前と比較</span></div>
      <div class="help">現在値を、この分数前の値と比べます。</div>
      <div class="err"></div>
    </div>
    <div class="row" data-key="throttle_sec">
      <label for="throttle_min">同じ銘柄の再通知</label>
      <div class="unit"><input type="number" id="throttle_min" step="1" min="0" max="1440"><span>分あける</span></div>
      <div class="help">動きが続いても、同じ銘柄のメールはこの間隔に1通までです。0 で毎回。</div>
      <div class="err"></div>
    </div>
  </section>

  <section class="card">
    <h2>連続した値動き</h2>
    <p class="lede">何日も続けて大きく動いている銘柄を知らせます（日足・終値どうし）。</p>
    <div class="summary" id="sumStreak"></div>
    <div class="row" data-key="streak_threshold_pct">
      <label for="streak_threshold_pct">1日あたりの変動率</label>
      <div class="unit"><input type="number" id="streak_threshold_pct" step="0.1" min="0.1" max="50"><span>% 以上</span></div>
      <div class="help">各日がそれぞれこの率以上動いている必要があります。</div>
      <div class="err"></div>
    </div>
    <div class="row" data-key="streak_days">
      <label for="streak_days">連続日数</label>
      <div class="unit"><input type="number" id="streak_days" step="1" min="1" max="10"><span>日連続</span></div>
      <div class="help">完成した日足で数えます。今日の途中の値動きは含みません。</div>
      <div class="err"></div>
    </div>
    <div class="row" data-key="streak_same_direction">
      <label>方向</label>
      <div class="toggle" role="group" aria-label="方向">
        <button type="button" id="dirSame">同じ方向のみ</button>
        <button type="button" id="dirAny">上下どちらでも</button>
      </div>
      <div class="help" id="dirHelp"></div>
      <div class="err"></div>
    </div>
  </section>

  <section class="card">
    <h2>監視する銘柄</h2>
    <p class="fixed" id="fleetNote"></p>
    <div class="row wide" data-key="extra_symbols">
      <label for="extra_symbols">追加で監視する銘柄（1行に1つ）</label>
      <textarea id="extra_symbols" spellcheck="false" placeholder="例:&#10;GOOGL&#10;AAPL"></textarea>
      <div class="help">MT5 の気配値表示にある名前のまま入力してください（例: NVIDIA.24H）。</div>
      <div class="err"></div>
    </div>
    <div class="row" data-key="poll_seconds">
      <label for="poll_seconds">確認の間隔</label>
      <div class="unit"><input type="number" id="poll_seconds" step="1" min="5" max="3600"><span>秒ごと</span></div>
      <div class="help">短いほど早く気づけますが、銘柄が多いと1巡に時間がかかります。</div>
      <div class="err"></div>
    </div>
  </section>

  <p class="status" id="status">アラートの反映状況を確認しています…</p>
</main>

<div class="bar">
  <div class="inner">
    <button class="btn primary" id="save" disabled>保存</button>
    <button class="btn" id="revert" disabled>元に戻す</button>
    <span class="msg" id="msg" role="status" aria-live="polite"></span>
    <span class="spacer"></span>
    <button class="btn" id="test">テストメール</button>
  </div>
</div>

<script>
(function () {
  "use strict";
  var B = __BOOT__;
  var saved = clone(B.values);
  var $ = function (id) { return document.getElementById(id); };
  var NUM = ["threshold_pct", "window_minutes", "poll_seconds",
             "streak_threshold_pct", "streak_days"];
  var sameDir = !!saved.streak_same_direction;
  var savedAt = null;

  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function fmt(x) { var n = Number(x); return isFinite(n) ? String(n) : "?"; }
  function minutes(sec) { return Math.round(Number(sec) / 60); }

  if (B.loadError) {
    $("loadError").style.display = "block";
    $("loadError").textContent = "設定ファイルを読めませんでした（既定値を表示しています）: " + B.loadError;
  }
  $("fleetNote").textContent = B.fleet === null
    ? "config/us_fleet が見つかりません。下の追加銘柄だけが監視されます。"
    : "このほか、運用中の艦隊 " + B.fleet + " 銘柄は常に監視しています。";

  function fill(v) {
    NUM.forEach(function (k) { $(k).value = v[k]; });
    $("throttle_min").value = minutes(v.throttle_sec);
    $("extra_symbols").value = (v.extra_symbols || []).join("\n");
    sameDir = !!v.streak_same_direction;
    paintDir();
  }

  function read() {
    var v = {};
    NUM.forEach(function (k) { v[k] = $(k).value.trim(); });
    var m = $("throttle_min").value.trim();
    // Shown in minutes, stored in seconds. A hand-set 1830s displays as 31
    // minutes; if the field still says 31 it has not been touched, so keep
    // the exact seconds rather than rounding them into a change nobody made.
    v.throttle_sec = m === "" ? ""
      : Number(m) === minutes(saved.throttle_sec) ? String(saved.throttle_sec)
      : String(Math.round(Number(m) * 60));
    v.streak_same_direction = sameDir;
    v.extra_symbols = $("extra_symbols").value.split(/\s+/).filter(Boolean);
    return v;
  }

  function paintDir() {
    $("dirSame").setAttribute("aria-pressed", String(sameDir));
    $("dirAny").setAttribute("aria-pressed", String(!sameDir));
    $("dirHelp").textContent = sameDir
      ? "上げ続け・下げ続けのときだけ通知します。上げて下げた（行って戻った）だけの銘柄は通知しません。"
      : "上げた日と下げた日が混ざっていても、各日が大きく動いていれば通知します。";
  }

  function summarize() {
    var v = read();
    var t = Number(v.throttle_sec) / 60;
    $("sumIntraday").innerHTML =
      "<b>" + fmt(v.window_minutes) + "分</b>で<b>±" + fmt(v.threshold_pct) +
      "%</b>以上動いたら通知" +
      (t > 0 ? "（同じ銘柄は<b>" + fmt(Math.round(t)) + "分</b>に1通まで）" : "（毎回通知）");
    var p = Number(v.streak_threshold_pct), d = Number(v.streak_days);
    var total = isFinite(p) && isFinite(d) ? (Math.pow(1 + p / 100, d) - 1) * 100 : NaN;
    $("sumStreak").innerHTML =
      "<b>" + fmt(v.streak_days) + "日連続</b>で、それぞれ" +
      (sameDir ? "<b>同じ方向に</b>" : "") + "<b>" + fmt(v.streak_threshold_pct) +
      "%</b>以上動いたら通知" +
      (sameDir && isFinite(total) ? "（合計で少なくとも <b>" + total.toFixed(1) + "%</b> の動き）" : "");
  }

  function dirty() {
    var a = read(), b = saved;
    var keys = NUM.concat(["streak_same_direction"]);
    for (var i = 0; i < keys.length; i++) {
      if (String(a[keys[i]]) !== String(b[keys[i]])) return true;
    }
    if (Number(a.throttle_sec) !== Number(b.throttle_sec)) return true;
    return a.extra_symbols.join(",") !== (b.extra_symbols || []).join(",");
  }

  function refresh() {
    summarize();
    var d = dirty();
    $("save").disabled = !d;
    $("revert").disabled = !d;
  }

  function clearErrors() {
    document.querySelectorAll(".row.bad").forEach(function (r) { r.classList.remove("bad"); });
  }
  function showErrors(errs) {
    Object.keys(errs || {}).forEach(function (k) {
      var row = document.querySelector('.row[data-key="' + k + '"]');
      if (!row) return;
      row.classList.add("bad");
      row.querySelector(".err").textContent = errs[k];
    });
    var first = document.querySelector(".row.bad input, .row.bad textarea");
    if (first) first.focus();
  }

  var msgTimer = null;
  function say(text, kind, sticky) {
    var el = $("msg");
    el.textContent = text;
    el.className = "msg show " + kind;
    clearTimeout(msgTimer);
    if (!sticky) msgTimer = setTimeout(function () { el.className = "msg"; }, 6000);
  }

  function post(path, payload) {
    payload.token = B.token;
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) { return r.json(); });
  }

  $("save").addEventListener("click", function () {
    clearErrors();
    $("save").disabled = true;
    post("/api/save", { values: read() }).then(function (res) {
      if (res.ok) {
        saved = clone(res.values);
        fill(saved);
        savedAt = Date.now();
        say("保存しました。アラートへの反映を確認しています…", "ok", true);
        pollStatus();
      } else {
        showErrors(res.errors);
        say(res.message || "保存できませんでした", "bad");
      }
      refresh();
    }).catch(function () {
      say("アプリと通信できません。設定アプリの窓が閉じていないか確認してください", "bad");
      refresh();
    });
  });

  $("revert").addEventListener("click", function () {
    clearErrors(); fill(saved); refresh();
    say("保存済みの値に戻しました", "ok");
  });

  $("test").addEventListener("click", function () {
    $("test").disabled = true;
    say("送信しています…", "warn", true);
    post("/api/test-mail", {}).then(function (res) {
      say(res.message, res.ok ? "ok" : "bad");
    }).catch(function () {
      say("アプリと通信できません", "bad");
    }).then(function () { $("test").disabled = false; });
  });

  $("dirSame").addEventListener("click", function () { sameDir = true; paintDir(); refresh(); });
  $("dirAny").addEventListener("click", function () { sameDir = false; paintDir(); refresh(); });
  document.querySelectorAll("input, textarea").forEach(function (el) {
    el.addEventListener("input", function () {
      var row = el.closest(".row"); if (row) row.classList.remove("bad");
      refresh();
    });
  });
  window.addEventListener("beforeunload", function (e) {
    if (dirty()) { e.preventDefault(); e.returnValue = ""; }
  });

  // What the alert loop itself last said about the settings. After a save,
  // keep asking until it reports a reload newer than the save - or refusal.
  function describe(s) {
    if (s.state === "no-log") return "アラートのログがまだありません。start.bat でアラートを起動すると、保存は次の確認時に反映されます。";
    if (s.state === "reloaded") return "アラートは <b>" + s.at + "</b> に設定を読み込み直しました。";
    if (s.state === "refused") return "アラートは <b>" + s.at + "</b> に設定の読み込みを拒否しました（前の設定で動作中）。";
    if (s.state === "started") return "アラートは <b>" + s.at + "</b> に起動し、そのときの設定で動作しています。";
    return "アラートのログに設定の記録が見つかりません。";
  }
  var tries = 0, pollHandle = null;
  function pollStatus() {
    tries = 0;
    clearInterval(pollHandle);
    pollHandle = setInterval(checkOnce, 3000);
    checkOnce();
  }
  function checkOnce() {
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (s) {
      $("status").innerHTML = describe(s);
      if (savedAt === null) { clearInterval(pollHandle); return; }
      var fresh = s.epoch != null && s.epoch * 1000 >= savedAt - 2000;
      if (fresh && s.state === "reloaded") {
        say("保存しました。アラートに反映済みです", "ok");
        savedAt = null; clearInterval(pollHandle);
      } else if (fresh && s.state === "refused") {
        say("アラートが新しい設定を拒否しました（前の設定で動作中）", "bad", true);
        savedAt = null; clearInterval(pollHandle);
      } else if (++tries > Math.ceil((Number(saved.poll_seconds) + 60) / 3)) {
        say("保存しました。アラートが動いていないようです（start.bat で起動すると反映されます）", "warn", true);
        savedAt = null; clearInterval(pollHandle);
      }
    }).catch(function () {});
  }

  fill(saved);
  refresh();
  checkOnce();
})();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
