# clau-stock

Multi-asset auto-trader for **Vantage** via MetaTrader 5. Two strategies —
`donchian` (breakout) and `fibonacci` (pullback, the current default rollout) —
with presets for 50 instruments and a tri-account launcher out of the box; any
MT5 symbol can be added as a new YAML file.

> Live trading carries real financial risk. Run on a demo account first, validate
> with backtests, and only deploy capital you can afford to lose.

## Built-in presets

The fleet was selected by a 6-month donchian-vs-fibonacci backtest
(`scripts/backtest_all.py`): each launched symbol runs whichever strategy won
on its own data, and symbols where **both** strategies lost are not launched.
Preset files are named `fib_<symbol>.yaml` regardless of the strategy inside
(historical; the file name keys the magic_number and start.bat entries).

`start.bat` launches:

| account | symbols | strategy |
|---|---|---|
| 1 | GBPUSD, USDCHF, CL-OIL, BTCUSD | fibonacci (PF 2.93 / 1.27 / 1.15 / 1.42) |
| 1 | NZDUSD, USDCAD, XAUUSD, XAGUSD | donchian (PF 1.21 / 1.18 / 1.50 / 1.25) |
| 2 | JPM, TSLA | fibonacci (PF 1.12 / 1.03) |
| 2 | JPN225ft, AMD, MSFT, NFLX, NVIDIA, META | donchian (PF 1.27-3.72) |
| 2 | CAT COST HD JNJ KO MA MCD NKE PEP PG WMT | fibonacci (PF 1.18-7.06) |
| 2 | CVX, BAC, UNH | donchian (PF 2.37 / 1.16 / 1.66) |
| 3 | EURUSD (`fib_eurusd_small.yaml`, live JPY 20k) | fibonacci (tight filters) |

Crypto is deliberately BTC-only. Non-tech stocks split cleanly the opposite
way from tech: fibonacci won 11 of 14 there, while breakout (donchian) won
5 of 7 tech names. Benched (in repo, not launched):
- both strategies lost: AAPL, NVIDIA.24H, HK50.r, SP500ft.r, COPPER-Cr,
  AUDJPY, AUDUSD, CADJPY, CHFJPY, EURAUD, EURGBP, EURJPY, EURUSD(demo),
  GBPJPY, USDJPY, GE, GS, MRK, ETH/ADA/LTC/XRP/SOL
- awaiting their dump+backtest gate (names fixed to Vantage's spelling):
  DISNEY (`fib_disney.yaml`), PFIZER (`fib_pfizer.yaml`), VISA (`fib_visa.yaml`),
  GOOG (`fib_goog.yaml`), AMAZON (`fib_amazon.yaml`), INTEL (`fib_intel.yaml`),
  BOEING (`fib_boeing.yaml`), EXXON (`fib_exxon.yaml`)
- symbol name failed to dump (fix `symbol:` against MT5 Market Watch first):
  UK-OIL, NG, XPTUSD, XPDUSD, NAS100ft, DJ30ft, GER40ft, UK100ft, AUS200ft

Symbols carried over from the original 13-instrument rollout keep their old
magic_number, so open positions from the retired presets are adopted and exit
through the shared safety exit. The retired donchian-era YAMLs
(`config/eurusd.yaml` etc.) remain in the repo for reference.

### Legacy preset map (donchian era)

### Account 1 (currencies / commodities / crypto)
| YAML                       | Symbol         | magic_number |
|----------------------------|----------------|--------------|
| `config/example.yaml`      | `BTCUSD`       | 20260509     |
| `config/eurusd.yaml`       | `EURUSD`       | 20260511     |
| `config/usdjpy.yaml`       | `USDJPY`       | 20260512     |
| `config/xauusd.yaml`       | `XAUUSD`       | 20260518     |
| `config/xagusd.yaml`       | `XAGUSD`       | 20260519     |
| `config/copper.yaml`       | `COPPER-Cr`    | 20260520     |
| `config/cloil.yaml`        | `CL-OIL`       | 20260521     |

### Account 2 (equities / indices)
| YAML                       | Symbol         | magic_number |
|----------------------------|----------------|--------------|
| `config/nvidia.yaml`       | `NVIDIA`       | 20260513     |
| `config/nvidia_24h.yaml`   | `NVIDIA.24H`   | 20260514     |
| `config/jpn225ft.yaml`     | `JPN225ft`     | 20260515     |
| `config/hk50.yaml`         | `HK50.r`       | 20260516     |
| `config/sp500ft.yaml`      | `SP500ft.r`    | 20260517     |

### Account 3 (small live, JPY ~20k)
| YAML                       | Symbol         | magic_number |
|----------------------------|----------------|--------------|
| `config/eurusd_small.yaml` | `EURUSD`       | 20260523     |

A single-symbol, tightened-filter preset sized for a ~JPY 20,000 live account:
`per_trade_pct: 1.0`, `adx_min: 25`, `atr_buffer_mult: 0.2`, `atr_stop_mult: 1.5`,
`daily_guard.max_loss_pct: 2.0`. EURUSD micro-lots (0.01 = 1,000 units) keep the
per-trade risk at roughly JPY 200 so the account can absorb a normal losing
streak without margin pressure. Uses its own `magic_number` so account 1's
EURUSD bot is unaffected even if both ever ran on the same login.

All presets share the same strategy / filter defaults (defined in
`src/gold_trader/config.py`). Each YAML only overrides what's specific:
`symbol`, `session.trade_days`, `execution.magic_number`, `deviation_points`
and `comment`.

## Strategies

Selected per-YAML via `strategy: donchian | fibonacci` (default `donchian`).
Both share the same H4 trend gate, ATR% sanity band, daily guard, position
sizing, and the Donchian reverse-channel safety exit.

### fibonacci (current rollout) — pullback entry, extension take-profit

Long entry, all on the most recent closed H1 bar (short symmetric):
1. **H4 trend == UP** - H4 EMA200 slope up AND `H4 ADX(14) >= adx_min`
2. **Fib zone** - price inside the 38.2%-78.6% retrace of the H4 swing
   (high/low of the last `swing_lookback` = 20 closed H4 bars)
3. **Bounce** - `bounce_bars` (2) consecutive rising H1 closes
4. **Volume** - H1 volume >= `vol_mult` (1.2) x SMA20(volume)
5. **MACD** - H1 MACD(12,26,9) histogram rising vs the previous bar
6. ATR% inside the per-class `filters.atr_pct_*` band

Orders carry both **SL** (beyond the swing low by `stop_atr_buffer` x ATR) and
**TP** (the 161.8% extension: `swing_high + 0.618 x swing_range`). The
executor's Donchian-10 reverse exit still applies as a trailing safety net, so
a position can close before TP if the move dies.

Tunables live under `fibonacci:` in each YAML — see `FibonacciConfig` in
`src/gold_trader/config.py`.

### donchian (legacy) — breakout entry

1. `close > Donchian_high(20).shift(1) + buffer`, `close > EMA(200)`, EMA slope up
2. `ADX(14) >= adx_min`, ATR% band
3. H4 trend agreement (same gate as fibonacci)

No fixed TP; exits via the reverse Donchian channel or ATR stop.

Daily-guard limits (consecutive losses, daily realized-loss cap) are enforced
at the executor layer for both strategies and reset at UTC midnight. The H4
frame is cached for 15 minutes per executor, so MT5 API load stays flat.

## Backtesting the switch

```bash
# 1. dump history from MT5 (run on the Windows box; ~6 months of H1 bars)
python scripts/dump_history.py --account 1 --months 6 config/fib_*.yaml

# 2. compare donchian vs fibonacci on identical data
python scripts/backtest_all.py                      # all data/*_h1.csv
python scripts/backtest_all.py --config config/fib_xauusd.yaml data/xauusd_h1.csv
```

`backtest_all.py` prints trades / win% / profit factor / total PnL / max
drawdown per symbol per strategy. Judge the fib parameters here **before**
letting the live account trade them; tune `fibonacci:` fields in the YAMLs and
re-run.

### Email notification

When an entry is filled, the executor sends a one-line summary email via
Gmail SMTP. Set `GMAIL_USER`, `GMAIL_APP_PASSWORD` (a 16-char Google App
Password - 2FA required) and `NOTIFY_TO` in `.env` to enable; leave any
blank to disable. SMTP failure is logged at WARNING and never blocks
trading. Throttled at one email per (symbol, side) per 60 seconds.

### Price-change alerts (separate from entry signals)

`scripts/run_alerts.py` is an independent loop that emails you whenever a
watched symbol moves more than `threshold_pct` over the last
`window_minutes` of M1 bars. It does not trade.

Defaults (`config/watchlist.yaml`):
- `threshold_pct: 2.0` - fires at |Δ| >= 2%
- `window_minutes: 10` - close vs close 10 M1 bars ago
- `poll_seconds: 30` - refresh interval per symbol
- `throttle_sec: 1800` - 30-min cooldown per symbol

The alerts process watches the 13 trading-preset symbols by default;
add anything else to `extra_symbols:` in `watchlist.yaml`. `start.bat`
launches the alerts process automatically on account 1's MT5 terminal.
Log: `logs/alerts1.log`. Email subject: `[clau-stock alert] XAUUSD +2.34% in 10min`.

### Stop / exit
- Initial stop: `ATR(14) * 2` from entry (`risk.atr_stop_mult`).
- Exit: 10-bar reverse Donchian.

### Sizing
Per-trade risk = `risk.per_trade_pct`%% of equity, sized via the live MT5 tick
value so the same config works regardless of contract size.

## Quickstart (single-account)

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # fill MT5 creds
```

```bash
# Single account, one or many configs
python scripts/run_live.py config/example.yaml config/eurusd.yaml
```

## Tri-account setup

To trade three accounts in parallel you need three MT5 terminals running side
by side, each logged in to its own account.

### 1. Install additional MT5 terminals (portable mode)

MT5 locks each terminal to its data folder, so two installs with separate data
folders can run concurrently.

1. Copy `C:\Program Files\Vantage MetaTrader 5` to `C:\Vantage MT5 - Account 2`,
   then again to `C:\Vantage MT5 - Account 3`.
2. For each copy, right-click `terminal64.exe`, choose "Create shortcut", and on
   the shortcut Properties append ` /portable` to the Target field.
3. Launch each shortcut and log in with the corresponding account credentials.
4. Confirm all three terminals can run at the same time.

### 2. Populate `.env` with all credential sets

```
MT5_LOGIN_1=<account 1 login>
MT5_PASSWORD_1=<account 1 password>
MT5_SERVER_1=VantageInternational-Live
MT5_PATH_1=C:\Program Files\Vantage MetaTrader 5\terminal64.exe

MT5_LOGIN_2=<account 2 login>
MT5_PASSWORD_2=<account 2 password>
MT5_SERVER_2=VantageInternational-Live
MT5_PATH_2=C:\Vantage MT5 - Account 2\terminal64.exe

MT5_LOGIN_3=<account 3 login>           # small live JPY 20k account
MT5_PASSWORD_3=<account 3 password>
MT5_SERVER_3=VantageInternational-Live
MT5_PATH_3=C:\Vantage MT5 - Account 3\terminal64.exe
```

Use `VantageInternational-Demo` instead of `-Live` for demo accounts.

The legacy un-suffixed (`MT5_LOGIN` / `MT5_PASSWORD` / ...) keys are still
used if you run `python scripts/run_live.py` without `--account`.

### 3. Launch

```
start.bat            # opens all three MT5 terminals + spawns three bot windows
```

or manually:

```bash
python scripts/run_live.py --account 1 config/example.yaml config/eurusd.yaml ...
python scripts/run_live.py --account 2 config/nvidia.yaml config/sp500ft.yaml ...
python scripts/run_live.py --account 3 config/eurusd_small.yaml
```

Each `--account N` instance reads `MT5_LOGIN_N` / `MT5_PASSWORD_N` /
`MT5_SERVER_N` / `MT5_PATH_N` and writes to `logs/accountN.log`.

To move a symbol between accounts: edit the symbol list on the corresponding
`python scripts\run_live.py` line in `start.bat`. `magic_number` already keeps
positions strictly separated regardless of which account places the order.

## Operating account 3 (small live)

The JPY 20k account leaves little headroom. Before and during operation:

- **Verify EURUSD min lot in MT5**: "Market Watch > EURUSD > Specification".
  Vantage normally allows 0.01 (= 1,000 units); if the broker forces 0.1 the
  per-trade risk will exceed `per_trade_pct: 1.0` and you should not run this
  preset on JPY 20k.
- **First 3 trades: watch live.** Confirm `entry side=... vol=0.01` in
  `logs/account3.log`, that the MT5 order ticket shows a stop-loss, and that
  the resulting risk is roughly JPY 150-250.
- **Emergency stop**: close the `clau-stock account 3` cmd window. Existing
  positions stay open and must be closed manually in MT5 if desired.
- **Weekend gap risk**: H1 stops can be jumped on the Sunday open. For the
  first few weeks, consider manually closing the EURUSD position before the
  Friday late-NY close.
- **No cross-account impact**: account 3 uses `magic_number: 20260523`, so it
  cannot touch positions opened by account 1's `eurusd.yaml`
  (`magic_number: 20260511`) even if both ever ran on the same login.

### Backtest
```bash
python scripts/run_backtest.py config/example.yaml data/btcusd_h1.csv
```

### Tests
```bash
pytest -q
```

## Layout
```
src/gold_trader/      core package (config, strategy, risk, mt5 client, executor, backtest)
scripts/              CLI entry points (live, backtest)
config/               one YAML per instrument
tests/                unit tests (no MT5 dependency)
start.bat             tri-account Windows launcher
```

The package directory is still named `gold_trader` for historical reasons; it
is asset-agnostic and trades whatever `symbol` is set in each YAML config.

## Configuration
`config/example.yaml` is the full reference. The other presets inherit the
defaults defined in `src/gold_trader/config.py` and only override:
- `symbol`
- `session.trade_days` - weekend exclusion for non-crypto markets
- `execution.magic_number` - MUST be unique per running bot on the same account
- `execution.deviation_points`
- `execution.comment`

To add a 14th asset: copy one of the YAMLs, edit `symbol` and `magic_number`,
and append the path to the appropriate `python scripts\run_live.py` line in
`start.bat`.

## Notes on Vantage / MT5
- The `MetaTrader5` Python package is **Windows-only** and requires the MT5
  desktop terminal installed and logged in to your Vantage account.
- Use python.org's CPython, not the Microsoft Store build - the Store build
  runs in a sandbox that cannot launch `terminal64.exe` and `MT5 initialize`
  fails with `Process create failed`.
- Symbol names vary by broker. If a preset fails with `unknown symbol`, open the
  MT5 "Market Watch" panel, find the actual name on your Vantage account, and
  update the `symbol:` field in the relevant YAML.
- The MetaTrader5 Python module holds one connection per terminal per process,
  so tri-account operation requires three terminals AND three Python processes
  (one per account). `start.bat` handles both.
