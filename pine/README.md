# 8 EMA Cloud (TradingView / Pine v6)

A clouded 8 EMA instead of a single line. The band is filled between the **8 EMA**
and the **9 EMA**, and can be padded so it has real surface area on the chart.

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

Padding does not move the EMAs — the midline of the cloud is still the 8/9 pair.
It only sets how much room price has to be "inside" the cloud before the
above/below alerts fire. Bigger multiple = stricter filter, fewer signals.

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
- **Price above cloud** — close crosses above the cloud top
- **Price below cloud** — close crosses below the cloud bottom
