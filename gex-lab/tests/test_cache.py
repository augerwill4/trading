"""Cache behaviour: one fetch per ticker per day, atomic writes, retention."""

import gzip
import tempfile
import unittest
from datetime import date
from pathlib import Path

from gexlab.cache import ChainCache


class TestCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = ChainCache(Path(self.tmp.name), retention_days=30)
        self.day = date(2026, 3, 2)

    def tearDown(self):
        self.tmp.cleanup()

    def test_miss_then_hit(self):
        self.assertIsNone(self.cache.get("cboe", "SPY", self.day))
        self.cache.put("cboe", "SPY", {"data": {"x": 1}}, self.day)
        self.assertEqual(self.cache.get("cboe", "SPY", self.day), {"data": {"x": 1}})

    def test_separated_by_day_source_and_ticker(self):
        self.cache.put("cboe", "SPY", {"v": 1}, self.day)
        self.assertIsNone(self.cache.get("cboe", "SPY", date(2026, 3, 3)))
        self.assertIsNone(self.cache.get("yahoo", "SPY", self.day))
        self.assertIsNone(self.cache.get("cboe", "QQQ", self.day))

    def test_ticker_with_punctuation_is_path_safe(self):
        self.cache.put("cboe", "BRK.B", {"v": 1}, self.day)
        self.assertEqual(self.cache.get("cboe", "BRK.B", self.day), {"v": 1})
        self.assertIn("BRK_B", str(self.cache.path_for("cboe", "BRK.B", self.day)))

    def test_corrupt_entry_is_treated_as_a_miss(self):
        p = self.cache.path_for("cboe", "SPY", self.day)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"not gzip")
        self.assertIsNone(self.cache.get("cboe", "SPY", self.day))
        self.assertFalse(p.exists())  # and it cleans up after itself

    def test_write_is_gzipped(self):
        p = self.cache.put("cboe", "SPY", {"hello": "world"}, self.day)
        with gzip.open(p, "rt") as fh:
            self.assertIn("hello", fh.read())

    def test_no_temp_files_left_behind(self):
        self.cache.put("cboe", "SPY", {"v": 1}, self.day)
        self.assertEqual(list(Path(self.tmp.name).rglob("*.tmp")), [])

    def test_prune_removes_only_old_days(self):
        self.cache.put("cboe", "SPY", {"v": 1}, date(2026, 1, 1))   # old
        self.cache.put("cboe", "QQQ", {"v": 1}, date(2026, 3, 1))   # inside window
        removed, freed = self.cache.prune(today=date(2026, 3, 2))
        self.assertEqual(removed, 1)
        self.assertGreater(freed, 0)
        self.assertIsNone(self.cache.get("cboe", "SPY", date(2026, 1, 1)))
        self.assertIsNotNone(self.cache.get("cboe", "QQQ", date(2026, 3, 1)))

    def test_prune_ignores_unparseable_folder_names(self):
        (Path(self.tmp.name) / "cboe" / "not-a-date").mkdir(parents=True)
        removed, _ = self.cache.prune(today=date(2026, 3, 2))
        self.assertEqual(removed, 0)

    def test_stats(self):
        self.cache.put("cboe", "SPY", {"v": 1}, self.day)
        self.cache.put("cboe", "QQQ", {"v": 1}, self.day)
        stats = self.cache.stats()
        self.assertEqual(stats.entries, 2)
        self.assertGreater(stats.bytes, 0)
        self.assertEqual(stats.days, ["2026-03-02"])

    def test_stats_on_empty_cache(self):
        self.assertEqual(ChainCache(Path(self.tmp.name) / "nope").stats().entries, 0)


if __name__ == "__main__":
    unittest.main()
