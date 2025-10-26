import os

import pytest
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("TELEGRAM_BOT_MODE", "off")
os.environ.setdefault("GOOGLE_CLIENT_ID", "client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "client-secret")

from app import create_app
from app.models import db
from app.models.user import User


@pytest.fixture(autouse=True)
def reset_google_id_cache():
    from app.routes import auth as auth_routes

    auth_routes._GOOGLE_ID_COLUMN_SUPPORTED = None
    auth_routes._PLAN_TYPE_COLUMN_READY = None
    yield
    auth_routes._GOOGLE_ID_COLUMN_SUPPORTED = None
    auth_routes._PLAN_TYPE_COLUMN_READY = None


class DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.fixture
def app(monkeypatch):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
            "GOOGLE_CLIENT_ID": os.environ["GOOGLE_CLIENT_ID"],
            "GOOGLE_CLIENT_SECRET": os.environ["GOOGLE_CLIENT_SECRET"],
        }
    )

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    with app.test_client() as client:
        yield client


def test_google_callback_creates_user(monkeypatch, client, app):
    token_response = DummyResponse(200, {"access_token": "access", "refresh_token": "refresh"})
    userinfo_response = DummyResponse(
        200,
        {
            "sub": "google-user",
            "email": "new-user@example.com",
            "name": "Example User",
            "picture": "https://example.com/pic.png",
        },
    )

    responses = iter([token_response, userinfo_response])

    def fake_google_request(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr("app.routes.auth._google_oauth_request", fake_google_request)

    with client.session_transaction() as session:
        session["oauth_state"] = "state-token"

    response = client.get("/auth/callback?code=auth-code&state=state-token")
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]

    with client.session_transaction() as session:
        assert session.get("user_id") is not None

    with app.app_context():
        user = User.query.filter_by(google_id="google-user").one()
        assert user.email == "new-user@example.com"
        assert user.plan_type == "free"


def test_google_callback_handles_missing_google_id(monkeypatch, client, app):
    from sqlalchemy.exc import ProgrammingError

    token_response = DummyResponse(200, {"access_token": "access"})
    userinfo_response = DummyResponse(
        200,
        {
            "sub": "legacy-google-user",
            "email": "legacy-user@example.com",
            "name": "Legacy User",
        },
    )

    responses = iter([token_response, userinfo_response])

    def fake_google_request(*args, **kwargs):
        return next(responses)

    from app.routes import auth as auth_routes

    monkeypatch.setattr("app.routes.auth._google_oauth_request", fake_google_request)

    original_query_with_retry = auth_routes._query_with_retry

    def fake_query_with_retry(query_callable):
        if "google_id" in getattr(query_callable.__code__, "co_freevars", ()):  # pragma: no cover - guard
            raise ProgrammingError("SELECT", {}, Exception("missing column"))
        return original_query_with_retry(query_callable)

    monkeypatch.setattr(auth_routes, "_query_with_retry", fake_query_with_retry)

    with client.session_transaction() as session:
        session["oauth_state"] = "state-token"

    response = client.get("/auth/callback?code=auth-code&state=state-token")
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]

    with app.app_context():
        user = User.query.filter_by(email="legacy-user@example.com").one()
        assert user.google_id is None


def test_google_callback_heals_missing_plan_type(monkeypatch, client, app):
    from sqlalchemy.exc import ProgrammingError

    token_response = DummyResponse(200, {"access_token": "access"})
    userinfo_response = DummyResponse(
        200,
        {
            "sub": "plan-type-user",
            "email": "plan-type@example.com",
            "name": "Plan Type",
        },
    )

    responses = iter([token_response, userinfo_response])

    def fake_google_request(*args, **kwargs):
        return next(responses)

    from app.routes import auth as auth_routes

    monkeypatch.setattr("app.routes.auth._google_oauth_request", fake_google_request)

    ensure_calls: list[bool] = []

    def fake_ensure(force_refresh: bool = False) -> bool:
        ensure_calls.append(force_refresh)
        return True

    monkeypatch.setattr(auth_routes, "_ensure_plan_type_column", fake_ensure)

    original_query_with_retry = auth_routes._query_with_retry

    call_state = {"count": 0}

    def flaky_query(query_callable):
        if call_state["count"] == 0:
            call_state["count"] += 1
            raise ProgrammingError(
                "SELECT",
                {},
                Exception("column users.plan_type does not exist"),
            )
        return original_query_with_retry(query_callable)

    monkeypatch.setattr(auth_routes, "_query_with_retry", flaky_query)

    with client.session_transaction() as session:
        session["oauth_state"] = "state-token"

    response = client.get("/auth/callback?code=auth-code&state=state-token")
    assert response.status_code == 302
    assert "/dashboard" in response.headers["Location"]

    assert ensure_calls == [True]

    with app.app_context():
        user = User.query.filter_by(email="plan-type@example.com").one()
        assert user.plan_type == "free"
