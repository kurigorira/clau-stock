# Monthly operating statistics

Generated 2026-09-30 06:30 JST from live MT5 account history (`scripts/monthly_report.py --markdown`).

One closed **position** counts as one trade (partial closes collapse) and its PnL includes commission and swap on every deal of the position. Months are JST calendar months; a month with no trades is shown as a zero row. Deposits and withdrawals are reported separately from trading PnL, so a funded month cannot read as a winning one. All amounts in JPY.

## Summary

| account | months | trades | win % | PF | net PnL |
|---|---:|---:|---:|---:|---:|
| 1 (***431) | 5 | 211 | 26.1 | 0.73 | -268,744 |
| 2 (***128) | 5 | 212 | 28.3 | 0.89 | -77,812 |
| 3 (***497) | 6 | 80 | 43.8 | 1.06 | +6,833 |
| 4 (***565) | 2 | 94 | 40.4 | 0.84 | -1,944 |
| 5 (***010) | 2 | 13 | 30.8 | 0.08 | -101,427 |

## Cost of carry

What each open book costs to **keep** open. None of this is in the tables above: financing is charged whether or not anything is closed, and it is charged on the notional, not on the account. The last column is what matters for survival — at leverage, a rate the broker would call ordinary becomes a multiple of the account per year.

| account | notional | equity | leverage | financing/yr | as % of equity |
|---|---:|---:|---:|---:|---:|
| 1 | 606,901 | 710,165 | 0.9x | -39,596 * | -5.6% * |
| 2 | 914,065 | 724,020 | 1.3x | +35,399 * | +4.9% * |
| 4 | 91,520 | 97,482 | 0.9x | -19,937 * | -20.5% * |

\* **Provisional.** Swap is not charged evenly — the weekend is billed on a single night at triple rate — so the charge arrives in weekly lumps while the days it is divided by accrue daily. The reading swings across the week, by roughly ±29% at a week held and ±7% at a month, so these are worth reading as numbers near a month, not before.

## Account 1 (***431)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 27 | 25.9 | 0.64 | +226,560 | -353,534 | -126,974 | +990,000 | 863,026 |
| 2026-06 | 31 | 41.9 | 1.41 | +395,459 | -281,454 | +114,005 | 0 | 977,031 |
| 2026-07 | 21 | 14.3 | 0.11 | +20,346 | -180,028 | -159,682 | 0 | 817,349 |
| 2026-08 | 12 | 25.0 | 0.62 | +13,465 | -21,869 | -8,404 | 0 | 808,945 |
| 2026-09 | 120 | 24.2 | 0.48 | +79,911 | -167,600 | -87,689 | 0 | 721,256 |
| **total** | **211** | **26.1** | | | | **-268,744** | | **721,256** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-05 | ambiguous | -96,334 | 20 |
| 2026-05 | donchian | -30,640 | 7 |
| 2026-06 | ambiguous | +67,756 | 18 |
| 2026-06 | donchian | +46,249 | 13 |
| 2026-07 | ambiguous | -80,729 | 5 |
| 2026-07 | donchian | -33,386 | 8 |
| 2026-07 | fibonacci | -449 | 3 |
| 2026-07 | manual | -29,503 | 1 |
| 2026-07 | unknown | -15,615 | 4 |
| 2026-08 | donchian | +5,833 | 3 |
| 2026-08 | fibonacci | +1,695 | 4 |
| 2026-08 | unknown | -15,932 | 5 |
| 2026-09 | buyhold | -8,433 | 12 |
| 2026-09 | macd | -87,719 | 104 |
| 2026-09 | unknown | +8,463 | 4 |

How trades ended:

| exit | trades |
|---|---:|
| stop loss | 95 |
| the strategy's own exit | 95 |
| closed by hand | 19 |
| take profit | 2 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| buyhold | 89 | 52.40 | -11,091 | -758 | 606,901 |

Financing: **-108/day** → **-39,596/yr**, **-6.5%/yr of notional**, measured over 89 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

**This rate is provisional** — roughly **±29%** at this age. The book is 7.0 day(s) old, and swap is not charged evenly: the weekend is billed on a single night at triple rate, so the charge arrives in weekly lumps while the days it is divided by accrue daily. The reading therefore swings across the week — jumping on the triple night, decaying every day after — with the swing shrinking as roughly 1/days. It is worth reading as a number near 28 days, not before.

## Account 2 (***128)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 14 | 28.6 | 0.67 | +122,356 | -181,345 | -58,989 | +800,000 | 741,011 |
| 2026-06 | 20 | 40.0 | 1.71 | +399,529 | -233,301 | +166,228 | 0 | 907,239 |
| 2026-07 | 16 | 25.0 | 0.12 | +10,837 | -90,700 | -79,863 | 0 | 827,376 |
| 2026-08 | 24 | 12.5 | 0.16 | +6,643 | -41,720 | -35,077 | 0 | 792,299 |
| 2026-09 | 138 | 29.7 | 0.56 | +89,577 | -159,688 | -70,111 | 0 | 722,188 |
| **total** | **212** | **28.3** | | | | **-77,812** | | **722,188** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-05 | ambiguous | -37,973 | 5 |
| 2026-05 | donchian | -21,016 | 9 |
| 2026-06 | ambiguous | +116,616 | 13 |
| 2026-06 | donchian | +49,612 | 7 |
| 2026-07 | donchian | -76,118 | 12 |
| 2026-07 | fibonacci | -3,745 | 4 |
| 2026-08 | donchian | -27,027 | 16 |
| 2026-08 | fibonacci | -4,005 | 6 |
| 2026-08 | unknown | -4,045 | 2 |
| 2026-09 | donchian | -2,456 | 1 |
| 2026-09 | fibonacci | +2,988 | 3 |
| 2026-09 | macd | -81,676 | 132 |
| 2026-09 | unknown | +11,033 | 2 |

How trades ended:

| exit | trades |
|---|---:|
| the strategy's own exit | 106 |
| stop loss | 98 |
| closed by hand | 7 |
| take profit | 1 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| macd | 9 | 83.40 | +1,832 | -227 | 914,065 |

Financing: **+97/day** → **+35,399/yr**, **+4.2%/yr of notional**, measured over 8 position(s) held at least a day. 1 position(s) are too new to count. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

**This rate is provisional** — roughly **±29%** at this age. The book is 7.0 day(s) old, and swap is not charged evenly: the weekend is billed on a single night at triple rate, so the charge arrives in weekly lumps while the days it is divided by accrue daily. The reading therefore swings across the week — jumping on the triple night, decaying every day after — with the swing shrinking as roughly 1/days. It is worth reading as a number near 28 days, not before.

## Account 3 (***497)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-04 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | -104 | 7,685 |
| 2026-05 | 3 | 33.3 | 0.31 | +5,166 | -16,454 | -11,288 | +11,032 | 7,429 |
| 2026-06 | 9 | 44.4 | 4.41 | +30,844 | -7,002 | +23,842 | +6,679 | 37,950 |
| 2026-07 | 3 | 0.0 | 0.00 | 0 | -7,474 | -7,474 | -122 | 30,354 |
| 2026-08 | 2 | 50.0 | 10.37 | +3,672 | -354 | +3,318 | -16,186 | 17,486 |
| 2026-09 | 63 | 46.0 | 0.98 | +83,112 | -84,677 | -1,565 | -15,921 | 0 |
| **total** | **80** | **43.8** | | | | **+6,833** | | **0** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-05 | manual | -11,288 | 3 |
| 2026-06 | manual | +23,842 | 9 |
| 2026-07 | manual | -7,474 | 3 |
| 2026-08 | manual | +3,318 | 2 |
| 2026-09 | manual | -1,565 | 63 |

How trades ended:

| exit | trades |
|---|---:|
| closed by hand | 74 |
| stop loss | 6 |

## Account 4 (***565)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | +100,000 | 100,000 |
| 2026-09 | 94 | 40.4 | 0.84 | +9,916 | -11,860 | -1,944 | 0 | 98,056 |
| **total** | **94** | **40.4** | | | | **-1,944** | | **98,056** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-09 | bollrci | -1,944 | 94 |

How trades ended:

| exit | trades |
|---|---:|
| stop loss | 48 |
| the strategy's own exit | 42 |
| closed by hand | 4 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| bollrci | 5 | 5.90 | -574 | -27 | 91,520 |

Financing: **-55/day** → **-19,937/yr**, **-22.8%/yr of notional**, measured over 4 position(s) held at least a day. 1 position(s) are too new to count. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

**This rate is provisional** — roughly **±49%** at this age. The book is 4.1 day(s) old, and swap is not charged evenly: the weekend is billed on a single night at triple rate, so the charge arrives in weekly lumps while the days it is divided by accrue daily. The reading therefore swings across the week — jumping on the triple night, decaying every day after — with the swing shrinking as roughly 1/days. It is worth reading as a number near 28 days, not before.

## Account 5 (***010)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08 | 2 | 0.0 | 0.00 | 0 | -14,931 | -14,931 | +15,000 | -1,071 |
| 2026-09 | 11 | 36.4 | 0.10 | +9,092 | -95,588 | -86,496 | +87,567 | 0 |
| **total** | **13** | **30.8** | | | | **-101,427** | | **0** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-08 | manual | -14,931 | 2 |
| 2026-09 | manual | -86,496 | 11 |

How trades ended:

| exit | trades |
|---|---:|
| stop loss | 8 |
| closed by hand | 3 |
| **margin stop-out** | 2 |

**2 position(s) were closed by the broker for margin, not by a decision.** A stop-out means the account ran out of cover while the positions were still open — the size was the problem, whatever the trades were doing.

