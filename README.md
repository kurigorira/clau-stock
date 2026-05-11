# clau-stock

BTCUSD (Bitcoin) breakout/trend-following auto-trader for **Vantage** via MetaTrader 5.

> Live trading carries real financial risk. Run on a demo account first, validate
> with backtests, and only deploy capital you can afford to lose.

## Strategy

Donchian-channel breakout with multi-layer regime / strength / risk filters.

### Long entry (all conditions on the most recent closed H1 bar)
1. `close > Donchian_high(20).shift(1) + ATR(14) * 0.05` - breakout with ATR buffer
2. `close > EMA(200)`                                     - trend filter
3. `EMA(200)_now > EMA(200) 10 bars ago`                  - trend slope is up
4. `ADX(14) >= 18`                                        - trending regime
5. `0.3%% <= ATR(14) / close <= 2.5%%`                      - volatility regime
6. `<=1 consecutive loss today`                           - block on the 2nd consecutive loss
7. Today's realized loss `< 1%% of equity`                 - daily loss cap

Short is symmetric (mirror with `<` and `< 0` slope).

Conditions 1-5 are pure indicator math (`src/gold_trader/strategy.py`).
Conditions 6-7 are enforced at the executor layer using closed deals from the
MT5 history for the bot's `magic_number`. They reset at UTC midnight.

### Stop / exit
- Initial stop: `ATR(14) * 2` from entry (`risk.atr_stop_mult`).
- Exit: 10-bar reverse Donchian (close below recent low for longs / above recent high for shorts).

### Sizing
Per-trade risk = `risk.per_trade_pct`%% of equity, sized via the live MT5 tick value
so the same config works regardless of contract size.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                 # fill MT5 creds
```

### Backtest
```bash
python scripts/run_backtest.py config/example.yaml data/btcusd_h1.csv
```

### Live (Windows + MT5 terminal logged in to Vantage)
```bash
python scripts/run_live.py config/example.yaml
# or, on Windows, double-click start.bat
```

### Tests
```bash
pytest -q
```

## Layout
```
src/gold_trader/      core package (config, strategy, risk, mt5 client, executor, backtest)
scripts/              CLI entry points (live, backtest)
config/               example YAML configs
tests/                unit tests (no MT5 dependency)
start.bat             Windows one-click launcher (auto-starts MT5 + bot)
```

The package directory is still named `gold_trader` for historical reasons; it is
asset-agnostic and trades whatever `symbol` is set in the YAML config.

## Configuration
See `config/example.yaml`. Key knobs:
- `symbol` - broker's BTC symbol name (e.g. `BTCUSD`, `BTCUSD.s`, `BITCOIN`);
  check the actual name in the MT5 "Market Watch" panel
- `trend.ema_length` / `trend.ema_slope_lookback` - trend filter and slope window
- `breakout.donchian_length` / `breakout.atr_buffer_mult` - entry channel and breakout buffer
- `breakout.exit_donchian_length` - reverse-channel exit length
- `risk.per_trade_pct` / `risk.atr_stop_mult` - risk per trade, ATR stop multiple
- `filters.adx_min` / `filters.atr_pct_min` / `filters.atr_pct_max` - regime filters
- `daily_guard.max_consecutive_losses` / `daily_guard.max_loss_pct` - daily circuit breakers
- `session.start_utc` / `session.end_utc` / `session.trade_days` - trading window (default 24/7 for BTC)

## Notes on Vantage / MT5
- The `MetaTrader5` Python package is **Windows-only** and requires the MT5
  desktop terminal installed and logged in to your Vantage account.
- Use python.org's CPython, not the Microsoft Store build - the Store build
  runs in a sandbox that cannot launch `terminal64.exe` and `MT5 initialize`
  fails with `Process create failed`.
- `MT5_PATH` in `.env` points to a specific `terminal64.exe` if you run multiple
  MT5 installations side by side (e.g. demo + live). `start.bat` reads it too.
- The executor tags every order with `magic_number` so it only manages its own
  positions - manual trades on the same account are left alone.
