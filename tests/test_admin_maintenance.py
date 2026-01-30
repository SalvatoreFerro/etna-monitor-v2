import os

import pytest
from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import db
from app.models.user import User


os.environ.setdefault("SECRET_KEY", "test-secret-key")


@pytest.fixture()
def app(tmp_path):
    static_root = tmp_path / "static"
    static_root.mkdir()

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
            "STATIC_FOLDER": str(static_root),
        }
    )

    with app.app_context():
        db.create_all()
        admin = User(email="admin@example.com", is_admin=True)
        regular = User(email="user@example.com")
        db.session.add_all([admin, regular])
        db.session.commit()
        yield app
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_user(app):
    with app.app_context():
        return User.query.filter_by(email="admin@example.com").first()


@pytest.fixture()
def regular_user(app):
    with app.app_context():
        return User.query.filter_by(email="user@example.com").first()


def test_admin_home_requires_admin(client, regular_user):
    with client.session_transaction() as session:
        session["user_id"] = regular_user.id

    response = client.get("/admin/")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_recompute_badges_ui_admin_success(
    client, admin_user, regular_user, monkeypatch
):
    calls = []

    def fake_recompute(user_id):
        calls.append(user_id)

    monkeypatch.setattr(
        "app.routes.admin.recompute_badges_for_user", fake_recompute
    )

    with client.session_transaction() as session:
        session["_csrf_token"] = "csrf-token"
        session["user_id"] = admin_user.id

    response = client.post(
        "/admin/recompute-badges-ui",
        data={"csrf_token": "csrf-token", "user_id": str(regular_user.id)},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert regular_user.id in calls
    assert "Badge ricalcolati per" in response.get_data(as_text=True)
