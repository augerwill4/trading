# 8 EMA Cloud (TradingView / Pine v6)

A clouded 8 EMA instead of a single line. The band is filled between the **8 EMA**
and the **9 EMA**, and can be padded so it has real surface area on the chart. By
default the padding hangs **downward only** — the top edge sits on the raw EMA and
the cloud thickens through the middle and bottom.

File: [`8ema-cloud.pine`](8ema-cloud.pine)

## Install

1. TradingView → **Pine Editor** (bottom panel) → **Open → New indicator**.
2. Delete the template, paste the contents of `8ema-cloud.pine`.
3. **Save**, then **Add to chart**.

## Why the padding option

The 8 and 9 EMA are one period apart, so the raw fill between them is a hairline —
technically a cloud, visually a thick line. **Expand cloud by** widens the band
symmetrically around that 8/9 ribbon so it reads as a zone:

| Setting | What it does | Good for |
| --- | --- | --- |
| `ATR` (default) | Pads by `ATR(14) × 0.25` | Scales itself across tickers and timeframes — set once, works everywhere |
| `Percent` | Pads by a fixed % of price (default 0.10%) | When you want the same relative width regardless of volatility |
| `None` | Pure 8/9 fill, no padding | The literal 8/9 ribbon |

**Expand direction** controls which side gets the padding:

- `Down only` (default) — top edge = the raw 8/9 EMA, all padding below it. Price
  crossing the top of the cloud is a clean EMA cross; the thick underside acts as
  the support zone / pullback area.
- `Both` — symmetric band around the 8/9 pair.
- `Up only` — mirror image, thick on top.

Padding never moves the EMAs. It only sets how far price has to travel past the
8/9 pair before it is "outside" the cloud on the padded side. Bigger multiple =
wider zone, fewer breaks below it.

## Settings

- **Source / Fast EMA / Slow EMA** — defaults `close` / 8 / 9.
- **Cloud timeframe** — blank uses the chart. Set `15` to overlay the 15m 8EMA
  cloud on a 1m chart (non-repainting: `lookahead_off`, so the higher-timeframe
  value only updates when that candle closes).
- **Style** — bull/bear colors, cloud and edge transparency, optionally show the
  raw 8/9 lines on top of the fill, optionally color candles with the cloud.

Cloud is green while the 8 is above the 9, red while it is below.

## Alerts

Add via the alert dialog → condition = *8 EMA Cloud*:

- **Cloud turns bullish** — 8 crosses above 9
- **Cloud turns bearish** — 8 crosses below 9
- **Price above cloud** — close crosses above the cloud top (with `Down only`,
  that is the raw 8/9 EMA itself)
- **Price below cloud** — close crosses below the cloud bottom, i.e. all the way
  through the padded zone
