"""Command line entry point: python -m gexlab <command>"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import config as config_mod
from .cache import ChainCache
from .http import FetchError, HttpClient
from .sources import cboe, yahoo


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"


def _keys_line(keys: list[str], limit: int = 10) -> str:
    shown = ", ".join(keys[:limit])
    return shown + (f", … (+{len(keys) - limit} more)" if len(keys) > limit else "") if keys else "(none)"


def _check(label: str, missing: list[str]) -> str:
    return "OK" if not missing else f"MISSING {', '.join(missing)}"


def doctor_one(ticker: str, source_name: str, cfg, client: HttpClient,
               cache: ChainCache | None, out=sys.stdout) -> bool:
    """Fetch one ticker from one source and report what actually came back."""
    w = out.write
    w(f"\n{ticker} via {source_name}\n")

    module = {"cboe": cboe, "yahoo": yahoo}[source_name]
    try:
        if source_name == "cboe":
            w(f"  url            {cboe.url_for(ticker)}\n")
            payload, meta = cboe.fetch_raw(ticker, client, cache)
        else:
            w(f"  call           yfinance.Ticker({ticker!r}).option_chain(...)  "
              f"max {cfg.yahoo.max_expirations} expirations\n")
            payload, meta = yahoo.fetch_raw(ticker, client, cache,
                                            max_expirations=cfg.yahoo.max_expirations)
    except FetchError as exc:
        w(f"  request        FAILED after {exc.attempts} attempt(s)\n")
        w(f"  reason         {exc.reason}\n")
        if exc.blocked_by_proxy:
            w("  diagnosis      The outbound proxy refused the CONNECT. This is a network\n"
              "                 policy on this machine, not a problem with the data source.\n")
        w("  VERDICT        FAIL\n")
        return False

    if meta.from_cache:
        w("  request        served from today's cache (no network call)\n")
    else:
        w(f"  request        HTTP {meta.status}, {_human_bytes(meta.bytes)} in "
          f"{meta.seconds:.1f}s, {meta.attempts} attempt(s)\n")
    for note in meta.notes:
        w(f"                 {note}\n")

    d = module.describe(payload)
    w(f"  top-level keys {_keys_line(d['top_level_keys'])}\n")
    w(f"                 expected -> {_check('top', d['missing_top'])}\n")
    if source_name == "cboe":
        w(f"  data keys      {_keys_line(d['data_keys'])}\n")
        w(f"                 expected -> {_check('data', d['missing_data'])}\n")
    else:
        w(f"  expirations    {d['expirations_fetched']} fetched of "
          f"{d['expirations_available']} available"
          f"{'  (TRUNCATED — partial open interest)' if d['truncated'] else ''}\n")
    w(f"  contract keys  {_keys_line(d['option_keys'], 14)}\n")
    w(f"                 expected -> {_check('option', d['missing_option'])}\n")
    w(f"  contracts      {d['contract_count']:,}\n")
    if d["populated"]:
        w("  populated      " + "  ".join(f"{k} {v:,}" for k, v in d["populated"].items()) + "\n")
    w(f"  spot           {d['spot']}\n")

    schema_ok = not (d["missing_top"] or d.get("missing_data") or d["missing_option"])

    try:
        chain = module.parse(payload, ticker)
    except (FetchError, ValueError, KeyError, TypeError) as exc:
        w(f"  parse          FAILED — {exc}\n")
        w("  VERDICT        FAIL\n")
        return False

    with_oi = sum(1 for q in chain.quotes if q.open_interest > 0)
    with_iv = sum(1 for q in chain.quotes if q.implied_vol)
    w(f"  parse          OK — {len(chain.quotes):,} quotes, {len(chain.expiries)} expirations\n")
    w(f"                 {with_oi:,} with open interest, {with_iv:,} with implied vol\n")
    w(f"                 source string: {chain.source}\n")

    usable = with_oi > 0 and with_iv > 0
    if not usable:
        w("  VERDICT        FAIL — parsed, but no usable open interest or implied vol\n")
        return False
    w(f"  VERDICT        {'PASS' if schema_ok else 'PASS (with schema drift above)'}\n")
    return True


def cmd_doctor(args) -> int:
    cfg, warnings = config_mod.load(args.config)
    out = sys.stdout
    out.write(f"GEX Lab doctor — {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}\n")
    out.write(f"config: {args.config or config_mod.DEFAULT_PATH}\n")
    for warn in warnings:
        out.write(f"  warning: {warn}\n")

    sources = [args.source] if args.source else [cfg.data.primary, cfg.data.fallback]
    client = HttpClient(cfg.http)
    cache = None if args.no_cache else ChainCache(cfg.path(cfg.cache.dir), cfg.cache.retention_days)
    out.write(f"sources: {', '.join(sources)}   cache: {'off' if cache is None else cfg.cache.dir}\n")
    out.write(f"rate limit: {cfg.http.requests_per_second}/s, "
              f"{cfg.http.max_retries} retries, backoff base {cfg.http.backoff_base_seconds}s\n")

    results = {}
    for ticker in args.tickers:
        for source_name in sources:
            results[(ticker, source_name)] = doctor_one(ticker, source_name, cfg, client, cache, out)

    out.write("\n" + "-" * 68 + "\nSummary\n")
    for (ticker, source_name), ok in results.items():
        out.write(f"  {ticker:<8} {source_name:<8} {'PASS' if ok else 'FAIL'}\n")

    by_source = {s: [ok for (_, sn), ok in results.items() if sn == s] for s in sources}
    primary = sources[0]
    if all(by_source.get(primary, [False])):
        out.write(f"\n{primary} is healthy — safe to build on.\n")
        return 0
    if len(sources) > 1 and all(by_source.get(sources[1], [False])):
        out.write(f"\n{primary} failed but {sources[1]} is healthy — the fallback would carry the load.\n")
        return 1
    out.write("\nNo source is healthy. Do not build on this data until it is fixed.\n")
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gexlab", description="GEX Lab — options positioning research.")
    p.add_argument("--config", help="path to config.toml (default: alongside the package)")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("doctor", help="verify the data sources actually work")
    d.add_argument("tickers", nargs="*", default=["SPY", "TSLA"],
                   help="tickers to test (default: SPY TSLA)")
    d.add_argument("--source", choices=["cboe", "yahoo"], help="test only this source")
    d.add_argument("--no-cache", action="store_true", help="force a live fetch, ignoring today's cache")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "tickers", None) == []:
        args.tickers = ["SPY", "TSLA"]
    return args.func(args)
