# gex-lab

Dealer gamma exposure from an option chain: net GEX, the gamma flip, the call
and put walls, and a levels block you paste into TradingView.

Pure standard library. No numpy, no pandas, no install step, no API key.

```
cd gex-lab
python3 -m gexlab --csv data/sample-spy-chain.csv     # offline demo chain
python3 -m gexlab SPY --max-dte 7                     # Cboe delayed quotes
python3 -m unittest discover -s tests -t .            # 22 tests
```

---

## What GEX actually measures

It is not sentiment and it is not a positioning survey. It is one mechanical
consequence of options dealers hedging their books.

A dealer who sells you a call is short that call. To stay delta-neutral they buy
shares. As price rises the call's delta rises, so they have to buy more shares;
as price falls they sell. Their hedging pushes in the same direction as the move.
That is **short gamma**, and it amplifies whatever the tape is already doing.

Flip the sign. A dealer who is **long gamma** hedges against the move — selling
into strength, buying into weakness — which compresses ranges and pins price.

Gamma is the rate at which that hedge requirement changes. GEX aggregates it
across every strike so you get one number: how many dollars of stock dealers
have to trade for a 1% move, and in which direction.

| Net GEX | Dealer hedging | What the tape usually does |
| --- | --- | --- |
| Positive | against the move | ranges compress, moves fade, levels pin |
| Negative | with the move | ranges expand, moves extend, gaps run |

This is the whole reason the number is worth computing. It does not tell you
direction. It tells you **which playbook is live** — fade or follow.

---

## The math

Black-Scholes gamma, per share:

```
gamma = e^(-qT) * phi(d1) / (S * sigma * sqrt(T))
d1    = [ ln(S/K) + (r - q + sigma^2/2) T ] / (sigma * sqrt(T))
```

Gamma is identical for a call and a put at the same strike and expiry — put-call
parity is linear in spot, so its second derivative is zero. That identity is
tested in `tests/test_blackscholes.py` and it is what lets the chain be bucketed
by strike without tracking which side the gamma came from.

Scale it to a dollar figure per contract:

```
GEX = gamma * OI * 100 * S^2 * 0.01
```

Reading the terms right to left, because this is where most write-ups wave their
hands:

- `0.01 * S` — a 1% move in dollars.
- `gamma * (0.01 * S)` — the change in delta, in shares per share, over that move.
- `* 100` — contract multiplier, so now it is shares per contract.
- `* OI` — every open contract at that strike.
- `* S` — shares priced into dollars.

Multiply it out and the two spot terms collapse into `S^2 * 0.01`. The unit is
**dollars of stock dealers must trade per 1% move**. Reported in billions.

### The sign convention, and why it is the weak link

Open interest does not say who is long and who is short. The convention this
lab uses by default — and the one every public GEX number you have seen uses —
is that dealers are **long call open interest and short put open interest**,
because customers buy puts for protection and sell calls for yield.

```
call GEX = +gamma * OI * 100 * S^2 * 0.01
put  GEX = -gamma * OI * 100 * S^2 * 0.01
```

It is an assumption, not data. It is roughly right on index products, where the
structural bid for downside protection is real and persistent. It is much
shakier on a single name after a retail call-buying frenzy, where dealers are
short the calls, not long them — and the sign of your entire number is wrong.

`--convention all_long` and `--convention all_short` are there so you can see
how far the answer moves under the opposite assumption. If the flip barely
budges, the level is robust. If it swings across spot, you are reading noise.

---

## The three levels

**Gamma flip** — the spot price where net GEX crosses zero. Above it dealers
dampen, below it they amplify. It is found by recomputing total GEX at a grid of
hypothetical spot prices (`gamma_profile`), not by interpolating the strike
ladder, because gamma itself moves with spot and the two curves are not the same
shape. Open interest, implied vol and time are held fixed — it answers "if price
were there right now," not "where will this be tomorrow."

**Call wall** — the strike above spot carrying the most positive call gamma.
Rallies into it tend to stall, because dealer hedging gets heaviest exactly
there.

**Put wall** — the strike below spot carrying the most negative put gamma. The
mirror image: selloffs tend to find a shelf.

Walls are gravity, not brick. When they break they usually break hard, because
the hedging flow that was absorbing the move stops absorbing it.

---

## Using it

Once a morning, before the open. Open interest only updates overnight, so
running this intraday mostly re-tells you what you already know.

```
python3 -m gexlab SPY --max-dte 7 --out-dir out/
```

The report prints a levels block:

```
// SPY GEX levels — 2026-03-02 18:30 UTC (synthetic-demo)
// spot 585.40   net GEX -3.356 Bn per 1%
Gamma flip      = 591.95
Call wall       = 590.00
Put wall        = 575.00
Extra level 1   = 580.00   // 1.742 Bn gamma
```

Type those into [`pine/gex-levels.pine`](pine/gex-levels.pine) on TradingView —
Pine Editor, New indicator, paste, Save, Add to chart, then fill the settings.
TradingView has no option chain, so the indicator cannot compute any of this
itself; it draws what you give it and tints the background by which side of the
flip price is on.

`--out-dir` also writes `strikes.csv` (GEX by strike — chart it anywhere),
`profile.csv` (the GEX-vs-spot curve, where the flip is the x-intercept) and
`levels.txt`.

`--save-chain data/spy-2026-03-02.csv` stores the raw chain. Do that daily and
you have a positioning history to test against, which is worth more than any
single day's snapshot.

### How the levels change the plan, concretely

| Regime | Bias |
| --- | --- |
| Price above flip, net GEX positive | fade extremes, expect the call wall to hold, size down on breakouts, mean reversion into the 8/9 cloud works |
| Price below flip, net GEX negative | follow momentum, expect ranges to expand, trail wider, breakout continuation works and fades get run over |
| Price pinned between the walls with big positive GEX | the chop day — smallest size, or no trade |

That maps onto the EMA-cloud setup in [`../pine`](../pine): the entry trigger is
the same, what changes is whether you trust the pullback to reverse or expect it
to keep going.

---

## Where this is wrong

Read this part. It is the difference between a tool and a crutch.

1. **The dealer sign is assumed.** Covered above. It is the single biggest
   source of error and there is no free data that fixes it.
2. **Open interest is stale.** It settles overnight. Every 0DTE contract that
   opened and closed today is invisible, and on SPX that is most of the volume.
   Same-day flow is a real gap in this number.
3. **The IV surface is one snapshot.** Gamma is repriced across hypothetical
   spot with volatility frozen. In reality vol rises as price falls, which moves
   the true flip lower than the model says.
4. **Cboe quotes are ~15 minutes delayed.** Irrelevant for open interest,
   relevant for the spot price the profile is centered on. Pass `--spot` to
   override it with a live print.
5. **Calendar days, not trading days.** `T` uses 365-day years and a 16:00 New
   York settle. Over a long weekend this slightly overstates time to expiry on
   the front contracts.
6. **It is a level, not a signal.** GEX tells you the character of the tape. It
   does not tell you direction, and nothing in this repo takes a trade.

---

## Files

| File | What it does |
| --- | --- |
| `gexlab/blackscholes.py` | gamma, price, bisection implied vol — no dependencies |
| `gexlab/chain.py` | `OptionQuote` / `Chain`, OCC symbol parsing, CSV round-trip |
| `gexlab/providers.py` | Cboe delayed JSON and CSV loaders |
| `gexlab/gex.py` | per-contract and per-strike GEX, the spot profile, flip and walls |
| `gexlab/report.py` | terminal report with ASCII bars, CSV exports, the levels block |
| `gexlab/cli.py` | `python3 -m gexlab` |
| `pine/gex-levels.pine` | TradingView indicator that draws the levels |
| `data/sample-spy-chain.csv` | synthetic demo chain, timestamp pinned so output is deterministic |
| `tests/` | 22 stdlib unittest cases |

### CLI

| Flag | Meaning |
| --- | --- |
| `symbol` | underlying to pull from Cboe (`SPY`, `SPX`, `QQQ`, …) |
| `--csv PATH` | read a saved chain instead of the network |
| `--spot PRICE` | override the underlying price |
| `--max-dte N` | only expiries within N calendar days |
| `--expiry YYYY-MM-DD` | a single expiry |
| `--min-oi N` | drop thin strikes (default 1) |
| `-r` / `-q` | risk-free rate and dividend yield (defaults 0.04 / 0.01) |
| `--convention` | `long_calls_short_puts` (default), `all_long`, `all_short` |
| `--range-pct` / `--steps` | width and resolution of the spot profile |
| `--top N` / `--no-bars` | size and style of the strike ladder |
| `--out-dir DIR` | write `strikes.csv`, `profile.csv`, `levels.txt` |
| `--save-chain PATH` | snapshot the raw chain for later |

### Data sources

**Cboe delayed quotes** is the default because it is free, needs no key, covers
index products including SPX, and carries open interest and IV for the full
chain. `https://cdn.cboe.com/api/global/delayed_quotes/options/SPY.json`.

Anything live costs money — Tradier, Polygon, or your broker's API. Adding one
means writing a function that returns a `Chain`; nothing else in the lab
changes. That is the only reason `providers.py` exists as its own module.

> The demo chain in `data/` is synthetic. Its *shape* is realistic — downside
> skew, open-interest humps on round strikes, protection demand below spot — but
> the numbers are not a real session and the levels it produces are not
> tradeable. It is there so the tests and the demo run with no network.
