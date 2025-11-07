from app import create_app


def test_ga_diag_reports_measurement_id(monkeypatch):
    monkeypatch.setenv("GA_MEASUREMENT_ID", "G-TEST123456")
    app = create_app({"TESTING": True})
    client = app.test_client()

    response = client.get("/__ga_diag")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "G-TEST123456" in html

    # Cleanup to avoid leaking to other tests
    monkeypatch.delenv("GA_MEASUREMENT_ID", raising=False)
