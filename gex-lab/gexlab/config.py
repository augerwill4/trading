"""Loads config.toml.

tomllib is standard library on Python 3.11+, so the config file costs no
dependency and still allows comments — which matters, because half the value of
config.toml is the explanation next to each threshold.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "config.toml"


@dataclass(frozen=True)
class HttpConfig:
    requests_per_second: float = 1.0
    timeout_seconds: float = 30.0
    max_retries: int = 4
    backoff_base_seconds: float = 2.0
    backoff_max_seconds: float = 60.0


@dataclass(frozen=True)
class CacheConfig:
    dir: str = "data/cache"
    retention_days: int = 30


@dataclass(frozen=True)
class LiquidityConfig:
    min_total_open_interest: int = 50_000
    min_daily_option_volume: int = 10_000
    max_atm_spread_pct: float = 0.05
    min_underlying_price: float = 10.0
    front_month_min_dte: int = 5
    atm_band_pct: float = 0.05


@dataclass(frozen=True)
class UniverseConfig:
    always_include: tuple[str, ...] = ("SPY", "QQQ", "SPX", "IWM")
    candidates_file: str = "candidates.txt"
    watchlist_file: str = "watchlist.txt"
    output: str = "data/universe.csv"
    top_n_daily: int = 50


@dataclass(frozen=True)
class ScanConfig:
    require_after_close: bool = True
    close_hour_et: int = 16
    close_grace_minutes: int = 15
    min_volume_to_oi_ratio: float = 0.02


@dataclass(frozen=True)
class DataConfig:
    primary: str = "cboe"
    fallback: str = "yahoo"
    risk_free_rate: float = 0.043
    dividend_yield: float = 0.010


@dataclass(frozen=True)
class YahooConfig:
    max_expirations: int = 12


@dataclass(frozen=True)
class Config:
    root: Path
    data: DataConfig = field(default_factory=DataConfig)
    http: HttpConfig = field(default_factory=HttpConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    liquidity: LiquidityConfig = field(default_factory=LiquidityConfig)
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    yahoo: YahooConfig = field(default_factory=YahooConfig)

    def path(self, relative: str) -> Path:
        """Resolve a config-relative path against the project root."""
        p = Path(relative)
        return p if p.is_absolute() else self.root / p


def _section(raw: dict, name: str, cls):
    """Build a config dataclass, ignoring unknown keys rather than crashing.

    An unknown key in config.toml is far more likely to be a typo the user wants
    reported than a reason to refuse to start, so it is named and skipped.
    """
    given = raw.get(name, {}) or {}
    known = {f for f in cls.__dataclass_fields__}
    unknown = sorted(set(given) - known)
    kept = {k: v for k, v in given.items() if k in known}
    if name == "universe" and "always_include" in kept:
        kept["always_include"] = tuple(str(t).upper() for t in kept["always_include"])
    return cls(**kept), [f"[{name}] {k}" for k in unknown]


def load(path: str | Path | None = None) -> tuple[Config, list[str]]:
    """Return (config, warnings). Missing file falls back to the defaults."""
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return Config(root=p.parent), [f"config file not found at {p} — using built-in defaults"]

    raw = tomllib.loads(p.read_text())
    warnings: list[str] = []
    sections = {}
    for name, cls in (
        ("data", DataConfig), ("http", HttpConfig), ("cache", CacheConfig),
        ("liquidity", LiquidityConfig), ("universe", UniverseConfig),
        ("scan", ScanConfig), ("yahoo", YahooConfig),
    ):
        sections[name], unknown = _section(raw, name, cls)
        warnings += [f"unknown config key, ignored: {u}" for u in unknown]

    for extra in sorted(set(raw) - set(sections)):
        warnings.append(f"unknown config section, ignored: [{extra}]")

    return Config(root=p.parent, **sections), warnings
