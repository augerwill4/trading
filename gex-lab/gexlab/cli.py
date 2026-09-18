"""Command line entry point: python -m gexlab ..."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from . import providers
from .chain import dump_csv
from .gex import SIGN_CONVENTIONS, by_strike, gamma_profile
from .report import Snapshot, pine_inputs, profile_csv, strikes_csv, text_report

EXAMPLES = """
examples:
  python -m gexlab --csv data/sample-spy-chain.csv          # offline demo
  python -m gexlab SPY --max-dte 7                          # live-ish, Cboe delayed
  python -m gexlab SPX --expiry 2026-03-20 --out-dir out/
  python -m gexlab SPY --save-chain data/spy-2026-03-02.csv # snapshot for later
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gexlab",
        description="Dealer gamma exposure from an option chain.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("symbol", nargs="?", help="underlying to pull from Cboe delayed quotes (e.g. SPY, SPX)")
    p.add_argument("--csv", help="read the chain from this file instead of the network")
    p.add_argument("--spot", type=float, help="override the underlying price")

    f = p.add_argument_group("chain filters")
    f.add_argument("--max-dte", type=int, help="only expiries within this many calendar days")
    f.add_argument("--expiry", help="a single expiry, YYYY-MM-DD")
    f.add_argument("--min-oi", type=int, default=1, help="drop strikes below this open interest (default 1)")

    m = p.add_argument_group("model")
    m.add_argument("-r", "--rate", type=float, default=0.04, help="risk-free rate (default 0.04)")
    m.add_argument("-q", "--dividend", type=float, default=0.01, help="dividend yield (default 0.01)")
    m.add_argument("--convention", default="long_calls_short_puts", choices=sorted(SIGN_CONVENTIONS),
                   help="dealer positioning assumption (default long_calls_short_puts)")
    m.add_argument("--range-pct", type=float, default=0.10, help="profile half-width around spot (default 0.10)")
    m.add_argument("--steps", type=int, default=161, help="profile resolution (default 161)")

    o = p.add_argument_group("output")
    o.add_argument("--top", type=int, default=12, help="strikes to list (default 12)")
    o.add_argument("--no-bars", action="store_true", help="plain numbers, no ASCII bars")
    o.add_argument("--out-dir", help="also write strikes.csv, profile.csv and levels.txt here")
    o.add_argument("--save-chain", help="write the raw chain to this CSV for offline reuse")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.symbol and not args.csv:
        build_parser().print_help()
        return 2

    try:
        if args.csv:
            chain = providers.from_csv(args.csv, symbol=args.symbol, spot=args.spot)
        else:
            chain = providers.from_cboe(args.symbol)
            if args.spot:
                chain.spot = args.spot
    except (LookupError, ValueError, OSError) as exc:
        print(f"gexlab: {exc}", file=sys.stderr)
        return 1

    if args.save_chain:
        Path(args.save_chain).write_text(dump_csv(chain))
        print(f"wrote {args.save_chain}", file=sys.stderr)

    expiry = datetime.strptime(args.expiry, "%Y-%m-%d").date() if args.expiry else None
    chain = chain.filtered(max_dte=args.max_dte, expiry=expiry, min_oi=args.min_oi)
    if not chain.quotes:
        print("gexlab: no contracts left after filtering", file=sys.stderr)
        return 1

    model = dict(r=args.rate, div=args.dividend, convention=args.convention)
    snap = Snapshot(
        chain=chain,
        strikes=by_strike(chain, **model),
        profile=gamma_profile(chain, range_pct=args.range_pct, steps=args.steps, **model),
        convention=args.convention,
    )
    if not snap.strikes:
        print("gexlab: every contract was dropped — no usable IV or open interest", file=sys.stderr)
        return 1

    print(text_report(snap, top=args.top, bars=not args.no_bars))
    print(pine_inputs(snap))

    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "strikes.csv").write_text(strikes_csv(snap))
        (out / "profile.csv").write_text(profile_csv(snap))
        (out / "levels.txt").write_text(pine_inputs(snap))
        print(f"wrote {out}/strikes.csv, profile.csv, levels.txt", file=sys.stderr)
    return 0
