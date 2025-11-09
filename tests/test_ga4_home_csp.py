import re
from typing import Dict, List

from app import create_app


def _parse_csp_header(header: str) -> Dict[str, List[str]]:
    directives: Dict[str, List[str]] = {}
    for part in header.split(";"):
        part = part.strip()
        if not part:
            continue
        segments = part.split()
        if not segments:
            continue
        directives[segments[0]] = segments[1:]
    return directives


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

    csp_header = response.headers.get("Content-Security-Policy", "")
    directives = _parse_csp_header(csp_header)

    script_sources = directives.get("script-src", [])
    script_elem_sources = directives.get("script-src-elem", [])
    assert "script-src-elem" in directives
    for domain in (
        "https://www.googletagmanager.com",
        "https://www.google-analytics.com",
    ):
        assert domain in script_sources
        assert domain in script_elem_sources

    style_sources = directives.get("style-src", [])
    style_elem_sources = directives.get("style-src-elem", [])
    assert "style-src-elem" in directives
    assert "https://cdnjs.cloudflare.com" in style_sources
    assert "https://fonts.googleapis.com" in style_sources
    assert style_elem_sources == style_sources

    connect_sources = directives.get("connect-src", [])
    assert "https://region1.google-analytics.com" in connect_sources
    assert "https://stats.g.doubleclick.net" in connect_sources


def test_ga4_test_csp_endpoint(monkeypatch):
    monkeypatch.setenv("GA_ENABLE", "true")
    app = create_app({"TESTING": True})
    client = app.test_client()

    response = client.get("/ga4/test-csp")
    assert response.status_code == 200
    payload = response.get_json()
    assert "csp" in payload
    policy = payload["csp"]
    script_sources = policy.get("script-src", [])
    script_elem_sources = policy.get("script-src-elem", [])
    assert "https://www.googletagmanager.com" in script_sources
    assert "https://www.google-analytics.com" in script_sources
    assert script_elem_sources == script_sources

    style_sources = policy.get("style-src", [])
    assert "https://cdnjs.cloudflare.com" in style_sources
    assert "https://fonts.googleapis.com" in style_sources

    connect_sources = policy.get("connect-src", [])
    assert "https://region1.google-analytics.com" in connect_sources
    assert "https://stats.g.doubleclick.net" in connect_sources
