import os
from datetime import datetime, timezone

import pytest
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("TELEGRAM_BOT_MODE", "off")

from app import create_app
from app.models import db
from app.models.partner import Partner


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


def test_experience_handles_empty_database(client):
    response = client.get("/experience")
    assert response.status_code == 200
    assert "Nessun partner disponibile" in response.get_data(as_text=True)


def test_experience_orders_and_filters_partners(client, app):
    with app.app_context():
        db.session.add_all(
            [
                Partner(
                    name="Hidden Partner",
                    category="Guide",
                    verified=True,
                    visible=False,
                ),
                Partner(
                    name="Visible Veteran",
                    category="Guide",
                    verified=True,
                    visible=True,
                    created_at=datetime(2024, 7, 1, tzinfo=timezone.utc),
                ),
                Partner(
                    name="Recent Arrival",
                    category="Guide",
                    verified=False,
                    visible=True,
                    created_at=datetime(2024, 7, 15, tzinfo=timezone.utc),
                ),
            ]
        )
        db.session.commit()

    response = client.get("/experience")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Hidden Partner" not in body
    assert body.index("Visible Veteran") < body.index("Recent Arrival")
