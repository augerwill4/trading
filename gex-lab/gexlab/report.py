"""Turning the numbers into something you can read on a terminal or a chart."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass

from .chain import Chain
from .gex import StrikeGex, call_wall, flip_point, put_wall, top_strikes


@dataclass
class Snapshot:
    chain: Chain
    strikes: list[StrikeGex]
    profile: list[tuple[float, float]]
    convention: str

    @property
    def total(self) -> float:
        return sum(s.net_gex for s in self.strikes)

    @property
    def flip(self) -> float | None:
        return flip_point(self.profile, reference=self.chain.spot)

    @property
    def call_wall(self) -> StrikeGex | None:
        return call_wall(self.strikes, above=self.chain.spot)

    @property
    def put_wall(self) -> StrikeGex | None:
        return put_wall(self.strikes, below=self.chain.spot)


def _bn(x: float) -> str:
    return f"{x / 1e9:+.3f} Bn"


def _bar(value: float, scale: float, width: int = 28) -> str:
    """One centered bar: puts run left of the axis, calls run right."""
    if scale <= 0.0:
        return " " * (2 * width + 1)
    n = min(width, int(round(abs(value) / scale * width)))
    if value >= 0:
        return " " * width + "|" + "#" * n + " " * (width - n)
    return " " * (width - n) + "#" * n + "|" + " " * width


def text_report(snap: Snapshot, *, top: int = 12, bars: bool = True) -> str:
    c = snap.chain
    out = io.StringIO()
    w = out.write

    w(f"{c.symbol}  spot {c.spot:,.2f}   {c.as_of:%Y-%m-%d %H:%M UTC}   source: {c.source}\n")
    w(f"convention: dealers {snap.convention.replace('_', ' ')}\n")
    w(f"expiries: {len(c.expiries)}   strikes: {len(snap.strikes)}   "
      f"contracts: {sum(1 for q in c.quotes if q.open_interest > 0):,}\n")
    w("-" * 78 + "\n")

    total = snap.total
    regime = "POSITIVE — dealers dampen moves, fade the extremes" if total > 0 else \
             "NEGATIVE — dealers amplify moves, trend and momentum regime"
    w(f"Net GEX          {_bn(total)} per 1% move\n")
    w(f"Regime           {regime}\n")

    flip = snap.flip
    if flip is None:
        w("Gamma flip       not inside the scanned range\n")
    else:
        w(f"Gamma flip       {flip:,.2f}   ({(flip / c.spot - 1) * 100:+.2f}% from spot)\n")

    cw, pw = snap.call_wall, snap.put_wall
    if cw:
        w(f"Call wall        {cw.strike:,.2f}   {_bn(cw.call_gex)}   OI {cw.call_oi:,}\n")
    if pw:
        w(f"Put wall         {pw.strike:,.2f}   {_bn(pw.put_gex)}   OI {pw.put_oi:,}\n")
    w("-" * 78 + "\n")

    ladder = top_strikes(snap.strikes, top)
    ladder.sort(key=lambda s: s.strike, reverse=True)
    scale = max((abs(s.net_gex) for s in ladder), default=0.0)
    w(f"Top {len(ladder)} strikes by absolute gamma        (puts <-- | --> calls)\n")
    for s in ladder:
        marker = "  <-- spot" if abs(s.strike - c.spot) <= _tick(snap.strikes) / 2 else ""
        line = f"{s.strike:>10,.2f}  {_bn(s.net_gex):>12}  "
        if bars:
            line += _bar(s.net_gex, scale, 22)
        w(line.rstrip() + marker + "\n")
    return out.getvalue()


def _tick(strikes: list[StrikeGex]) -> float:
    gaps = [b.strike - a.strike for a, b in zip(strikes, strikes[1:]) if b.strike > a.strike]
    return min(gaps) if gaps else 1.0


def strikes_csv(snap: Snapshot) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["strike", "call_gex", "put_gex", "net_gex", "abs_gex", "call_oi", "put_oi"])
    for s in snap.strikes:
        w.writerow([s.strike, round(s.call_gex, 2), round(s.put_gex, 2),
                    round(s.net_gex, 2), round(s.abs_gex, 2), s.call_oi, s.put_oi])
    return out.getvalue()


def profile_csv(snap: Snapshot) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["spot", "total_gex"])
    for px, g in snap.profile:
        w.writerow([round(px, 4), round(g, 2)])
    return out.getvalue()


def pine_inputs(snap: Snapshot, *, extra: int = 3) -> str:
    """The settings block to paste into pine/gex-levels.pine's inputs.

    Kept as copy-paste text rather than a generated script: the indicator is
    fixed, only the numbers change, and typing four numbers into the settings
    dialog beats re-pasting a script every morning.
    """
    c = snap.chain
    flip = snap.flip
    cw, pw = snap.call_wall, snap.put_wall
    used = {round(x, 2) for x in (flip, cw.strike if cw else None, pw.strike if pw else None) if x}
    # A level sitting on top of spot is not a level you can trade against, and a
    # duplicate of a wall is noise on the chart. Drop both.
    others = [
        s for s in top_strikes(snap.strikes, 60)
        if round(s.strike, 2) not in used and abs(s.strike / c.spot - 1.0) >= 0.0025
    ][:extra]

    lines = [
        f"// {c.symbol} GEX levels — {c.as_of:%Y-%m-%d %H:%M UTC} ({c.source.split(' (')[0]})",
        f"// spot {c.spot:,.2f}   net GEX {_bn(snap.total)} per 1%",
        f"Gamma flip      = {flip:,.2f}" if flip else "Gamma flip      = (none in range)",
        f"Call wall       = {cw.strike:,.2f}" if cw else "Call wall       = (none)",
        f"Put wall        = {pw.strike:,.2f}" if pw else "Put wall        = (none)",
    ]
    for i, s in enumerate(others, start=1):
        lines.append(f"Extra level {i}   = {s.strike:,.2f}   // {s.abs_gex / 1e9:.3f} Bn gamma")
    return "\n".join(lines) + "\n"
