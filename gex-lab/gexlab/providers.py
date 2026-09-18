"""Where chains come from.

Two providers, both stdlib:

  csv   — a file you saved earlier. Always works, offline, reproducible.
  cboe  — Cboe's free delayed-quote JSON. No API key, ~15 minutes stale, carries
          open interest and IV for the whole chain including SPX and index
          products. Delayed is fine for GEX: open interest only updates
          overnight anyway.

Live quotes need a paid feed (Tradier, Polygon, your broker). Add one as a
function returning a Chain and the rest of the lab does not change.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .chain import Chain, OptionQuote, load_csv, parse_occ

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
# Cboe files index products under a leading underscore.
INDEX_SYMBOLS = {"SPX", "SPXW", "NDX", "RUT", "VIX", "XSP", "DJX", "OEX"}
USER_AGENT = "gex-lab/1.0 (+https://github.com/augerwill4/trading)"


def from_csv(path: str | Path, *, symbol: str | None = None, spot: float | None = None) -> Chain:
    return load_csv(Path(path).read_text(), symbol=symbol, spot=spot)


def _cboe_ticker(symbol: str) -> str:
    s = symbol.strip().upper().lstrip("_^")
    return f"_{s}" if s in INDEX_SYMBOLS else s


def from_cboe(symbol: str, *, timeout: float = 20.0) -> Chain:
    url = CBOE_URL.format(symbol=_cboe_ticker(symbol))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise LookupError(
                f"Cboe has no delayed-quote file for {symbol!r} (tried {_cboe_ticker(symbol)})"
            ) from exc
        raise

    data = payload.get("data") or {}
    spot = data.get("current_price") or data.get("close")
    if not spot:
        raise ValueError(f"Cboe returned no price for {symbol!r}")

    quotes: list[OptionQuote] = []
    for row in data.get("options") or []:
        try:
            _, expiry, right, strike = parse_occ(row["option"])
        except (KeyError, ValueError):
            continue
        iv = row.get("iv")
        quotes.append(
            OptionQuote(
                expiry=expiry,
                strike=strike,
                right=right,
                open_interest=int(row.get("open_interest") or 0),
                implied_vol=float(iv) if iv else None,
                bid=float(row.get("bid") or 0.0) or None,
                ask=float(row.get("ask") or 0.0) or None,
                last=float(row.get("last_trade_price") or 0.0) or None,
                volume=int(row.get("volume") or 0),
            )
        )
    if not quotes:
        raise ValueError(f"Cboe returned an empty chain for {symbol!r}")

    as_of = datetime.now(timezone.utc)
    stamp = payload.get("timestamp")
    if stamp:
        try:
            # Cboe stamps these in US/Eastern without an offset.
            as_of = datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return Chain(symbol.upper(), float(spot), quotes, as_of, source="cboe-delayed")
