# clau-stock

Multi-asset breakout/trend-following auto-trader for **Vantage** via MetaTrader 5.
Ships with tuned presets for **BTCUSD** and **EURUSD**; any MT5 symbol can be added
as a new YAML file.

> Live trading carries real financial risk. Run on a demo account first, validate
> with backtests, and only deploy capital you can afford to lose.

## Strategy

Donchian-channel breakout with light regime/strength/risk filters. Same logic
for every symbol; thresholds are tuned per asset in its YAML.

### Long entry (all conditions on the most recent closed H1 bar)
1. `close > Donchian_high(20).shift(1) + ATR(14) * atr_buffer_mult` - breakout
2. `close > EMA(200)`                                     - trend filter
3. `EMA(200)_now > EMA(200) ema_slope_lookback bars ago`  - trend slope is up
4. `ADX(14) >= adx_min`                                   - trending regime
5. `atr_pct_min <= ATR(14) / close <= atr_pct_max`        - volatility regime
6. `<=1 consecutive loss today`                           - block on the 2nd consecutive loss
7. Today's realized loss `< 1%% of equity`                 - daily loss cap

Short is symmetric (mirror with `<` and `< 0` slope).

Conditions 1-5 are pure indicator math (`src/gold_trader/strategy.py`).
Conditions 6-7 are enforced at the executor layer using closed deals from the
MT5 history for that bot's `magic_number`. They reset at UTC midnight.

The executor also writes a one-line `bar:` INFO log per H1 close with all
indicator values, so it's easy to see which filter is rejecting setups when
tuning thresholds.

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
# single asset
python scripts/run_live.py config/example.yaml

# multiple assets in one process / one MT5 connection
python scripts/run_live.py config/example.yaml config/eurusd.yaml

# or just double-click start.bat (already configured for BTCUSD + EURUSD)
```

Each instance gets its own child logger, so log lines are prefixed with the
symbol: `gold_trader.BTCUSD` / `gold_trader.EURUSD`. Each has its own
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
config/example.yaml   BTCUSD preset (24/7, crypto vol)
config/eurusd.yaml    EURUSD preset (24/5, FX vol)
tests/                unit tests (no MT5 dependency)
start.bat             Windows launcher: auto-starts MT5 then runs both bots
```

The package directory is still named `gold_trader` for historical reasons; it is
asset-agnostic and trades whatever `symbol` is set in each YAML config.

## Configuration
See `config/example.yaml` (BTCUSD) or `config/eurusd.yaml` (EURUSD). Key knobs:
- `symbol` - broker's symbol name (check the MT5 "Market Watch" panel for the exact name)
- `trend.ema_length` / `trend.ema_slope_lookback`
- `breakout.donchian_length` / `breakout.atr_buffer_mult` / `breakout.exit_donchian_length`
- `risk.per_trade_pct` / `risk.atr_stop_mult` / `risk.max_positions`
- `filters.adx_min` / `filters.atr_pct_min` / `filters.atr_pct_max`
- `daily_guard.max_consecutive_losses` / `daily_guard.max_loss_pct`
- `session.start_utc` / `session.end_utc` / `session.trade_days`
- `execution.magic_number` - MUST be unique per running bot on the same account
- `execution.deviation_points` - acceptable slippage on entry (tighter for FX)

To add a third asset: copy one of the YAMLs, edit `symbol`, give it a fresh
`magic_number`, and append the path to the `start.bat` python line.

## Notes on Vantage / MT5
- The `MetaTrader5` Python package is **Windows-only** and requires the MT5
  desktop terminal installed and logged in to your Vantage account.
- Use python.org's CPython, not the Microsoft Store build - the Store build
  runs in a sandbox that cannot launch `terminal64.exe` and `MT5 initialize`
  fails with `Process create failed`.
- `MT5_PATH` in `.env` points to a specific `terminal64.exe` if you run multiple
  MT5 installations side by side (e.g. demo + live). `start.bat` reads it too.
- The executor tags every order with `magic_number` so it only manages its own
  positions - manual trades and other bots on the same account are left alone.
