# clau-stock

BTCUSD (Bitcoin) breakout/trend-following auto-trader for **Vantage** via MetaTrader 5.

> Live trading carries real financial risk. Run on a demo account first, validate
> with backtests, and only deploy capital you can afford to lose.

## Strategy
Donchian-channel breakout with an EMA trend filter:
- Long when close > N-bar high **and** close > EMA(trend); short symmetrically.
- ATR-based stop, Donchian-mid exit (M-bar reverse channel break).
- Risk per trade = % of account equity, sized via the live MT5 tick value so it
  works regardless of contract size.

BTC trades 24/7, so the session window in `config/example.yaml` is configured to
be a no-op (`00:00`-`23:59`, all seven weekdays). Tighten it if your broker
suspends BTC CFDs over the weekend.

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
```

The package directory is still named `gold_trader` for historical reasons; it is
asset-agnostic and trades whatever `symbol` is set in the YAML config.

## Configuration
See `config/example.yaml`. Key knobs:
- `symbol` — broker's BTC symbol name (e.g. `BTCUSD`, `BTCUSD.s`, `BITCOIN`);
  check the actual name in the MT5 "Market Watch" panel
- `breakout.donchian_length` — entry channel length
- `breakout.exit_donchian_length` — exit (reverse) channel length
- `trend.ema_length` — trend filter
- `risk.per_trade_pct` — % of equity risked per trade
- `risk.atr_stop_mult` — ATR multiple for initial stop
- `session.start_utc` / `session.end_utc` — UTC trading window

## Notes on Vantage / MT5
- The `MetaTrader5` Python package is **Windows-only** and requires the MT5
  desktop terminal installed and logged in to your Vantage account.
- Use python.org's CPython, not the Microsoft Store build — the Store build
  runs in a sandbox that cannot launch `terminal64.exe` and `MT5 initialize`
  fails with `Process create failed`.
- `MT5_PATH` in `.env` points to a specific `terminal64.exe` if you run multiple
  MT5 installations side by side (e.g. demo + live).
- The executor tags every order with `magic_number` so it only manages its own
  positions — manual trades on the same account are left alone.
