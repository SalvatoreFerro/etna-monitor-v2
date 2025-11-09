import re

from app import create_app


def test_home_includes_ga4_and_csp_allows_google(monkeypatch):
    monkeypatch.setenv("GA_ENABLE", "true")
    app = create_app({"TESTING": True})
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    external_tag = (
        '<script async crossorigin="anonymous" '
        'src="https://www.googletagmanager.com/gtag/js?id=G-Z3ESSERP7W"></script>'
    )
    assert external_tag in html

    inline_match = re.search(
        r"<script nonce=\"[^\"]+\">[\s\S]*?gtag\('config','G-Z3ESSERP7W'",
        html,
    )
    assert inline_match is not None
    assert html.find(external_tag) < inline_match.start()

    csp = response.headers.get("Content-Security-Policy", "")
    assert "https://www.googletagmanager.com" in csp
    assert "https://www.googletagmanager.com/gtag/js" in csp
    assert "https://region1.google-analytics.com" in csp
    assert "https://stats.g.doubleclick.net" in csp


def test_ga4_test_csp_endpoint(monkeypatch):
    monkeypatch.setenv("GA_ENABLE", "true")
    app = create_app({"TESTING": True})
    client = app.test_client()

    response = client.get("/ga4/test-csp")
    assert response.status_code == 200
    payload = response.get_json()
    assert "csp" in payload
    script_sources = payload["csp"].get("script-src", [])
    assert "https://www.googletagmanager.com" in script_sources
    assert "https://www.googletagmanager.com/gtag/js" in script_sources
    assert "https://www.google-analytics.com" in script_sources
