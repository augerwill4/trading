"""Gamma exposure: per-contract, per-strike, and the spot profile.

Units throughout: dollars of dealer delta that change hands per 1% move in the
underlying. That is the standard GEX unit and the reason for the `spot^2 * 0.01`
term — see the derivation in README.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from . import blackscholes as bs
from .chain import Chain, OptionQuote

CONTRACT_MULTIPLIER = 100.0

# How dealer inventory is assumed to sit against customer open interest.
#   "long_calls_short_puts" — the market convention (SqueezeMetrics). Customers
#       buy puts for protection and sell calls for yield, so dealers end up long
#       call OI and short put OI. Calls add gamma, puts subtract it.
#   "all_long" / "all_short" — sanity bounds, not trading assumptions.
SIGN_CONVENTIONS = {
    "long_calls_short_puts": (1.0, -1.0),
    "all_long": (1.0, 1.0),
    "all_short": (-1.0, -1.0),
}


@dataclass
class StrikeGex:
    strike: float
    call_gex: float = 0.0
    put_gex: float = 0.0
    call_oi: int = 0
    put_oi: int = 0

    @property
    def net_gex(self) -> float:
        return self.call_gex + self.put_gex

    @property
    def abs_gex(self) -> float:
        return abs(self.call_gex) + abs(self.put_gex)


def quote_vol(q: OptionQuote, spot: float, t: float, r: float, div: float) -> float | None:
    """Volatility for a contract: the feed's IV, else solved from the mid."""
    if q.implied_vol and q.implied_vol > 0.0:
        return q.implied_vol
    mid = q.mid
    if mid is None:
        return None
    return bs.implied_vol(mid, q.right, spot, q.strike, t, r, div)


def contract_gex(
    q: OptionQuote,
    spot: float,
    t: float,
    *,
    vol: float,
    r: float = 0.0,
    div: float = 0.0,
    convention: str = "long_calls_short_puts",
    multiplier: float = CONTRACT_MULTIPLIER,
) -> float:
    """Signed dollar gamma for one strike's open interest, per 1% spot move."""
    g = bs.gamma(spot, q.strike, t, vol, r, div)
    call_sign, put_sign = SIGN_CONVENTIONS[convention]
    sign = call_sign if q.is_call else put_sign
    return sign * g * q.open_interest * multiplier * spot * spot * 0.01


def by_strike(
    chain: Chain,
    *,
    spot: float | None = None,
    r: float = 0.0,
    div: float = 0.0,
    convention: str = "long_calls_short_puts",
    now: datetime | None = None,
    vol_floor: float = 0.01,
) -> list[StrikeGex]:
    """Aggregate the chain into per-strike exposure, sorted by strike.

    `spot` overrides the chain's spot for the price leg only. Implied vol is
    always taken at the *observed* spot, so repricing the profile does not
    silently re-solve the surface.
    """
    now = now or chain.as_of or datetime.now(timezone.utc)
    observed = chain.spot
    px = observed if spot is None else spot

    buckets: dict[float, StrikeGex] = {}
    for q in chain.quotes:
        t = q.years_to_expiry(now)
        if t <= 0.0 or q.open_interest <= 0:
            continue
        vol = quote_vol(q, observed, t, r, div)
        if vol is None or vol < vol_floor:
            continue
        value = contract_gex(q, px, t, vol=vol, r=r, div=div, convention=convention)
        b = buckets.setdefault(q.strike, StrikeGex(q.strike))
        if q.is_call:
            b.call_gex += value
            b.call_oi += q.open_interest
        else:
            b.put_gex += value
            b.put_oi += q.open_interest
    return sorted(buckets.values(), key=lambda b: b.strike)


def total_gex(chain: Chain, **kwargs) -> float:
    return sum(b.net_gex for b in by_strike(chain, **kwargs))


def gamma_profile(
    chain: Chain,
    *,
    range_pct: float = 0.10,
    steps: int = 81,
    **kwargs,
) -> list[tuple[float, float]]:
    """Total GEX recomputed across hypothetical spot prices.

    This is the honest way to find the flip: gamma itself moves with spot, so
    interpolating the strike ladder is not the same curve. Open interest, IV and
    time are held fixed — it answers "if price were there right now", not "where
    will this be tomorrow".
    """
    lo, hi = chain.spot * (1.0 - range_pct), chain.spot * (1.0 + range_pct)
    if steps < 2:
        raise ValueError("steps must be >= 2")
    out = []
    for i in range(steps):
        px = lo + (hi - lo) * i / (steps - 1)
        out.append((px, total_gex(chain, spot=px, **kwargs)))
    return out


def flip_point(profile: list[tuple[float, float]], reference: float | None = None) -> float | None:
    """Spot where total GEX crosses zero, linearly interpolated.

    Multiple crossings are common on a messy chain; the one nearest `reference`
    (normally current spot) is the one that matters for today's tape.
    """
    crossings = []
    for (x0, y0), (x1, y1) in zip(profile, profile[1:]):
        if y0 == 0.0:
            crossings.append(x0)
        elif y0 * y1 < 0.0:
            crossings.append(x0 + (x1 - x0) * (-y0) / (y1 - y0))
    if not crossings:
        return None
    if reference is None:
        return crossings[0]
    return min(crossings, key=lambda x: abs(x - reference))


def call_wall(strikes: list[StrikeGex], *, above: float | None = None) -> StrikeGex | None:
    """Strike carrying the most positive call gamma — the pin/resistance shelf."""
    pool = [s for s in strikes if above is None or s.strike >= above]
    pool = [s for s in pool if s.call_gex > 0.0]
    return max(pool, key=lambda s: s.call_gex) if pool else None


def put_wall(strikes: list[StrikeGex], *, below: float | None = None) -> StrikeGex | None:
    """Strike carrying the most negative put gamma — the support shelf."""
    pool = [s for s in strikes if below is None or s.strike <= below]
    pool = [s for s in pool if s.put_gex < 0.0]
    return min(pool, key=lambda s: s.put_gex) if pool else None


def top_strikes(strikes: list[StrikeGex], n: int = 10) -> list[StrikeGex]:
    return sorted(strikes, key=lambda s: s.abs_gex, reverse=True)[:n]
