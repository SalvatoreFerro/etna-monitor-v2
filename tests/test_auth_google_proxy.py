import os
from unittest.mock import Mock

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")

import pytest
import requests
from sqlalchemy.pool import StaticPool

from app import create_app
from app.routes import auth


@pytest.fixture(scope="module")
def app_context():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
        }
    )

    with app.app_context():
        yield app


def test_google_request_proxy_fallback(monkeypatch, app_context):
    responses = []
    success_response = Mock(spec=requests.Response)

    class DummySession:
        def __init__(self, idx: int):
            self.idx = idx
            self.closed = False
            self.trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.closed = True

        def request(self, method, url, **kwargs):
            responses.append((self.idx, self.trust_env))
            if self.idx == 0:
                raise requests.exceptions.ProxyError("blocked")
            return success_response

    sessions = []

    def session_factory():
        session = DummySession(len(sessions))
        sessions.append(session)
        return session

    monkeypatch.setattr(auth, "Session", session_factory)

    resp = auth._google_oauth_request("GET", "https://example.com")

    assert resp is success_response
    assert len(sessions) == 2
    assert sessions[0].closed is True
    assert sessions[0].trust_env is True
    assert sessions[1].closed is True
    assert sessions[1].trust_env is False
    assert responses == [(0, True), (1, False)]


def test_google_request_proxy_success_without_retry(monkeypatch, app_context):
    success_response = Mock(spec=requests.Response)

    class DummySession:
        def __init__(self):
            self.closed = False
            self.trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.closed = True

        def request(self, method, url, **kwargs):
            return success_response

    sessions = []

    def session_factory():
        session = DummySession()
        sessions.append(session)
        return session

    monkeypatch.setattr(auth, "Session", session_factory)

    resp = auth._google_oauth_request("GET", "https://example.com")

    assert resp is success_response
    assert len(sessions) == 1
    assert sessions[0].closed is True
    assert sessions[0].trust_env is True


def test_google_request_proxy_fallback_failure(monkeypatch, app_context):
    class DummySession:
        def __init__(self, idx: int):
            self.idx = idx
            self.closed = False
            self.trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.closed = True

        def request(self, method, url, **kwargs):
            if self.idx == 0:
                raise requests.exceptions.ProxyError("blocked")
            raise requests.exceptions.ConnectionError("down")

    sessions = []

    def session_factory():
        session = DummySession(len(sessions))
        sessions.append(session)
        return session

    monkeypatch.setattr(auth, "Session", session_factory)

    with pytest.raises(requests.exceptions.ConnectionError):
        auth._google_oauth_request("GET", "https://example.com")

    assert len(sessions) == 2
    assert all(session.closed for session in sessions)
    assert sessions[0].trust_env is True
    assert sessions[1].trust_env is False
