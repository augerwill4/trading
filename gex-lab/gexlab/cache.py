"""One fetch per ticker, per source, per day.

Option chains are large and open interest only settles overnight, so re-fetching
the same ticker twice in a day costs the data provider bandwidth and tells us
nothing new. Entries are gzipped JSON on disk and pruned on a rolling window.
"""

from __future__ import annotations

import gzip
import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path


@dataclass
class CacheStats:
    entries: int
    bytes: int
    days: list[str]


class ChainCache:
    def __init__(self, root: Path, retention_days: int = 30):
        self.root = Path(root)
        self.retention_days = retention_days

    def path_for(self, source: str, ticker: str, day: date | None = None) -> Path:
        day = day or date.today()
        safe = ticker.upper().replace("/", "_").replace(".", "_")
        return self.root / source.lower() / day.isoformat() / f"{safe}.json.gz"

    def get(self, source: str, ticker: str, day: date | None = None) -> dict | None:
        p = self.path_for(source, ticker, day)
        if not p.exists():
            return None
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            # A truncated or corrupt entry is treated as a miss rather than an
            # error: the cost is one refetch, and the alternative is a crash on
            # a file the user never asked about.
            p.unlink(missing_ok=True)
            return None

    def put(self, source: str, ticker: str, payload: dict, day: date | None = None) -> Path:
        p = self.path_for(source, ticker, day)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh)
        tmp.replace(p)  # atomic, so an interrupted write never leaves a bad entry
        return p

    def prune(self, today: date | None = None) -> tuple[int, int]:
        """Delete day-folders older than the retention window.

        Returns (folders_removed, bytes_freed).
        """
        today = today or date.today()
        cutoff = today - timedelta(days=self.retention_days)
        removed = freed = 0
        if not self.root.exists():
            return 0, 0
        for source_dir in self.root.iterdir():
            if not source_dir.is_dir():
                continue
            for day_dir in source_dir.iterdir():
                if not day_dir.is_dir():
                    continue
                try:
                    day = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if day < cutoff:
                    freed += sum(f.stat().st_size for f in day_dir.rglob("*") if f.is_file())
                    shutil.rmtree(day_dir)
                    removed += 1
        return removed, freed

    def stats(self) -> CacheStats:
        if not self.root.exists():
            return CacheStats(0, 0, [])
        files = [f for f in self.root.rglob("*.json.gz") if f.is_file()]
        days = sorted({f.parent.name for f in files})
        return CacheStats(len(files), sum(f.stat().st_size for f in files), days)
