import json
import os

import pandas as pd
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app import create_app


@pytest.fixture()
def client(tmp_path):
    csv_path = tmp_path / "curva.csv"

    app = create_app()
    app.config["TESTING"] = True
    app.config["CURVA_CSV_PATH"] = str(csv_path)

    with app.test_client() as test_client:
        yield test_client, csv_path


def test_curva_endpoint_serializes_iso_utc(client):
    test_client, csv_path = client
    df = pd.DataFrame(
        {
            "timestamp": [
                "2025-01-01T10:00:00Z",
                "2025-01-01T10:05:00Z",
            ],
            "value": [1.2, 3.4],
        }
    )
    df.to_csv(csv_path, index=False)

    response = test_client.get("/api/curva")
    assert response.status_code == 200

    payload = json.loads(response.data)
    assert payload["ok"] is True
    assert payload["last_ts"].endswith("Z")
    assert payload["rows"] == 2
    timestamps = [row["timestamp"] for row in payload["data"]]
    assert all(ts.endswith("Z") for ts in timestamps)


def test_status_endpoint_serializes_iso_utc(client):
    test_client, csv_path = client
    df = pd.DataFrame(
        {
            "timestamp": [
                "2025-01-02T00:00:00Z",
                "2025-01-02T00:05:00Z",
            ],
            "value": [0.5, 0.8],
        }
    )
    df.to_csv(csv_path, index=False)

    response = test_client.get("/api/status")
    assert response.status_code == 200

    payload = json.loads(response.data)
    assert payload["ok"] is True
    assert payload["last_update"].endswith("Z")
    assert payload["total_points"] == 2
