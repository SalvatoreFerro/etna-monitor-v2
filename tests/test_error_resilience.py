import os

import pytest
from flask import session
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app import create_app
from app.models import db
from app.models.user import User
from app.utils.auth import get_current_user


@pytest.fixture()
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
            "STATIC_FOLDER": str(tmp_path),
            "PROPAGATE_EXCEPTIONS": False,
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_get_current_user_recovers_from_programming_error(app, monkeypatch):
    with app.app_context():
        user = User(email="resilient@example.com", name="Resilient")
        db.session.add(user)
        db.session.commit()
        user_id = user.id

    with app.test_request_context("/"):
        session["user_id"] = user_id

        def failing_get(*args, **kwargs):
            raise ProgrammingError("SELECT *", {}, Exception("boom"))

        monkeypatch.setattr(db.session, "get", failing_get)

        user = get_current_user()

        assert user is not None
        assert user.id == user_id


def test_internal_error_handler_resets_session_state(app):
    @app.route("/broken")
    def broken_route():
        db.session.execute(text("SELECT * FROM table_that_does_not_exist"))
        return "never reached"

    client = app.test_client()
    response = client.get("/broken")
    assert response.status_code == 500

    with app.app_context():
        # The session should be usable again after the error handler ran.
        db.session.execute(text("SELECT 1"))
