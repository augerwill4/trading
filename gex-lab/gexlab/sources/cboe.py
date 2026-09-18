"""Cboe free delayed quotes.

    https://cdn.cboe.com/api/global/delayed_quotes/options/SPY.json

Public CDN JSON, no API key, roughly 15 minutes delayed. It carries the full
chain with open interest, implied volatility, volume and a two-sided quote,
which is everything the scanner and the GEX engine need.

The delay does not matter for open interest — that settles overnight — but it
does matter for the spot price the gamma profile is centred on. Phase 2 exposes
a --spot override for that reason.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from ..cache import ChainCache
from ..chain import Chain, OptionQuote, parse_occ
from ..http import FetchError, FetchMeta, HttpClient

NAME = "cboe"
URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
DELAY_NOTE = "~15 minutes delayed"

# Cboe files index products under a leading underscore (_SPX, _VIX, ...).
INDEX_SYMBOLS = {"SPX", "SPXW", "NDX", "RUT", "VIX", "XSP", "DJX", "OEX", "XEO", "MRUT"}

# What the parser reads. doctor checks the live payload against these.
EXPECTED_TOP = ("data",)
EXPECTED_DATA = ("current_price", "options")
EXPECTED_OPTION = ("option", "open_interest", "iv", "bid", "ask", "volume")


def api_ticker(ticker: str) -> str:
    t = ticker.strip().upper().lstrip("_^")
    return f"_{t}" if t in INDEX_SYMBOLS else t


def url_for(ticker: str) -> str:
    return URL.format(ticker=api_ticker(ticker))


def fetch_raw(ticker: str, client: HttpClient, cache: ChainCache | None = None,
              day: date | None = None) -> tuple[dict, FetchMeta]:
    """Return the raw JSON payload, from cache when we already have today's."""
    if cache is not None:
        cached = cache.get(NAME, ticker, day)
        if cached is not None:
            return cached, FetchMeta(url=url_for(ticker), from_cache=True,
                                     notes=["served from cache"])
    payload, meta = client.get_json(url_for(ticker))
    if cache is not None:
        cache.put(NAME, ticker, payload, day)
    return payload, meta


def describe(payload: dict) -> dict:
    """Structural diagnosis of a raw payload, for the doctor command."""
    data = payload.get("data") if isinstance(payload, dict) else None
    options = (data or {}).get("options") if isinstance(data, dict) else None
    sample = options[0] if isinstance(options, list) and options else {}

    def missing(expected, actual) -> list[str]:
        have = set(actual or ())
        return [k for k in expected if k not in have]

    populated = {}
    if isinstance(options, list) and options:
        for key in EXPECTED_OPTION:
            populated[key] = sum(1 for row in options if row.get(key) not in (None, "", 0))

    return {
        "top_level_keys": sorted(payload) if isinstance(payload, dict) else [],
        "missing_top": missing(EXPECTED_TOP, payload if isinstance(payload, dict) else {}),
        "data_keys": sorted(data) if isinstance(data, dict) else [],
        "missing_data": missing(EXPECTED_DATA, data if isinstance(data, dict) else {}),
        "option_keys": sorted(sample) if isinstance(sample, dict) else [],
        "missing_option": missing(EXPECTED_OPTION, sample if isinstance(sample, dict) else {}),
        "contract_count": len(options) if isinstance(options, list) else 0,
        "populated": populated,
        "spot": (data or {}).get("current_price") or (data or {}).get("close"),
    }


def parse(payload: dict, ticker: str) -> Chain:
    data = payload.get("data") or {}
    spot = data.get("current_price") or data.get("close")
    if not spot:
        raise FetchError(url_for(ticker), "payload carried no underlying price")

    quotes: list[OptionQuote] = []
    unparsed = 0
    for row in data.get("options") or []:
        try:
            _, expiry, right, strike = parse_occ(row["option"])
        except (KeyError, TypeError, ValueError):
            unparsed += 1
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
        raise FetchError(url_for(ticker), "payload carried no parseable contracts")

    as_of = datetime.now(timezone.utc)
    stamp = payload.get("timestamp")
    if stamp:
        try:
            as_of = datetime.fromisoformat(str(stamp)).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    chain = Chain(ticker.upper(), float(spot), quotes, as_of, source=f"cboe ({DELAY_NOTE})")
    if unparsed:
        chain.source += f" [{unparsed} unparseable contract symbols skipped]"
    return chain


def fetch(ticker: str, client: HttpClient, cache: ChainCache | None = None,
          day: date | None = None) -> tuple[Chain, FetchMeta]:
    payload, meta = fetch_raw(ticker, client, cache, day)
    return parse(payload, ticker), meta
