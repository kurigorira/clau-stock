# clau-stock

Multi-asset breakout/trend-following auto-trader for **Vantage** via MetaTrader 5.
Ships with tuned presets for 13 instruments and a tri-account launcher out of
the box; any MT5 symbol can be added as a new YAML file.

> Live trading carries real financial risk. Run on a demo account first, validate
> with backtests, and only deploy capital you can afford to lose.

## Built-in presets

Default `start.bat` splits the 13 instruments across three MT5 accounts:

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

## Strategy

Donchian-channel breakout with light regime/strength/risk filters, plus an
H4 multi-timeframe (MTF) trend filter on top.

### Long entry (all conditions on the most recent closed H1 bar)
1. `close > Donchian_high(20).shift(1)`                   - pure breakout
2. `close > EMA(200)`                                     - trend filter (H1)
3. `EMA(200)_now > EMA(200) 3 bars ago`                   - trend slope is up (H1)
4. `ADX(14) >= 0`                                         - filter effectively off
5. `0.01%% <= ATR(14) / close <= 10%%`                      - blocks only dead-flat / blow-off bars
6. **`H4 trend direction == +1`** - H4 EMA200 slope up AND `H4 ADX(14) >= adx_min`
7. `<=1 consecutive loss today`                           - block on the 2nd consecutive loss
8. Today's realized loss `< daily_guard.max_loss_pct%% of equity`

Short is symmetric.

Conditions 1-6 are pure indicator math (`src/gold_trader/strategy.py`).
Conditions 7-8 are enforced at the executor layer using closed deals from the
MT5 history for that bot's `magic_number`. They reset at UTC midnight.

The H4 filter (`trend.higher_timeframe`, default `H4`) drops fake H1 breakouts
that fire against the higher-timeframe trend. Set `trend.higher_timeframe: ""`
in a YAML to disable MTF for that symbol. The H4 frame is cached for 15
minutes per executor, so MT5 API load is virtually identical to H1-only.

### Email notification

When an entry is filled, the executor sends a one-line summary email via
Gmail SMTP. Set `GMAIL_USER`, `GMAIL_APP_PASSWORD` (a 16-char Google App
Password - 2FA required) and `NOTIFY_TO` in `.env` to enable; leave any
blank to disable. SMTP failure is logged at WARNING and never blocks
trading. Throttled at one email per (symbol, side) per 60 seconds.

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
