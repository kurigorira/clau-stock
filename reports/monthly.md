# Monthly operating statistics

Generated 2026-11-28 06:30 JST from live MT5 account history (`scripts/monthly_report.py --markdown`).

One closed **position** counts as one trade (partial closes collapse) and its PnL includes commission and swap on every deal of the position. Months are JST calendar months; a month with no trades is shown as a zero row. Deposits and withdrawals are reported separately from trading PnL, so a funded month cannot read as a winning one. All amounts in JPY.

## Summary

| account | months | trades | win % | PF | net PnL |
|---|---:|---:|---:|---:|---:|
| 1 (***431) | 4 | 184 | 26.1 | 0.78 | -141,770 |
| 2 (***128) | 6 | 627 | 26.2 | 0.83 | -163,742 |
| 3 (***497) | 6 | 88 | 44.3 | 1.16 | +19,478 |
| 4 (***565) | 4 | 370 | 44.1 | 0.82 | -8,032 |
| 5 (***010) | 3 | 21 | 23.8 | 0.09 | -120,068 |

## Cost of carry

What each open book costs to **keep** open. None of this is in the tables above: financing is charged whether or not anything is closed, and it is charged on the notional, not on the account. The last column is what matters for survival — at leverage, a rate the broker would call ordinary becomes a multiple of the account per year.

These describe **the positions open at this snapshot**. For a book that is genuinely held, consecutive days measure the same book and the rate converges. For one that trades, they measure whatever happened to be open each morning — different positions, different symbols, sometimes a different direction — so two readings are not two estimates of one number and the rate can swing, or change sign, without anything being wrong.

| account | notional | equity | leverage | financing/yr | as % of equity |
|---|---:|---:|---:|---:|---:|
| 1 | 626,274 | 714,924 | 0.9x | -35,273 | -4.9% |
| 2 | 911,053 | 597,402 | 1.5x | -48,412 * | -8.1% * |
| 4 | 188,031 | 91,947 | 2.0x | -334 * | -0.4% * |

\* **Provisional.** Swap is not charged evenly — the weekend is billed on a single night at triple rate — so the charge arrives in weekly lumps while the days it is divided by accrue daily. The reading swings across the week, by roughly ±29% at a week held and ±7% at a month, so these are worth reading as numbers near a month, not before.

## Account 1 (***431)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-06 | 31 | 41.9 | 1.41 | +395,459 | -281,454 | +114,005 | 0 | 977,031 |
| 2026-07 | 21 | 14.3 | 0.11 | +20,346 | -180,028 | -159,682 | 0 | 817,349 |
| 2026-08 | 12 | 25.0 | 0.62 | +13,465 | -21,869 | -8,404 | 0 | 808,945 |
| 2026-09 | 120 | 24.2 | 0.48 | +79,911 | -167,600 | -87,689 | 0 | 721,256 |
| **total** | **184** | **26.1** | | | | **-141,770** | | **721,256** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
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
| stop loss | 84 |
| the strategy's own exit | 79 |
| closed by hand | 19 |
| take profit | 2 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| buyhold | 89 | 52.40 | -6,332 | -6,377 | 626,274 |

Financing: **-97/day** → **-35,273/yr**, **-5.6%/yr of notional**, measured over 89 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

## Account 2 (***128)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-06 | 20 | 40.0 | 1.71 | +399,529 | -233,301 | +166,228 | 0 | 907,239 |
| 2026-07 | 16 | 25.0 | 0.12 | +10,837 | -90,700 | -79,863 | 0 | 827,376 |
| 2026-08 | 24 | 12.5 | 0.16 | +6,643 | -41,720 | -35,077 | 0 | 792,299 |
| 2026-09 | 138 | 29.7 | 0.56 | +89,577 | -159,688 | -70,111 | 0 | 722,188 |
| 2026-10 | 255 | 19.2 | 0.45 | +121,483 | -272,696 | -151,213 | 0 | 570,975 |
| 2026-11 | 174 | 33.9 | 1.04 | +150,962 | -144,668 | +6,294 | 0 | 577,269 |
| **total** | **627** | **26.2** | | | | **-163,742** | | **577,269** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
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
| 2026-10 | macd | -151,213 | 255 |
| 2026-11 | macd | +6,294 | 174 |

How trades ended:

| exit | trades |
|---|---:|
| the strategy's own exit | 348 |
| stop loss | 271 |
| closed by hand | 7 |
| take profit | 1 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| macd | 12 | 41.50 | +20,133 | -602 | 911,053 |

Financing: **-133/day** → **-48,412/yr**, **-5.7%/yr of notional**, measured over 11 position(s) held at least a day. 1 position(s) are too new to count. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

**This rate is provisional** — roughly **±28%** at this age. The book is 7.1 day(s) old, and swap is not charged evenly: the weekend is billed on a single night at triple rate, so the charge arrives in weekly lumps while the days it is divided by accrue daily. The reading therefore swings across the week — jumping on the triple night, decaying every day after — with the swing shrinking as roughly 1/days. It is worth reading as a number near 28 days, not before.

## Account 3 (***497)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-06 | 9 | 44.4 | 4.41 | +30,844 | -7,002 | +23,842 | +6,679 | 35,950 |
| 2026-07 | 3 | 0.0 | 0.00 | 0 | -7,474 | -7,474 | -122 | 28,354 |
| 2026-08 | 2 | 50.0 | 10.37 | +3,672 | -354 | +3,318 | -16,186 | 15,486 |
| 2026-09 | 63 | 46.0 | 0.98 | +83,112 | -84,677 | -1,565 | -15,921 | -2,000 |
| 2026-10 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | 0 | -2,000 |
| 2026-11 | 11 | 45.5 | 1.05 | +26,840 | -25,483 | +1,357 | +12,000 | 11,357 |
| **total** | **88** | **44.3** | | | | **+19,478** | | **11,357** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-06 | manual | +23,842 | 9 |
| 2026-07 | manual | -7,474 | 3 |
| 2026-08 | manual | +3,318 | 2 |
| 2026-09 | manual | -1,565 | 63 |
| 2026-11 | manual | +1,357 | 11 |

How trades ended:

| exit | trades |
|---|---:|
| closed by hand | 84 |
| stop loss | 4 |

## Account 4 (***565)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | +100,000 | 100,000 |
| 2026-09 | 94 | 40.4 | 0.84 | +9,916 | -11,860 | -1,944 | 0 | 98,056 |
| 2026-10 | 156 | 45.5 | 0.69 | +12,849 | -18,737 | -5,888 | 0 | 92,168 |
| 2026-11 | 120 | 45.0 | 0.99 | +14,618 | -14,818 | -200 | 0 | 91,968 |
| **total** | **370** | **44.1** | | | | **-8,032** | | **91,968** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-09 | bollrci | -1,944 | 94 |
| 2026-10 | bollrci | -5,888 | 156 |
| 2026-11 | bollrci | -200 | 120 |

How trades ended:

| exit | trades |
|---|---:|
| stop loss | 192 |
| the strategy's own exit | 174 |
| closed by hand | 4 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| bollrci | 20 | 19.70 | -21 | -2 | 188,031 |

Financing: **-1/day** → **-334/yr**, **-4.4%/yr of notional**, measured over 1 position(s) held at least a day. 19 position(s) are too new to count. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

**This rate is provisional** — roughly **±91%** at this age. The book is 2.2 day(s) old, and swap is not charged evenly: the weekend is billed on a single night at triple rate, so the charge arrives in weekly lumps while the days it is divided by accrue daily. The reading therefore swings across the week — jumping on the triple night, decaying every day after — with the swing shrinking as roughly 1/days. It is worth reading as a number near 28 days, not before.

## Account 5 (***010)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08 | 2 | 0.0 | 0.00 | 0 | -14,931 | -14,931 | +15,000 | -75 |
| 2026-09 | 11 | 36.4 | 0.10 | +9,092 | -95,588 | -86,496 | +87,567 | 996 |
| 2026-10 | 8 | 12.5 | 0.15 | +3,320 | -21,961 | -18,641 | +17,645 | 0 |
| **total** | **21** | **23.8** | | | | **-120,068** | | **0** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-08 | manual | -14,931 | 2 |
| 2026-09 | manual | -86,496 | 11 |
| 2026-10 | manual | -18,641 | 8 |

How trades ended:

| exit | trades |
|---|---:|
| stop loss | 12 |
| closed by hand | 7 |
| **margin stop-out** | 2 |

**2 position(s) were closed by the broker for margin, not by a decision.** A stop-out means the account ran out of cover while the positions were still open — the size was the problem, whatever the trades were doing.

