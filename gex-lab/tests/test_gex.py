import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from gexlab import providers
from gexlab.chain import Chain, OptionQuote, dump_csv, load_csv
from gexlab.gex import (
    by_strike,
    call_wall,
    contract_gex,
    flip_point,
    gamma_profile,
    put_wall,
    total_gex,
)
from gexlab.report import Snapshot, pine_inputs, strikes_csv

NOW = datetime(2026, 3, 2, 18, 30, tzinfo=timezone.utc)
SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample-spy-chain.csv"


def chain(*quotes, spot=100.0):
    return Chain("TEST", spot, list(quotes), NOW, "test")


def opt(right, strike, oi=1000, iv=0.2, expiry=date(2026, 4, 1)):
    return OptionQuote(expiry=expiry, strike=strike, right=right, open_interest=oi, implied_vol=iv)


class TestContractGex(unittest.TestCase):
    def test_sign_convention(self):
        c, p = opt("C", 100), opt("P", 100)
        t = c.years_to_expiry(NOW)
        self.assertGreater(contract_gex(c, 100, t, vol=0.2), 0)
        self.assertLess(contract_gex(p, 100, t, vol=0.2), 0)

    def test_equal_call_and_put_oi_nets_to_zero(self):
        self.assertAlmostEqual(total_gex(chain(opt("C", 100), opt("P", 100))), 0.0, places=6)

    def test_all_long_convention_makes_puts_positive(self):
        self.assertGreater(total_gex(chain(opt("P", 100)), convention="all_long"), 0)
        self.assertLess(total_gex(chain(opt("C", 100)), convention="all_short"), 0)

    def test_units_are_dollars_per_one_percent(self):
        # One contract of dollar gamma is gamma * 100 * S^2 * 0.01.
        q = opt("C", 100, oi=1)
        t = q.years_to_expiry(NOW)
        from gexlab import blackscholes as bs

        expected = bs.gamma(100, 100, t, 0.2) * 1 * 100 * 100 * 100 * 0.01
        self.assertAlmostEqual(contract_gex(q, 100, t, vol=0.2), expected, places=9)

    def test_expired_and_zero_oi_contracts_are_dropped(self):
        stale = opt("C", 100, expiry=date(2026, 1, 1))
        self.assertEqual(by_strike(chain(stale, opt("C", 105, oi=0))), [])


class TestProfileAndLevels(unittest.TestCase):
    def setUp(self):
        # Puts stacked below, calls stacked above: negative gamma under the
        # market, positive over it, so the flip has to sit between them.
        quotes = [opt("P", k, oi=4000) for k in (90, 92, 94, 96)]
        quotes += [opt("C", k, oi=4000) for k in (104, 106, 108, 110)]
        self.chain = chain(*quotes)
        self.strikes = by_strike(self.chain)
        self.profile = gamma_profile(self.chain, range_pct=0.20, steps=201)

    def test_flip_sits_between_the_walls(self):
        flip = flip_point(self.profile, reference=100.0)
        self.assertIsNotNone(flip)
        self.assertTrue(96 < flip < 104, flip)

    def test_walls_land_on_the_heaviest_strikes(self):
        cw = call_wall(self.strikes, above=100.0)
        pw = put_wall(self.strikes, below=100.0)
        self.assertEqual(cw.strike, 104.0)  # nearest ATM carries the most gamma
        self.assertEqual(pw.strike, 96.0)

    def test_profile_is_negative_below_and_positive_above(self):
        self.assertLess(total_gex(self.chain, spot=92.0), 0)
        self.assertGreater(total_gex(self.chain, spot=108.0), 0)

    def test_flip_picks_the_crossing_nearest_the_reference(self):
        synthetic = [(90.0, -1.0), (95.0, 1.0), (100.0, -1.0), (105.0, 1.0)]
        self.assertAlmostEqual(flip_point(synthetic, reference=104.0), 102.5)
        self.assertAlmostEqual(flip_point(synthetic, reference=91.0), 92.5)

    def test_no_crossing_returns_none(self):
        self.assertIsNone(flip_point([(90.0, 1.0), (100.0, 2.0)]))


class TestChainIO(unittest.TestCase):
    def test_csv_round_trip(self):
        original = chain(opt("C", 100), opt("P", 95, oi=250), spot=101.5)
        restored = load_csv(dump_csv(original))
        self.assertEqual(restored.symbol, "TEST")
        self.assertAlmostEqual(restored.spot, 101.5)
        self.assertEqual(len(restored.quotes), 2)
        self.assertAlmostEqual(total_gex(restored), total_gex(original), places=6)

    def test_missing_spot_is_an_error(self):
        with self.assertRaises(ValueError):
            load_csv("expiry,strike,right,open_interest\n2026-04-01,100,C,10\n")

    def test_filters(self):
        c = chain(opt("C", 100, expiry=date(2026, 3, 6)), opt("C", 105, expiry=date(2026, 6, 19)))
        self.assertEqual(len(c.filtered(max_dte=10).quotes), 1)
        self.assertEqual(len(c.filtered(expiry=date(2026, 6, 19)).quotes), 1)
        self.assertEqual(len(c.filtered(min_oi=5000).quotes), 0)


class TestSampleChainEndToEnd(unittest.TestCase):
    def test_sample_chain_produces_a_full_snapshot(self):
        c = providers.from_csv(SAMPLE).filtered(min_oi=1)
        strikes = by_strike(c)
        snap = Snapshot(c, strikes, gamma_profile(c, range_pct=0.10, steps=161), "long_calls_short_puts")
        self.assertGreater(len(strikes), 50)
        self.assertIsNotNone(snap.flip)
        self.assertIsNotNone(snap.call_wall)
        self.assertIsNotNone(snap.put_wall)
        self.assertGreater(snap.call_wall.strike, c.spot)
        self.assertLess(snap.put_wall.strike, c.spot)
        self.assertIn("strike,call_gex", strikes_csv(snap))
        self.assertIn("Gamma flip", pine_inputs(snap))

    def test_sample_chain_is_deterministic(self):
        # as_of is pinned in the file, so the demo output must not drift with
        # the wall clock.
        c = providers.from_csv(SAMPLE)
        self.assertEqual(c.as_of, NOW)
        self.assertAlmostEqual(total_gex(c), total_gex(providers.from_csv(SAMPLE)))


if __name__ == "__main__":
    unittest.main()
