import pytest
from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import db


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("SKIP_CURVA_BOOTSTRAP", "1")
    data_dir = tmp_path / "data"
    csv_path = data_dir / "curva.csv"
    config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
        "DATA_DIR": str(data_dir),
        "CSV_PATH": str(csv_path),
        "SECRET_KEY": "test-secret",
        "TELEGRAM_BOT_MODE": "off",
        "DISABLE_SCHEDULER": True,
    }
    app = create_app(config)
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


def test_home_placeholder_rendered_when_csv_missing(app):
    client = app.test_client()
    response = client.get("/")
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Stiamo acquisendo i dati INGV" in body
