"""Config loading, including the real config.toml shipped with the project."""

import tempfile
import unittest
from pathlib import Path

from gexlab import config as config_mod


class TestConfig(unittest.TestCase):
    def test_ships_a_loadable_config(self):
        cfg, warnings = config_mod.load()
        self.assertEqual(warnings, [], f"config.toml has problems: {warnings}")
        self.assertEqual(cfg.liquidity.min_total_open_interest, 50_000)
        self.assertEqual(cfg.liquidity.min_daily_option_volume, 10_000)
        self.assertAlmostEqual(cfg.liquidity.max_atm_spread_pct, 0.05)
        self.assertAlmostEqual(cfg.liquidity.min_underlying_price, 10.0)

    def test_always_included_tickers_are_upper_case_tuple(self):
        cfg, _ = config_mod.load()
        self.assertEqual(cfg.universe.always_include, ("SPY", "QQQ", "SPX", "IWM"))

    def test_missing_file_falls_back_to_defaults_with_a_warning(self):
        cfg, warnings = config_mod.load("/nonexistent/config.toml")
        self.assertEqual(cfg.liquidity.min_total_open_interest, 50_000)
        self.assertTrue(any("not found" in w for w in warnings))

    def test_unknown_keys_are_warned_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.toml"
            p.write_text("[liquidity]\nmin_underlying_price = 25.0\nnonsense = 1\n\n[bogus]\nx = 2\n")
            cfg, warnings = config_mod.load(p)
            self.assertAlmostEqual(cfg.liquidity.min_underlying_price, 25.0)
            self.assertTrue(any("nonsense" in w for w in warnings))
            self.assertTrue(any("[bogus]" in w for w in warnings))

    def test_paths_resolve_against_the_project_root(self):
        cfg, _ = config_mod.load()
        self.assertTrue(cfg.path("data/cache").is_absolute())
        self.assertEqual(cfg.path("/tmp/abs"), Path("/tmp/abs"))


if __name__ == "__main__":
    unittest.main()
