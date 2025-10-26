from __future__ import annotations

from typing import List

from alerts import notifier


class DummyResponse:
    def __init__(self, status_code: int, *, headers=None):
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise notifier.requests.HTTPError(response=self)


def test_send_telegram_alert_success(monkeypatch):
    calls = []

    def fake_post(url, json, timeout):  # noqa: A002 - signature required by requests
        calls.append((url, json, timeout))
        return DummyResponse(200)

    monkeypatch.setattr(notifier, "requests", notifier.requests)
    monkeypatch.setattr(notifier.requests, "post", fake_post)

    assert notifier.send_telegram_alert("token", "123", "ciao") is True
    assert calls


def test_send_telegram_alert_rate_limit_then_success(monkeypatch):
    responses: List[DummyResponse] = [
        DummyResponse(429, headers={"Retry-After": "0"}),
        DummyResponse(200),
    ]

    def fake_post(url, json, timeout):
        return responses.pop(0)

    monkeypatch.setattr(notifier.requests, "post", fake_post)
    monkeypatch.setattr(notifier.time, "sleep", lambda *_: None)

    assert notifier.send_telegram_alert("token", "123", "ciao") is True


def test_send_telegram_alert_failure(monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", lambda *_, **__: DummyResponse(500))
    monkeypatch.setattr(notifier.time, "sleep", lambda *_: None)

    assert notifier.send_telegram_alert("token", "123", "ciao") is False


def test_send_telegram_alert_missing_token():
    assert notifier.send_telegram_alert("", "123", "ciao") is False
    assert notifier.send_telegram_alert("token", "", "ciao") is False
