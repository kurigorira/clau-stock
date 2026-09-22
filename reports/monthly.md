# Monthly operating statistics

Generated 2026-09-23 06:30 JST from live MT5 account history (`scripts/monthly_report.py --markdown`).

One closed **position** counts as one trade (partial closes collapse) and its PnL includes commission and swap on every deal of the position. Months are JST calendar months; a month with no trades is shown as a zero row. Deposits and withdrawals are reported separately from trading PnL, so a funded month cannot read as a winning one. All amounts in JPY.

## Summary

| account | months | trades | win % | PF | net PnL |
|---|---:|---:|---:|---:|---:|
| 1 (***431) | 5 | 211 | 26.1 | 0.73 | -268,744 |
| 2 (***128) | 5 | 172 | 25.0 | 0.89 | -76,273 |
| 3 (***497) | 6 | 77 | 45.5 | 1.06 | +7,152 |
| 4 (***565) | 2 | 81 | 38.3 | 0.81 | -2,049 |
| 5 (***010) | 2 | 7 | 28.6 | 0.07 | -42,435 |

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
| 2026-07 | donchian | -31,863 | 7 |
| 2026-07 | fibonacci | -449 | 3 |
| 2026-07 | manual | -31,026 | 2 |
| 2026-07 | unknown | -15,615 | 4 |
| 2026-08 | donchian | +5,833 | 3 |
| 2026-08 | fibonacci | +1,695 | 4 |
| 2026-08 | unknown | -15,932 | 5 |
| 2026-09 | macd | -93,630 | 100 |
| 2026-09 | manual | +24,537 | 17 |
| 2026-09 | unknown | -18,596 | 3 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| buyhold | 89 | 52.40 | -663 | -89 | 617,159 |

Financing cost is not measurable yet: all 89 open position(s) are younger than one rollover, so none has been charged swap.

## Account 2 (***128)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 14 | 28.6 | 0.67 | +122,356 | -181,345 | -58,989 | +800,000 | 741,011 |
| 2026-06 | 20 | 40.0 | 1.71 | +399,529 | -233,301 | +166,228 | 0 | 907,239 |
| 2026-07 | 16 | 25.0 | 0.12 | +10,837 | -90,700 | -79,863 | 0 | 827,376 |
| 2026-08 | 24 | 12.5 | 0.16 | +6,643 | -41,720 | -35,077 | 0 | 792,299 |
| 2026-09 | 98 | 24.5 | 0.47 | +59,674 | -128,246 | -68,572 | 0 | 723,727 |
| **total** | **172** | **25.0** | | | | **-76,273** | | **723,727** |

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
| 2026-09 | fibonacci | +4,509 | 2 |
| 2026-09 | macd | -85,644 | 88 |
| 2026-09 | manual | +15,019 | 7 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| macd | 3 | 21.00 | +475 | -8 | 410,132 |

Financing cost is not measurable yet: all 3 open position(s) are younger than one rollover, so none has been charged swap.

## Account 3 (***497)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-04 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | -104 | -1,805 |
| 2026-05 | 3 | 33.3 | 0.31 | +5,166 | -16,454 | -11,288 | +11,032 | -2,061 |
| 2026-06 | 9 | 44.4 | 4.41 | +30,844 | -7,002 | +23,842 | +6,679 | 28,460 |
| 2026-07 | 3 | 0.0 | 0.00 | 0 | -7,474 | -7,474 | -122 | 20,864 |
| 2026-08 | 2 | 50.0 | 10.37 | +3,672 | -354 | +3,318 | -16,186 | 7,996 |
| 2026-09 | 60 | 48.3 | 0.99 | +83,112 | -84,358 | -1,246 | +11,643 | 18,393 |
| **total** | **77** | **45.5** | | | | **+7,152** | | **18,393** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-05 | manual | -11,288 | 3 |
| 2026-06 | manual | +23,842 | 9 |
| 2026-07 | manual | -7,474 | 3 |
| 2026-08 | manual | +3,318 | 2 |
| 2026-09 | manual | -1,246 | 60 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| manual | 1 | 2.00 | -236 | -28 | 48,482 |

Financing cost is not measurable yet: all 1 open position(s) are younger than one rollover, so none has been charged swap.

## Account 4 (***565)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | +100,000 | 100,000 |
| 2026-09 | 81 | 38.3 | 0.81 | +8,756 | -10,805 | -2,049 | 0 | 97,951 |
| **total** | **81** | **38.3** | | | | **-2,049** | | **97,951** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-09 | bollrci | -4,002 | 77 |
| 2026-09 | manual | +1,953 | 4 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| bollrci | 1 | 2.20 | -90 | -3 | 16,018 |

Financing cost is not measurable yet: all 1 open position(s) are younger than one rollover, so none has been charged swap.

## Account 5 (***010)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08 | 2 | 0.0 | 0.00 | 0 | -14,931 | -14,931 | +15,000 | -7,931 |
| 2026-09 | 5 | 40.0 | 0.10 | +3,103 | -30,607 | -27,504 | +48,003 | 12,568 |
| **total** | **7** | **28.6** | | | | **-42,435** | | **12,568** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-08 | manual | -14,931 | 2 |
| 2026-09 | manual | -27,504 | 5 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| manual | 5 | 3.03 | +31,843 | -2,684 | 2,258,974 |

Financing: **-507/day** → **-184,933/yr**, **-8.2%/yr of notional**, measured over 5 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

