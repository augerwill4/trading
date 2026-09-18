"""Rate limiting, retry and backoff. No network: a fake session drives every path."""

import unittest

import requests

from gexlab.config import HttpConfig
from gexlab.http import PERMANENT_STATUS, RETRY_STATUS, FetchError, HttpClient, RateLimiter


class FakeResponse:
    def __init__(self, status=200, body=b"{}", headers=None):
        self.status_code = status
        self.content = body
        self.headers = headers or {}

    @property
    def ok(self):
        return 200 <= self.status_code < 300


class FakeSession:
    """Replays a scripted list of responses or exceptions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.headers = {}

    def get(self, url, timeout=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else FakeResponse()
        if isinstance(item, Exception):
            raise item
        return item


def client(script, **overrides):
    cfg = HttpConfig(requests_per_second=0, max_retries=3, backoff_base_seconds=0.01,
                     backoff_max_seconds=0.02, **overrides)
    slept = []
    c = HttpClient(cfg, session=FakeSession(script), sleep=slept.append)
    return c, slept


class TestRateLimiter(unittest.TestCase):
    def test_zero_rate_disables_waiting(self):
        self.assertEqual(RateLimiter(0).wait(), 0.0)

    def test_first_call_does_not_wait(self):
        self.assertEqual(RateLimiter(100).wait(), 0.0)

    def test_spacing_is_enforced_between_calls(self):
        limiter = RateLimiter(50)  # 20ms apart
        limiter.wait()
        self.assertGreaterEqual(limiter.min_interval, 0.02)


class TestRetries(unittest.TestCase):
    def test_success_on_first_try(self):
        c, slept = client([FakeResponse(200, b'{"a": 1}')])
        payload, meta = c.get_json("https://example.test/x")
        self.assertEqual(payload, {"a": 1})
        self.assertEqual(meta.attempts, 1)
        self.assertEqual(slept, [])

    def test_retries_then_succeeds(self):
        c, slept = client([FakeResponse(503), FakeResponse(503), FakeResponse(200, b'{"ok": true}')])
        payload, meta = c.get_json("https://example.test/x")
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(meta.attempts, 3)
        self.assertEqual(len(slept), 2)

    def test_gives_up_after_max_retries(self):
        c, _ = client([FakeResponse(503)] * 10)
        with self.assertRaises(FetchError) as ctx:
            c.get_raw("https://example.test/x")
        self.assertEqual(ctx.exception.attempts, 4)  # 1 initial + 3 retries

    def test_permanent_status_is_not_retried(self):
        c, slept = client([FakeResponse(404)])
        with self.assertRaises(FetchError) as ctx:
            c.get_raw("https://example.test/x")
        self.assertEqual(ctx.exception.attempts, 1)
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(slept, [])

    def test_connection_errors_are_retried(self):
        c, slept = client([requests.exceptions.ConnectionError("reset"), FakeResponse(200, b"{}")])
        _, meta = c.get_json("https://example.test/x")
        self.assertEqual(meta.attempts, 2)
        self.assertEqual(len(slept), 1)

    def test_proxy_block_is_reported_not_retried(self):
        c, slept = client([requests.exceptions.ProxyError("CONNECT 403")])
        with self.assertRaises(FetchError) as ctx:
            c.get_raw("https://example.test/x")
        self.assertTrue(ctx.exception.blocked_by_proxy)
        self.assertEqual(slept, [])

    def test_retry_after_header_is_honoured(self):
        c, slept = client([FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, b"{}")])
        c.get_json("https://example.test/x")
        self.assertEqual(slept, [7.0])

    def test_bad_json_is_an_error(self):
        c, _ = client([FakeResponse(200, b"not json")])
        with self.assertRaises(FetchError):
            c.get_json("https://example.test/x")

    def test_backoff_grows_and_is_capped(self):
        cfg = HttpConfig(backoff_base_seconds=2.0, backoff_max_seconds=10.0)
        c = HttpClient(cfg, session=FakeSession([]))
        # Full jitter: each delay is bounded by min(base * 2^(n-1), cap).
        for attempt, bound in ((1, 2.0), (2, 4.0), (3, 8.0), (4, 10.0), (9, 10.0)):
            for _ in range(20):
                self.assertLessEqual(c.backoff_delay(attempt), bound)

    def test_status_sets_do_not_overlap(self):
        self.assertFalse(RETRY_STATUS & PERMANENT_STATUS)


if __name__ == "__main__":
    unittest.main()
