"""Option chain data model, CSV I/O, and OCC symbol parsing."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

# Options settle 16:00 New York. No tz database dependency: EDT is UTC-4, EST is
# UTC-5, and the error from picking the wrong one is one hour of theta on the
# front expiry — immaterial to gamma, and named here so it is not a surprise.
_EXPIRY_HOUR_UTC = 20


@dataclass(frozen=True)
class OptionQuote:
    expiry: date
    strike: float
    right: str  # "C" or "P"
    open_interest: int = 0
    implied_vol: float | None = None
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: int = 0

    @property
    def is_call(self) -> bool:
        return self.right.upper().startswith("C")

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.ask >= self.bid > 0.0:
            return 0.5 * (self.bid + self.ask)
        return self.last if self.last else None

    def years_to_expiry(self, now: datetime) -> float:
        settle = datetime(
            self.expiry.year, self.expiry.month, self.expiry.day, _EXPIRY_HOUR_UTC, tzinfo=timezone.utc
        )
        return (settle - now).total_seconds() / (365.0 * 24.0 * 3600.0)


@dataclass
class Chain:
    symbol: str
    spot: float
    quotes: list[OptionQuote] = field(default_factory=list)
    as_of: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "unknown"

    @property
    def expiries(self) -> list[date]:
        return sorted({q.expiry for q in self.quotes})

    def filtered(self, *, max_dte: int | None = None, expiry: date | None = None, min_oi: int = 0) -> "Chain":
        today = self.as_of.date()
        out = []
        for q in self.quotes:
            if q.open_interest < min_oi:
                continue
            if expiry is not None and q.expiry != expiry:
                continue
            if max_dte is not None and (q.expiry - today).days > max_dte:
                continue
            if q.expiry < today:
                continue
            out.append(q)
        return Chain(self.symbol, self.spot, out, self.as_of, self.source)


OCC_RE = re.compile(r"^(?P<root>[A-Z0-9]{1,6})(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})(?P<right>[CP])(?P<strike>\d{8})$")


def parse_occ(symbol: str) -> tuple[str, date, str, float]:
    """Split an OCC contract symbol, e.g. SPY260320C00600000."""
    m = OCC_RE.match(symbol.strip().upper())
    if not m:
        raise ValueError(f"not an OCC option symbol: {symbol!r}")
    return (
        m["root"],
        date(2000 + int(m["y"]), int(m["m"]), int(m["d"])),
        m["right"],
        int(m["strike"]) / 1000.0,
    )


def _num(row: dict, *names: str) -> float | None:
    for n in names:
        v = row.get(n)
        if v not in (None, "", "-"):
            try:
                return float(v)
            except ValueError:
                continue
    return None


def load_csv(text: str, *, symbol: str | None = None, spot: float | None = None) -> Chain:
    """Read a chain from CSV text.

    Required columns: expiry, strike, right, open_interest.
    Optional: implied_vol, bid, ask, last, volume.
    `# symbol: SPY` / `# spot: 585.20` / `# as_of: 2026-03-02T18:30:00Z` comment
    lines above the header are read as metadata so a saved file is self-contained.
    """
    meta: dict[str, str] = {}
    body: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") and ":" in line:
            k, _, v = line.lstrip("# ").partition(":")
            meta[k.strip().lower()] = v.strip()
        elif line.strip():
            body.append(line)

    quotes: list[OptionQuote] = []
    for row in csv.DictReader(io.StringIO("\n".join(body))):
        row = {(k or "").strip().lower(): v for k, v in row.items()}
        strike = _num(row, "strike")
        if strike is None:
            continue
        raw_expiry = (row.get("expiry") or row.get("expiration") or "").strip()
        expiry = datetime.strptime(raw_expiry.replace("/", "-")[:10], "%Y-%m-%d").date()
        iv = _num(row, "implied_vol", "iv")
        quotes.append(
            OptionQuote(
                expiry=expiry,
                strike=strike,
                right=(row.get("right") or row.get("type") or "C").strip().upper()[0],
                open_interest=int(_num(row, "open_interest", "oi") or 0),
                implied_vol=iv if iv and iv > 0.0 else None,
                bid=_num(row, "bid"),
                ask=_num(row, "ask"),
                last=_num(row, "last", "close"),
                volume=int(_num(row, "volume", "vol") or 0),
            )
        )

    resolved_spot = spot if spot is not None else _num(meta, "spot")
    if resolved_spot is None:
        raise ValueError("spot price missing — pass --spot or add a '# spot: <price>' line to the CSV")

    as_of = datetime.now(timezone.utc)
    if "as_of" in meta:
        as_of = datetime.fromisoformat(meta["as_of"].replace("Z", "+00:00"))

    return Chain(
        symbol=symbol or meta.get("symbol", "UNKNOWN"),
        spot=float(resolved_spot),
        quotes=quotes,
        as_of=as_of,
        source=meta.get("source", "csv"),
    )


def dump_csv(chain: Chain) -> str:
    out = io.StringIO()
    out.write(f"# symbol: {chain.symbol}\n# spot: {chain.spot}\n")
    out.write(f"# as_of: {chain.as_of.isoformat()}\n# source: {chain.source}\n")
    w = csv.writer(out)
    w.writerow(["expiry", "strike", "right", "open_interest", "implied_vol", "bid", "ask", "last", "volume"])
    for q in sorted(chain.quotes, key=lambda x: (x.expiry, x.strike, x.right)):
        w.writerow([q.expiry.isoformat(), q.strike, q.right, q.open_interest,
                    "" if q.implied_vol is None else round(q.implied_vol, 6),
                    "" if q.bid is None else q.bid, "" if q.ask is None else q.ask,
                    "" if q.last is None else q.last, q.volume])
    return out.getvalue()


def next_friday(from_day: date, weeks: int = 0) -> date:
    """Helper for building test chains."""
    return from_day + timedelta(days=(4 - from_day.weekday()) % 7 + 7 * weeks)
