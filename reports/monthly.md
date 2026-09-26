# Monthly operating statistics

Generated 2026-09-27 06:30 JST from live MT5 account history (`scripts/monthly_report.py --markdown`).

One closed **position** counts as one trade (partial closes collapse) and its PnL includes commission and swap on every deal of the position. Months are JST calendar months; a month with no trades is shown as a zero row. Deposits and withdrawals are reported separately from trading PnL, so a funded month cannot read as a winning one. All amounts in JPY.

## Summary

| account | months | trades | win % | PF | net PnL |
|---|---:|---:|---:|---:|---:|
| 1 (***431) | 5 | 211 | 26.1 | 0.73 | -268,744 |
| 2 (***128) | 5 | 194 | 25.8 | 0.88 | -84,448 |
| 3 (***497) | 6 | 80 | 43.8 | 1.06 | +6,833 |
| 4 (***565) | 2 | 86 | 38.4 | 0.80 | -2,328 |
| 5 (***010) | 2 | 9 | 22.2 | 0.05 | -63,343 |

## Cost of carry

What each open book costs to **keep** open. None of this is in the tables above: financing is charged whether or not anything is closed, and it is charged on the notional, not on the account. The last column is what matters for survival — at leverage, a rate the broker would call ordinary becomes a multiple of the account per year.

| account | notional | equity | leverage | financing/yr | as % of equity |
|---|---:|---:|---:|---:|---:|
| 1 | 613,314 | 716,643 | 0.9x | -53,093 * | -7.4% * |
| 2 | 1,715,813 | 726,738 | 2.4x | -70,245 * | -9.7% * |
| 4 | 113,068 | 97,512 | 1.2x | -2,120 * | -2.2% * |
| 5 | 1,548,290 | 14,891 | 104.0x | -110,818 | -744.2% |

\* **Provisional.** Swap is not charged evenly — the weekend is billed on a single night at triple rate, so five charged nights carry seven days of financing. A book held less than a week, especially across that night, reads too expensive. These settle once whole weeks accumulate.

**Account 5: financing alone exceeds the whole account every year.** That is arithmetic on the open book, not a forecast about prices — it is charged even if the market never moves.

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

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| buyhold | 89 | 52.40 | -4,613 | -580 | 613,314 |

Financing: **-145/day** → **-53,093/yr**, **-8.7%/yr of notional**, measured over 89 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

**This rate is provisional** — the book is 4.0 day(s) old. Swap is not charged evenly: the weekend is billed on a single night at triple rate, so five charged nights carry seven days of financing. Measured over less than a week, and especially across that night, the daily rate reads too expensive. It settles once whole weeks accumulate.

## Account 2 (***128)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-05 | 14 | 28.6 | 0.67 | +122,356 | -181,345 | -58,989 | +800,000 | 741,011 |
| 2026-06 | 20 | 40.0 | 1.71 | +399,529 | -233,301 | +166,228 | 0 | 907,239 |
| 2026-07 | 16 | 25.0 | 0.12 | +10,837 | -90,700 | -79,863 | 0 | 827,376 |
| 2026-08 | 24 | 12.5 | 0.16 | +6,643 | -41,720 | -35,077 | 0 | 792,299 |
| 2026-09 | 120 | 25.8 | 0.49 | +73,549 | -150,296 | -76,747 | 0 | 715,552 |
| **total** | **194** | **25.8** | | | | **-84,448** | | **715,552** |

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
| 2026-09 | macd | -88,312 | 114 |
| 2026-09 | unknown | +11,033 | 2 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| macd | 16 | 136.80 | +11,186 | -393 | 1,715,813 |

Financing: **-192/day** → **-70,245/yr**, **-4.1%/yr of notional**, measured over 16 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

**This rate is provisional** — the book is 4.0 day(s) old. Swap is not charged evenly: the weekend is billed on a single night at triple rate, so five charged nights carry seven days of financing. Measured over less than a week, and especially across that night, the daily rate reads too expensive. It settles once whole weeks accumulate.

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

## Account 4 (***565)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08 | 0 | 0.0 | 0.00 | 0 | 0 | 0 | +100,000 | 100,000 |
| 2026-09 | 86 | 38.4 | 0.80 | +9,066 | -11,394 | -2,328 | 0 | 97,672 |
| **total** | **86** | **38.4** | | | | **-2,328** | | **97,672** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-09 | bollrci | -2,328 | 86 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| bollrci | 8 | 6.40 | -160 | -7 | 113,068 |

Financing: **-6/day** → **-2,120/yr**, **-1.9%/yr of notional**, measured over 8 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

**This rate is provisional** — the book is 2.1 day(s) old. Swap is not charged evenly: the weekend is billed on a single night at triple rate, so five charged nights carry seven days of financing. Measured over less than a week, and especially across that night, the daily rate reads too expensive. It settles once whole weeks accumulate.

## Account 5 (***010)

| month | trades | win % | PF | gross + | gross - | net | in/out | end balance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08 | 2 | 0.0 | 0.00 | 0 | -14,931 | -14,931 | +15,000 | -17,421 |
| 2026-09 | 7 | 28.6 | 0.06 | +3,103 | -51,515 | -48,412 | +75,567 | 9,734 |
| **total** | **9** | **22.2** | | | | **-63,343** | | **9,734** |

By strategy:

| month | strategy | net | trades |
|---|---|---:|---:|
| 2026-08 | manual | -14,931 | 2 |
| 2026-09 | manual | -48,412 | 7 |

Open positions — **not** counted in the tables above, because nothing has been realized yet:

| strategy | positions | volume | unrealised | of which swap | notional |
|---|---:|---:|---:|---:|---:|
| manual | 4 | 3.02 | +5,157 | -3,783 | 1,548,290 |

Financing: **-304/day** → **-110,818/yr**, **-7.2%/yr of notional**, measured over 4 position(s) held at least a day. A CFD pays this every night the position is held; a cash share or an ETF pays none of it.

