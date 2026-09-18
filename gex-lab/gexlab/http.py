"""Polite HTTP: rate limiting, retry with exponential backoff, typed failures.

CLAUDE.md requires we never hammer a free endpoint. Two mechanisms enforce that:
a minimum interval between requests (RateLimiter), and a backoff that grows on
every failure instead of retrying immediately. Permanent failures are not
retried at all — retrying a 404 just wastes someone else's bandwidth.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import requests

from .config import HttpConfig

USER_AGENT = "gex-lab/0.2 (personal options research; single-user, low volume)"

# Worth retrying: the server asked us to slow down, or it broke transiently.
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
# Not worth retrying: the answer will not change.
PERMANENT_STATUS = {400, 401, 403, 404, 405, 410, 451}


class FetchError(Exception):
    """A request that did not produce a usable response."""

    def __init__(self, url: str, reason: str, *, status: int | None = None,
                 attempts: int = 1, blocked_by_proxy: bool = False):
        super().__init__(f"{reason} ({url})")
        self.url = url
        self.reason = reason
        self.status = status
        self.attempts = attempts
        self.blocked_by_proxy = blocked_by_proxy


@dataclass
class FetchMeta:
    url: str
    status: int | None = None
    bytes: int = 0
    seconds: float = 0.0
    attempts: int = 1
    from_cache: bool = False
    notes: list[str] = field(default_factory=list)


class RateLimiter:
    """Minimum wall-clock spacing between requests. Not thread-safe by design —
    this tool is deliberately single-threaded so it cannot burst."""

    def __init__(self, per_second: float):
        self.min_interval = 1.0 / per_second if per_second > 0 else 0.0
        self._last = 0.0

    def wait(self) -> float:
        if self.min_interval <= 0:
            return 0.0
        delay = self._last + self.min_interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            delay = 0.0
        self._last = time.monotonic()
        return delay


class HttpClient:
    def __init__(self, cfg: HttpConfig, *, session: requests.Session | None = None,
                 sleep=time.sleep):
        self.cfg = cfg
        self.limiter = RateLimiter(cfg.requests_per_second)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._sleep = sleep

    def backoff_delay(self, attempt: int) -> float:
        """Exponential with full jitter, capped. attempt is 1-based."""
        raw = self.cfg.backoff_base_seconds * (2 ** (attempt - 1))
        return random.uniform(0.0, min(raw, self.cfg.backoff_max_seconds))

    def get_json(self, url: str) -> tuple[dict, FetchMeta]:
        payload, meta = self.get_raw(url)
        try:
            import json

            return json.loads(payload), meta
        except ValueError as exc:
            raise FetchError(url, f"response was not valid JSON: {exc}",
                             status=meta.status, attempts=meta.attempts) from exc

    def get_raw(self, url: str) -> tuple[bytes, FetchMeta]:
        meta = FetchMeta(url=url)
        started = time.monotonic()
        last_reason = "no attempt made"

        for attempt in range(1, self.cfg.max_retries + 2):
            meta.attempts = attempt
            self.limiter.wait()
            try:
                resp = self.session.get(url, timeout=self.cfg.timeout_seconds)
            except requests.exceptions.ProxyError as exc:
                # A CONNECT rejected by an egress proxy. Distinct from the remote
                # host refusing us, and never worth retrying.
                meta.seconds = time.monotonic() - started
                raise FetchError(url, f"blocked by the outbound proxy: {exc}",
                                 attempts=attempt, blocked_by_proxy=True) from exc
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                last_reason = f"{type(exc).__name__}: {exc}"
                if attempt > self.cfg.max_retries:
                    break
                wait = self.backoff_delay(attempt)
                meta.notes.append(f"attempt {attempt}: {type(exc).__name__}, retrying in {wait:.1f}s")
                self._sleep(wait)
                continue

            meta.status = resp.status_code
            if resp.ok:
                meta.bytes = len(resp.content)
                meta.seconds = time.monotonic() - started
                return resp.content, meta

            if resp.status_code in PERMANENT_STATUS:
                meta.seconds = time.monotonic() - started
                raise FetchError(url, f"HTTP {resp.status_code} (not retryable)",
                                 status=resp.status_code, attempts=attempt)

            last_reason = f"HTTP {resp.status_code}"
            if resp.status_code not in RETRY_STATUS or attempt > self.cfg.max_retries:
                break

            wait = self._retry_after(resp) or self.backoff_delay(attempt)
            meta.notes.append(f"attempt {attempt}: HTTP {resp.status_code}, retrying in {wait:.1f}s")
            self._sleep(wait)

        meta.seconds = time.monotonic() - started
        raise FetchError(url, f"gave up after {meta.attempts} attempts — last: {last_reason}",
                         status=meta.status, attempts=meta.attempts)

    @staticmethod
    def _retry_after(resp: requests.Response) -> float | None:
        """Honour Retry-After when the server sends it. It is a direct request
        to back off and ignoring it is how you get blocked."""
        raw = resp.headers.get("Retry-After")
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            return None
