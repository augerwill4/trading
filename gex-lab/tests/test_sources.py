"""Source parsing and schema diagnosis.

IMPORTANT CAVEAT: the payloads below are reconstructions of each provider's
schema, not recordings of live responses. They prove the parser and the doctor
diagnostics are internally consistent. They do NOT prove the schema is correct —
only running `doctor` against the live endpoint does that.
"""

import unittest

from gexlab.cache import ChainCache
from gexlab.config import HttpConfig
from gexlab.http import FetchError, HttpClient
from gexlab.sources import cboe, yahoo


def cboe_payload(n=4, **overrides):
    options = []
    for i in range(n):
        strike = 580 + i
        for right in ("C", "P"):
            options.append({
                "option": f"SPY260320{right}00{strike}000",
                "open_interest": 1000 + i,
                "iv": 0.18,
                "bid": 1.20,
                "ask": 1.30,
                "last_trade_price": 1.25,
                "volume": 500 + i,
                "delta": 0.5,
                "gamma": 0.02,
            })
    payload = {"timestamp": "2026-03-02T18:30:00", "data": {"current_price": 585.4,
               "close": 584.0, "options": options}}
    payload["data"].update(overrides)
    return payload


def yahoo_payload(truncated=False):
    rows_c = [{"contractSymbol": "SPY260320C00580000", "strike": 580.0, "bid": 1.2, "ask": 1.3,
               "lastPrice": 1.25, "volume": 500, "openInterest": 1000, "impliedVolatility": 0.18}]
    rows_p = [{"contractSymbol": "SPY260320P00580000", "strike": 580.0, "bid": 1.1, "ask": 1.2,
               "lastPrice": 1.15, "volume": 400, "openInterest": 900, "impliedVolatility": 0.20}]
    return {
        "ticker": "SPY", "spot": 585.4,
        "expirations_available": ["2026-03-20", "2026-04-17", "2026-05-15"],
        "expirations_fetched": ["2026-03-20"],
        "truncated": truncated,
        "chains": {"2026-03-20": {"calls": rows_c, "puts": rows_p}},
        "fetched_at": "2026-03-02T18:30:00+00:00",
    }


class TestCboeTickerMapping(unittest.TestCase):
    def test_equities_are_passed_through(self):
        self.assertEqual(cboe.api_ticker("SPY"), "SPY")
        self.assertEqual(cboe.api_ticker("tsla"), "TSLA")

    def test_indexes_get_the_underscore_prefix(self):
        self.assertEqual(cboe.api_ticker("SPX"), "_SPX")
        self.assertEqual(cboe.api_ticker("^VIX"), "_VIX")
        self.assertEqual(cboe.api_ticker("_RUT"), "_RUT")

    def test_url(self):
        self.assertTrue(cboe.url_for("SPX").endswith("/_SPX.json"))


class TestCboeParse(unittest.TestCase):
    def test_parses_a_well_formed_payload(self):
        chain = cboe.parse(cboe_payload(), "SPY")
        self.assertEqual(chain.symbol, "SPY")
        self.assertAlmostEqual(chain.spot, 585.4)
        self.assertEqual(len(chain.quotes), 8)
        self.assertEqual(len(chain.expiries), 1)
        self.assertTrue(all(q.implied_vol == 0.18 for q in chain.quotes))

    def test_falls_back_to_close_when_current_price_is_absent(self):
        payload = cboe_payload()
        del payload["data"]["current_price"]
        self.assertAlmostEqual(cboe.parse(payload, "SPY").spot, 584.0)

    def test_no_price_is_an_error(self):
        payload = cboe_payload()
        payload["data"].pop("current_price")
        payload["data"].pop("close")
        with self.assertRaises(FetchError):
            cboe.parse(payload, "SPY")

    def test_no_contracts_is_an_error(self):
        with self.assertRaises(FetchError):
            cboe.parse(cboe_payload(0), "SPY")

    def test_unparseable_symbols_are_skipped_and_counted(self):
        payload = cboe_payload()
        payload["data"]["options"].append({"option": "GARBAGE", "open_interest": 5})
        chain = cboe.parse(payload, "SPY")
        self.assertEqual(len(chain.quotes), 8)
        self.assertIn("1 unparseable", chain.source)

    def test_zero_quotes_become_none_not_zero(self):
        payload = cboe_payload(1)
        payload["data"]["options"][0]["bid"] = 0
        chain = cboe.parse(payload, "SPY")
        self.assertIsNone(chain.quotes[0].bid)


class TestCboeDescribe(unittest.TestCase):
    def test_clean_payload_reports_nothing_missing(self):
        d = cboe.describe(cboe_payload())
        self.assertEqual(d["missing_top"], [])
        self.assertEqual(d["missing_data"], [])
        self.assertEqual(d["missing_option"], [])
        self.assertEqual(d["contract_count"], 8)
        self.assertEqual(d["spot"], 585.4)

    def test_schema_drift_is_named(self):
        payload = cboe_payload()
        for row in payload["data"]["options"]:
            row["open_int"] = row.pop("open_interest")
        d = cboe.describe(payload)
        self.assertIn("open_interest", d["missing_option"])

    def test_survives_a_completely_wrong_payload(self):
        d = cboe.describe({"error": "not found"})
        self.assertIn("data", d["missing_top"])
        self.assertEqual(d["contract_count"], 0)

    def test_survives_a_non_dict_payload(self):
        self.assertEqual(cboe.describe([]), cboe.describe([]))  # does not raise

    def test_populated_counts_ignore_zeros(self):
        payload = cboe_payload(2)
        payload["data"]["options"][0]["volume"] = 0
        d = cboe.describe(payload)
        self.assertEqual(d["populated"]["volume"], 3)


class TestYahoo(unittest.TestCase):
    def test_parse(self):
        chain = yahoo.parse(yahoo_payload(), "SPY")
        self.assertEqual(len(chain.quotes), 2)
        self.assertAlmostEqual(chain.spot, 585.4)
        self.assertEqual({q.right for q in chain.quotes}, {"C", "P"})

    def test_truncation_is_recorded_in_the_source_string(self):
        chain = yahoo.parse(yahoo_payload(truncated=True), "SPY")
        self.assertIn("partial", chain.source)

    def test_nan_becomes_absent_not_zero(self):
        payload = yahoo_payload()
        payload["chains"]["2026-03-20"]["calls"][0]["impliedVolatility"] = float("nan")
        payload["chains"]["2026-03-20"]["calls"][0]["openInterest"] = float("nan")
        chain = yahoo.parse(payload, "SPY")
        call = next(q for q in chain.quotes if q.right == "C")
        self.assertIsNone(call.implied_vol)
        self.assertEqual(call.open_interest, 0)

    def test_describe_flags_truncation(self):
        d = yahoo.describe(yahoo_payload(truncated=True))
        self.assertTrue(d["truncated"])
        self.assertEqual(d["expirations_available"], 3)
        self.assertEqual(d["expirations_fetched"], 1)

    def test_no_price_is_an_error(self):
        payload = yahoo_payload()
        payload["spot"] = None
        with self.assertRaises(FetchError):
            yahoo.parse(payload, "SPY")


class TestCacheIntegration(unittest.TestCase):
    def test_second_fetch_same_day_does_not_hit_the_network(self):
        import tempfile
        from pathlib import Path

        class ExplodingSession:
            headers = {}

            def get(self, url, timeout=None):
                raise AssertionError("network was called despite a warm cache")

        with tempfile.TemporaryDirectory() as tmp:
            cache = ChainCache(Path(tmp))
            cache.put("cboe", "SPY", cboe_payload())
            client = HttpClient(HttpConfig(requests_per_second=0), session=ExplodingSession())
            payload, meta = cboe.fetch_raw("SPY", client, cache)
            self.assertTrue(meta.from_cache)
            self.assertEqual(payload["data"]["current_price"], 585.4)


if __name__ == "__main__":
    unittest.main()
