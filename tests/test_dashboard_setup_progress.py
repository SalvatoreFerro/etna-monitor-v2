import os

import pytest
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from app import create_app
from app.models import db
from app.models.user import User


@pytest.fixture
def app():
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
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    with app.test_client() as client:
        yield client


def _create_user(email="user@example.com"):
    user = User(email=email)
    db.session.add(user)
    db.session.commit()
    return user.id


def test_logged_in_cta_targets_dashboard_and_pricing(client, app):
    with app.app_context():
        user_id = _create_user()

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    response = client.get("/")
    assert response.status_code == 200
    assert b"Vai alla Dashboard" in response.data
    assert b"/auth/login" not in response.data

    response = client.get("/etna-bot")
    assert response.status_code == 200
    assert b"Passa a Premium" in response.data
    assert b"/auth/login" not in response.data


def test_connect_telegram_requires_csrf(client, app):
    with app.app_context():
        user_id = _create_user("telegram@example.com")

    with client.session_transaction() as sess:
        sess["user_id"] = user_id

    response = client.post("/dashboard/telegram/connect", data={"chat_id": "123456"})
    assert response.status_code == 302

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.telegram_chat_id is None
        assert user.chat_id is None

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["_csrf_token"] = "csrf-token"

    response = client.post(
        "/dashboard/telegram/connect",
        data={"chat_id": "123456", "csrf_token": "csrf-token"},
    )
    assert response.status_code == 302

    with app.app_context():
        user = db.session.get(User, user_id)
        assert user.telegram_chat_id == 123456
        assert user.chat_id == 123456
