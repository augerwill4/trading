# EMA Cloud Setup (TradingView / Pine v6)

Two indicators that together produce the chart layout in the reference
screenshots: a stack of EMA clouds on price, session levels, entry marks and a
trailing stop.

| File | What it draws |
| --- | --- |
| [`8ema-cloud.pine`](8ema-cloud.pine) | The EMA cloud stack |
| [`levels-and-trade.pine`](levels-and-trade.pine) | PMH / PML / PDH / PDL lines, `(E)` entries, dotted trailing stop |

## Install

For each file: TradingView → **Pine Editor** → **Open → New indicator**, delete
the template, paste the file, **Save**, **Add to chart**. Add both to the same
chart.

The shaded off-hours columns in the screenshots are not part of either script —
that is the chart's own setting: right-click the price scale → **Settings →
Symbol → Extended trading hours**.

---

## 1. 8 EMA Cloud System

Each cloud is the filled band between two EMAs, so its thickness *is* the real
spread between them. Defaults, slowest painted first so the fast clouds sit on
top:

| Cloud | Pair | Color | Role |
| --- | --- | --- | --- |
| 1 | 8 / 9 | **green up, red down** | the fast cloud price rides |
| 2 | 5 / 12 | purple | trigger cloud |
| 3 | 20 / 21 | amber *(off)* | optional |
| 4 | 34 / 50 | navy | mid-term trend band |
| 5 | 72 / 89 | dark green | long-term trend band |
| 6 | 180 / 200 | gray *(off)* | optional |

Only cloud 1 changes color with trend by default — that is what makes the fast
cloud flip green→red on the downside example while the purple stays purple. Any
cloud can be made trend-colored by setting different Up and Down colors, or held
fixed by setting them the same.

This structure is what you were describing earlier: in an uptrend the clouds
stack *under* price as layered support, and in a downtrend they sit *above* it as
resistance. It happens naturally from EMA separation, so the artificial padding
is now **off by default**. It is still there under **8/9 extra thickness** if you
want the 8/9 band itself fatter than the true spread — `ATR` or `Percent` sizing,
with the `Auto (trend)` direction that pads below in an uptrend and above in a
downtrend.

Other settings: source, **Cloud timeframe** (blank = chart; set `30` to carry the
30m clouds onto a 10m chart, non-repainting), raw 8/9 lines, bar coloring.

**Alerts:** 8/9 cross either way, price closing above/below the 8/9 cloud, and
the 8/9 cloud crossing above/below the 34/50 trend cloud.

---

## 2. Session Levels & Trade Markers

### Levels

- **PMH / PML** — premarket high and low, tracked over the `0400-0930` session in
  `America/New_York` (both configurable). Dotted, green and red.
- **PDH / PDL** — previous day's high and low. Solid.

Each is drawn from the start of the current day and extends past the last bar by
**Extend levels right (bars)** with its tag at the end. Only the current day's set
is drawn, so the chart stays clean.

### Entries and stop

The `(E)` marker fires on a **pullback into the cloud that closes back out of it,
with the trend**:

- **Long** — 8 above 9, the bar dips into the 8/9 cloud (`low ≤ cloud top`), and
  closes green above it.
- **Short** — the mirror image.
- **Only trade with the trend cloud** (on by default) additionally requires the
  8/9 cloud to be above the 34/50 cloud for longs, below it for shorts.

The dotted red line is a **trailing stop**, not a fixed one. It starts just beyond
the entry bar's swing (`buffer = 0.25 × ATR(14)`), then ratchets: for a long it
rises to `cloud bottom − buffer` and never falls back, so it traces up under the
rally and prints `SL: 727.98` at its current level. A close through it ends the
trade and the line stops.

Widen **Stop buffer** for more room and fewer stop-outs, tighten it to trail
closer to the cloud.

**Alerts:** long/short entry, long/short stopped out.

> The entry rule is my reading of the marks in the reference charts — a pullback
> into the 8/9 cloud continuing with the trend. If your actual trigger differs
> (a break of PMH/PDH, a specific candle pattern, a volume condition), say so and
> I will change the rule; everything else stays as is.
