import unittest

from gexlab import blackscholes as bs


class TestGamma(unittest.TestCase):
    def test_known_value(self):
        # S=K=100, T=1y, vol=20%, r=q=0 -> phi(0.1) / (100 * 0.2)
        self.assertAlmostEqual(bs.gamma(100, 100, 1.0, 0.2), 0.019847627, places=8)

    def test_call_and_put_gamma_are_identical(self):
        # Put-call parity is linear in spot, so its second derivative vanishes.
        # This is the identity the whole strike-bucketing approach rests on.
        for k in (80, 100, 125):
            g = bs.gamma(100, k, 0.5, 0.25, r=0.04, q=0.01)
            c = bs.price("C", 100, k, 0.5, 0.25, 0.04, 0.01)
            p = bs.price("P", 100, k, 0.5, 0.25, 0.04, 0.01)
            h = 1e-3
            second = lambda f: (f(100 + h) - 2 * f(100) + f(100 - h)) / (h * h)
            num_c = second(lambda s: bs.price("C", s, k, 0.5, 0.25, 0.04, 0.01))
            num_p = second(lambda s: bs.price("P", s, k, 0.5, 0.25, 0.04, 0.01))
            self.assertAlmostEqual(num_c, num_p, places=6)
            self.assertAlmostEqual(g, num_c, places=5)
            self.assertGreater(c + p, 0)

    def test_peaks_near_the_money(self):
        atm = bs.gamma(100, 100, 0.08, 0.2)
        self.assertGreater(atm, bs.gamma(100, 120, 0.08, 0.2))
        self.assertGreater(atm, bs.gamma(100, 80, 0.08, 0.2))

    def test_short_dated_atm_gamma_dominates(self):
        self.assertGreater(bs.gamma(100, 100, 1 / 365, 0.2), bs.gamma(100, 100, 90 / 365, 0.2))

    def test_degenerate_inputs_return_zero(self):
        for args in ((0, 100, 1, 0.2), (100, 0, 1, 0.2), (100, 100, 0, 0.2), (100, 100, 1, 0)):
            self.assertEqual(bs.gamma(*args), 0.0)


class TestImpliedVol(unittest.TestCase):
    def test_round_trip(self):
        for right in ("C", "P"):
            for k in (90, 100, 115):
                px = bs.price(right, 100, k, 0.5, 0.35, 0.04, 0.01)
                self.assertAlmostEqual(bs.implied_vol(px, right, 100, k, 0.5, 0.04, 0.01), 0.35, places=5)

    def test_unsolvable_prices_return_none(self):
        self.assertIsNone(bs.implied_vol(0.0, "C", 100, 100, 0.5))
        self.assertIsNone(bs.implied_vol(5.0, "C", 100, 100, 0.0))
        self.assertIsNone(bs.implied_vol(99.0, "C", 100, 100, 0.5))  # above any arbitrage-free value


if __name__ == "__main__":
    unittest.main()
