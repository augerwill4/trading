"""Chains read from a CSV on disk. Offline, reproducible, used by the tests."""

from __future__ import annotations

from pathlib import Path

from ..chain import Chain, load_csv

NAME = "csv"


def fetch(path: str | Path, *, symbol: str | None = None, spot: float | None = None) -> Chain:
    return load_csv(Path(path).read_text(), symbol=symbol, spot=spot)
