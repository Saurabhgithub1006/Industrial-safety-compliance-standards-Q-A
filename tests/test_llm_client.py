"""Tests for the retry/backoff helper in llm_client.py -- the real robustness gap
found by reviewing the project for optimization opportunities: an unhandled
RateLimitError was observed directly during manual testing (this project's Kimi
account is capped at 3 requests/minute), and neither real client had any handling
for it beyond the SDK's own defaults. `call_with_retry` is pure and provider-agnostic,
so it's fully testable without real credentials or real waiting -- `time.sleep` is
mocked throughout so these tests run instantly rather than actually backing off.
"""

from __future__ import annotations

import pytest

from safety_qa.generation.llm_client import call_with_retry


class _RetryableError(Exception):
    pass


class _OtherError(Exception):
    pass


def test_succeeds_immediately_without_retrying(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    result = call_with_retry(lambda: "ok", (_RetryableError,))

    assert result == "ok"
    assert sleeps == []


def test_retries_on_retryable_exception_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _RetryableError("rate limited")
        return "eventually ok"

    result = call_with_retry(flaky, (_RetryableError,), max_attempts=4, base_delay=5.0)

    assert result == "eventually ok"
    assert attempts["n"] == 3
    assert sleeps == [5.0, 10.0]  # exponential: base_delay * 2**attempt, one sleep per failed attempt


def test_raises_after_exhausting_all_attempts(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)

    def always_fails():
        raise _RetryableError("still rate limited")

    with pytest.raises(_RetryableError, match="still rate limited"):
        call_with_retry(always_fails, (_RetryableError,), max_attempts=3, base_delay=1.0)


def test_non_retryable_exception_propagates_immediately(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    attempts = {"n": 0}

    def fails_differently():
        attempts["n"] += 1
        raise _OtherError("not the kind we retry")

    with pytest.raises(_OtherError):
        call_with_retry(fails_differently, (_RetryableError,), max_attempts=4)

    assert attempts["n"] == 1  # never retried
    assert sleeps == []


def test_backoff_is_exponential(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))

    def always_fails():
        raise _RetryableError()

    with pytest.raises(_RetryableError):
        call_with_retry(always_fails, (_RetryableError,), max_attempts=5, base_delay=2.0)

    assert sleeps == [2.0, 4.0, 8.0, 16.0]  # 4 sleeps between 5 attempts
