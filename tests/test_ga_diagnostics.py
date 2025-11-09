from app import create_app


def test_ga_diag_includes_dbg_link_and_status():
    app = create_app({"TESTING": True})
    client = app.test_client()

    response = client.get("/ga4/diagnostics")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "?dbg=1" in html
    assert "DataLayer length" in html
