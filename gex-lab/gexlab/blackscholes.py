"""Black-Scholes pieces needed for gamma exposure.

Stdlib only — no numpy, no scipy. Everything here is per-share, per-contract
scaling happens in gex.py.
"""

from __future__ import annotations

import math

SQRT_2PI = math.sqrt(2.0 * math.pi)


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def d1(spot: float, strike: float, t: float, vol: float, r: float, q: float) -> float:
    return (math.log(spot / strike) + (r - q + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))


def gamma(spot: float, strike: float, t: float, vol: float, r: float = 0.0, q: float = 0.0) -> float:
    """Second derivative of option value w.r.t. spot, per share.

    Identical for a call and a put at the same strike and expiry — that identity
    is what lets the chain be aggregated strike by strike without tracking which
    side the gamma came from.
    """
    if spot <= 0.0 or strike <= 0.0 or t <= 0.0 or vol <= 0.0:
        return 0.0
    return math.exp(-q * t) * norm_pdf(d1(spot, strike, t, vol, r, q)) / (spot * vol * math.sqrt(t))


def price(right: str, spot: float, strike: float, t: float, vol: float, r: float = 0.0, q: float = 0.0) -> float:
    """European option value. Used only by the implied-vol solver."""
    is_call = right.upper().startswith("C")
    if t <= 0.0 or vol <= 0.0:
        intrinsic = spot - strike if is_call else strike - spot
        return max(intrinsic, 0.0)
    a = d1(spot, strike, t, vol, r, q)
    b = a - vol * math.sqrt(t)
    df_r, df_q = math.exp(-r * t), math.exp(-q * t)
    if is_call:
        return spot * df_q * norm_cdf(a) - strike * df_r * norm_cdf(b)
    return strike * df_r * norm_cdf(-b) - spot * df_q * norm_cdf(-a)


def implied_vol(
    target: float,
    right: str,
    spot: float,
    strike: float,
    t: float,
    r: float = 0.0,
    q: float = 0.0,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float | None:
    """Bisection solve for vol. Returns None when the price is unsolvable.

    Bisection rather than Newton: vega collapses on deep OTM contracts, which is
    exactly where a stale chain puts its worst prints, and Newton diverges there.
    Bisection just fails to bracket and returns None, which is the honest answer.
    """
    if t <= 0.0 or target is None or target <= 0.0:
        return None
    intrinsic = max(spot - strike, 0.0) if right.upper().startswith("C") else max(strike - spot, 0.0)
    if target < intrinsic * math.exp(-r * t) - tol:
        return None
    f_lo = price(right, spot, strike, t, lo, r, q) - target
    f_hi = price(right, spot, strike, t, hi, r, q) - target
    if f_lo * f_hi > 0.0:
        return None
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        f_mid = price(right, spot, strike, t, mid, r, q) - target
        if abs(f_mid) < tol or (hi - lo) < tol:
            return mid
        if f_lo * f_mid <= 0.0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return 0.5 * (lo + hi)
