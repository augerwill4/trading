"""Yahoo Finance fallback, via yfinance.

Used only when Cboe fails. Two things to understand about it:

1. It costs one request per expiration, so a full chain is far more expensive
   than Cboe's single file. `[yahoo] max_expirations` caps it, which means a
   Yahoo-sourced scan UNDERSTATES total open interest. The scanner flags any
   row sourced this way so the number is never silently compared against a
   Cboe-sourced one.

2. Yahoo's endpoint is undocumented and periodically changes its auth handshake.
   yfinance absorbs that churn, which is the reason for the dependency.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from ..cache import ChainCache
from ..chain import Chain, OptionQuote
from ..http import FetchError, FetchMeta, HttpClient

NAME = "yahoo"
DELAY_NOTE = "~15 minutes delayed"

# Columns the parser reads off each yfinance option DataFrame.
EXPECTED_COLUMNS = ("strike", "openInterest", "impliedVolatility", "bid", "ask", "volume")


def _clean(value, cast, default=None):
    """yfinance leaves NaN in numeric columns; treat it as absent."""
    try:
        if value is None or value != value:  # NaN is the only value != itself
            return default
        return cast(value)
    except (TypeError, ValueError):
        return default


def fetch_raw(ticker: str, client: HttpClient, cache: ChainCache | None = None,
              day: date | None = None, max_expirations: int = 12) -> tuple[dict, FetchMeta]:
    """Pull the chain into a plain JSON-serializable dict so it can be cached."""
    if cache is not None:
        cached = cache.get(NAME, ticker, day)
        if cached is not None:
            return cached, FetchMeta(url=f"yfinance:{ticker}", from_cache=True,
                                     notes=["served from cache"])

    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise FetchError(f"yfinance:{ticker}", f"yfinance is not installed: {exc}") from exc

    handle = yf.Ticker(ticker.upper())

    client.limiter.wait()
    try:
        expirations = list(handle.options or [])
    except Exception as exc:
        raise FetchError(f"yfinance:{ticker}", f"could not list expirations: {exc}") from exc
    if not expirations:
        raise FetchError(f"yfinance:{ticker}", "no expirations returned")

    spot = None
    try:
        spot = _clean(handle.fast_info.get("last_price"), float)
    except Exception:
        spot = None
    if not spot:
        raise FetchError(f"yfinance:{ticker}", "no underlying price returned")

    chains, truncated = {}, len(expirations) > max_expirations
    for exp in expirations[:max_expirations]:
        client.limiter.wait()
        try:
            board = handle.option_chain(exp)
        except Exception as exc:
            raise FetchError(f"yfinance:{ticker}", f"option_chain({exp}) failed: {exc}") from exc
        chains[exp] = {
            "calls": board.calls.to_dict(orient="records"),
            "puts": board.puts.to_dict(orient="records"),
        }

    payload = {
        "ticker": ticker.upper(),
        "spot": float(spot),
        "expirations_available": expirations,
        "expirations_fetched": list(chains),
        "truncated": truncated,
        "chains": chains,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    if cache is not None:
        cache.put(NAME, ticker, payload, day)

    notes = []
    if truncated:
        notes.append(f"fetched {len(chains)} of {len(expirations)} expirations — open interest is a partial total")
    return payload, FetchMeta(url=f"yfinance:{ticker}", attempts=1, notes=notes)


def describe(payload: dict) -> dict:
    chains = payload.get("chains") or {}
    first = next(iter(chains.values()), {})
    sample_rows = (first.get("calls") or []) + (first.get("puts") or [])
    sample = sample_rows[0] if sample_rows else {}
    all_rows = [r for board in chains.values() for r in (board.get("calls") or []) + (board.get("puts") or [])]

    populated = {}
    for col in EXPECTED_COLUMNS:
        populated[col] = sum(1 for r in all_rows if r.get(col) not in (None, "", 0) and r.get(col) == r.get(col))

    return {
        "top_level_keys": sorted(payload),
        "missing_top": [k for k in ("spot", "chains") if k not in payload],
        "option_keys": sorted(sample),
        "missing_option": [c for c in EXPECTED_COLUMNS if c not in sample],
        "contract_count": len(all_rows),
        "expirations_available": len(payload.get("expirations_available") or []),
        "expirations_fetched": len(chains),
        "truncated": bool(payload.get("truncated")),
        "populated": populated,
        "spot": payload.get("spot"),
    }


def parse(payload: dict, ticker: str) -> Chain:
    spot = payload.get("spot")
    if not spot:
        raise FetchError(f"yfinance:{ticker}", "payload carried no underlying price")

    quotes: list[OptionQuote] = []
    for exp_str, board in (payload.get("chains") or {}).items():
        try:
            expiry = datetime.strptime(exp_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        for right, rows in (("C", board.get("calls") or []), ("P", board.get("puts") or [])):
            for row in rows:
                strike = _clean(row.get("strike"), float)
                if strike is None:
                    continue
                iv = _clean(row.get("impliedVolatility"), float)
                quotes.append(
                    OptionQuote(
                        expiry=expiry,
                        strike=strike,
                        right=right,
                        open_interest=_clean(row.get("openInterest"), int, 0) or 0,
                        implied_vol=iv if iv and iv > 0 else None,
                        bid=_clean(row.get("bid"), float) or None,
                        ask=_clean(row.get("ask"), float) or None,
                        last=_clean(row.get("lastPrice"), float) or None,
                        volume=_clean(row.get("volume"), int, 0) or 0,
                    )
                )
    if not quotes:
        raise FetchError(f"yfinance:{ticker}", "payload carried no parseable contracts")

    source = f"yahoo ({DELAY_NOTE})"
    if payload.get("truncated"):
        source += f" [partial: {len(payload.get('expirations_fetched') or [])} of " \
                  f"{len(payload.get('expirations_available') or [])} expirations]"
    as_of = datetime.now(timezone.utc)
    try:
        as_of = datetime.fromisoformat(payload["fetched_at"])
    except (KeyError, ValueError):
        pass
    return Chain(ticker.upper(), float(spot), quotes, as_of, source=source)


def fetch(ticker: str, client: HttpClient, cache: ChainCache | None = None,
          day: date | None = None, max_expirations: int = 12) -> tuple[Chain, FetchMeta]:
    payload, meta = fetch_raw(ticker, client, cache, day, max_expirations)
    return parse(payload, ticker), meta
