# clau-stock

Multi-asset breakout/trend-following auto-trader for **Vantage** via MetaTrader 5.
Ships with tuned presets for 12 instruments out of the box; any MT5 symbol can
be added as a new YAML file.

> Live trading carries real financial risk. Run on a demo account first, validate
> with backtests, and only deploy capital you can afford to lose.

## Built-in presets

| YAML                       | Symbol         | Description                       | magic_number |
|----------------------------|----------------|-----------------------------------|--------------|
| `config/example.yaml`      | `BTCUSD`       | Bitcoin (24/7)                    | 20260509     |
| `config/eurusd.yaml`       | `EURUSD`       | Euro / US Dollar                  | 20260511     |
| `config/usdjpy.yaml`       | `USDJPY`       | US Dollar / Japanese Yen          | 20260512     |
| `config/nvidia.yaml`       | `NVIDIA`       | NVIDIA Corp stock CFD             | 20260513     |
| `config/nvidia_24h.yaml`   | `NVIDIA.24H`   | NVIDIA 24-hour CFD                | 20260514     |
| `config/jpn225ft.yaml`     | `JPN225ft`     | Nikkei 225 Future                 | 20260515     |
| `config/hk50.yaml`         | `HK50.r`       | Hang Seng Index Cash CFD          | 20260516     |
| `config/sp500ft.yaml`      | `SP500ft.r`    | S&P 500 Future                    | 20260517     |
| `config/xauusd.yaml`       | `XAUUSD`       | Gold / US Dollar                  | 20260518     |
| `config/xagusd.yaml`       | `XAGUSD`       | Silver / US Dollar                | 20260519     |
| `config/copper.yaml`       | `COPPER-Cr`    | Copper                            | 20260520     |
| `config/cloil.yaml`        | `CL-OIL`       | Crude Oil Future CFD              | 20260521     |

All presets share the same strategy / filter defaults (defined in
`src/gold_trader/config.py`). Each YAML only overrides what's specific:
`symbol`, `session.trade_days`, `execution.magic_number`, `deviation_points`
and `comment`.

## Strategy

Donchian-channel breakout with light regime/strength/risk filters.

### Long entry (all conditions on the most recent closed H1 bar)
1. `close > Donchian_high(20).shift(1)`                   - pure breakout (buffer disabled)
2. `close > EMA(200)`                                     - trend filter
3. `EMA(200)_now > EMA(200) 10 bars ago`                  - trend slope is up
4. `ADX(14) >= 10`                                        - sanity floor
5. `0.1%% <= ATR(14) / close <= 10%%`                       - blocks only dead-flat / blow-off bars
6. `<=1 consecutive loss today`                           - block on the 2nd consecutive loss
7. Today's realized loss `< 1%% of equity`                 - daily loss cap

Short is symmetric (mirror with `<` and `< 0` slope).

Conditions 1-5 are pure indicator math (`src/gold_trader/strategy.py`).
Conditions 6-7 are enforced at the executor layer using closed deals from the
MT5 history for that bot's `magic_number`. They reset at UTC midnight.

### Stop / exit
- Initial stop: `ATR(14) * 2` from entry (`risk.atr_stop_mult`).
- Exit: 10-bar reverse Donchian.

### Sizing
Per-trade risk = `risk.per_trade_pct`%% of equity, sized via the live MT5 tick value
so the same config works regardless of contract size.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # fill MT5 creds
```

### Live (Windows + MT5 terminal logged in to Vantage)
```bash
# all 12 presets at once (default)
start.bat            # double-click on Windows

# or a custom subset
python scripts/run_live.py config/example.yaml config/eurusd.yaml
```

All instances run inside a single Python process / single MT5 connection.
Each instance gets its own child logger so log lines are prefixed with the
symbol, e.g. `gold_trader.BTCUSD` / `gold_trader.EURUSD`. Each has its own
`magic_number` so positions stay strictly separated even on the same account.

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
start.bat             Windows launcher: auto-starts MT5 then runs all bots
```

The package directory is still named `gold_trader` for historical reasons; it
is asset-agnostic and trades whatever `symbol` is set in each YAML config.

## Configuration
`config/example.yaml` is the full reference. The other presets inherit the
defaults defined in `src/gold_trader/config.py` and only override:
- `symbol` - broker's symbol name (check the MT5 "Market Watch" panel)
- `session.trade_days` - weekend exclusion for non-crypto markets
- `execution.magic_number` - MUST be unique per running bot on the same account
- `execution.deviation_points` - acceptable slippage (tighter for FX, wider for indices)
- `execution.comment` - tag on every order so you can audit which preset placed it

To add a 13th asset: copy one of the YAMLs, edit `symbol` and `magic_number`,
and append the new path to the `python scripts\run_live.py` line in `start.bat`.

## Notes on Vantage / MT5
- The `MetaTrader5` Python package is **Windows-only** and requires the MT5
  desktop terminal installed and logged in to your Vantage account.
- Use python.org's CPython, not the Microsoft Store build - the Store build
  runs in a sandbox that cannot launch `terminal64.exe` and `MT5 initialize`
  fails with `Process create failed`.
- `MT5_PATH` in `.env` points to a specific `terminal64.exe` if you run multiple
  MT5 installations side by side. `start.bat` reads it too.
- Symbol names vary by broker. If a preset fails with `unknown symbol`, open the
  MT5 "Market Watch" panel, find the actual name on your Vantage account, and
  update the `symbol:` field in the relevant YAML.
- The MetaTrader5 Python module supports only one connection per terminal, so
  all symbols run inside a single Python process sharing that connection.
