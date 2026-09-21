# Monthly operating statistics

Generated 2026-09-22 06:30 JST from live MT5 account history (`scripts/monthly_report.py --markdown`).

One closed **position** counts as one trade (partial closes collapse) and its PnL includes commission and swap on every deal of the position. Months are JST calendar months; a month with no trades is shown as a zero row. Deposits and withdrawals are reported separately from trading PnL, so a funded month cannot read as a winning one. All amounts in JPY.

## Summary

| account | months | trades | win % | PF | net PnL |
|---|---:|---:|---:|---:|---:|
| 1 (***431) | 5 | 193 | 24.9 | 0.71 | -291,381 |
| 2 (***128) | 5 | 164 | 23.2 | 0.87 | -89,462 |
| 3 (***497) | 6 | 73 | 45.2 | 1.05 | +5,547 |
| 4 (***565) | 2 | 77 | 36.4 | 0.63 | -4,002 |
| 5 (***010) | 2 | 7 | 28.6 | 0.07 | -42,435 |

## Account 1 (***431)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 27 | 25.9 | 0.64 | +226,560 | -353,534 | -126,974 | +990,000 | 863,026 |
| 2026-06 | 31 | 41.9 | 1.41 | +395,459 | -281,454 | +114,005 | 0 | 977,031 |
| 2026-07 | 21 | 14.3 | 0.11 | +20,346 | -180,028 | -159,682 | 0 | 817,349 |
| 2026-08 | 12 | 25.0 | 0.62 | +13,465 | -21,869 | -8,404 | 0 | 808,945 |
| 2026-09 | 102 | 21.6 | 0.29 | +44,461 | -154,787 | -110,326 | 0 | 698,619 |
| **total** | **193** | **24.9** | | | | **-291,381** | | **698,619** |

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
| 2026-09 | macd | -91,730 | 99 |
| 2026-09 | unknown | -18,596 | 3 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| macd | 5 | 16.60 | +8,118 | -1,051 | 4,153 |
| unknown | 1 | 3.20 | +25,922 | +683 | 1,206 |

Financing: **-79/day** → **-28,769/yr**, **-536.8%/yr of notional**, measured over 6 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

## Account 2 (***128)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 14 | 28.6 | 0.67 | +122,356 | -181,345 | -58,989 | +800,000 | 741,011 |
| 2026-06 | 20 | 40.0 | 1.71 | +399,529 | -233,301 | +166,228 | 0 | 907,239 |
| 2026-07 | 16 | 25.0 | 0.12 | +10,837 | -90,700 | -79,863 | 0 | 827,376 |
| 2026-08 | 24 | 12.5 | 0.16 | +6,643 | -41,720 | -35,077 | 0 | 792,299 |
| 2026-09 | 90 | 21.1 | 0.34 | +42,595 | -124,356 | -81,761 | 0 | 710,538 |
| **total** | **164** | **23.2** | | | | **-89,462** | | **710,538** |

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
| 2026-09 | macd | -83,814 | 87 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| fibonacci | 1 | 4.70 | -1,971 | -284 | 412 |
| macd | 5 | 16.00 | +7,678 | -990 | 3,917 |
| unknown | 2 | 13.10 | +9,338 | -1,969 | 1,576 |

Financing: **-138/day** → **-50,384/yr**, **-853.4%/yr of notional**, measured over 8 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

## Account 3 (***497)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-04 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | -104 | -1,805 |
| 2026-05 | 3 | 33.3 | 0.31 | +5,166 | -16,454 | -11,288 | +11,032 | -2,061 |
| 2026-06 | 9 | 44.4 | 4.41 | +30,844 | -7,002 | +23,842 | +6,679 | 28,460 |
| 2026-07 | 3 | 0.0 | 0.00 | 0 | -7,474 | -7,474 | -122 | 20,864 |
| 2026-08 | 2 | 50.0 | 10.37 | +3,672 | -354 | +3,318 | -16,186 | 7,996 |
| 2026-09 | 56 | 48.2 | 0.97 | +80,757 | -83,608 | -2,851 | +11,643 | 16,788 |
| **total** | **73** | **45.2** | | | | **+5,547** | | **16,788** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-05 | manual | -11,288 | 3 |
| 2026-06 | manual | +23,842 | 9 |
| 2026-07 | manual | -7,474 | 3 |
| 2026-08 | manual | +3,318 | 2 |
| 2026-09 | manual | -2,851 | 56 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| manual | 4 | 11.22 | +575 | -159 | 5,734 |

Financing cost is not measurable yet: all 4 open position(s) are younger than one rollover, so none has been charged swap.

## Account 4 (***565)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | +100,000 | 100,000 |
| 2026-09 | 77 | 36.4 | 0.63 | +6,738 | -10,740 | -4,002 | 0 | 95,998 |
| **total** | **77** | **36.4** | | | | **-4,002** | | **95,998** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-09 | bollrci | -4,002 | 77 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| bollrci | 4 | 2.80 | +1,638 | +13 | 380 |

Financing: **+2/day** → **+832/yr**, **+218.8%/yr of notional**, measured over 4 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

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
| manual | 5 | 3.03 | +23,698 | -2,291 | 212,685 |

Financing: **-290/day** → **-105,955/yr**, **-50.9%/yr of notional**, measured over 4 position(s) held at least a day. 1 position(s) are too new to count. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

