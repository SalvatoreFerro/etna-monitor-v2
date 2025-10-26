from alerts import notifier


class DummyResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):  # pragma: no cover - kept for legacy test
        if self.status_code >= 400:
            raise notifier.requests.HTTPError(response=self)


def test_send_telegram_alert_mock(monkeypatch):
    monkeypatch.setattr(notifier.requests, "post", lambda *_, **__: DummyResponse())
    monkeypatch.setattr(notifier.time, "sleep", lambda *_: None)

    assert notifier.send_telegram_alert("token", "123", "ciao") is True
    assert notifier.send_telegram_alert("", "123", "ciao") is False
    assert notifier.send_telegram_alert("token", "", "ciao") is False
