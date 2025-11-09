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
    external_match = re.search(
        r"<script[^>]+src=\"https://www\.googletagmanager\.com/gtag/js\?id=G-Z3ESSERP7W\"[^>]*></script>",
        html,
    )
    assert external_match is not None
    assert "async" in external_match.group(0)

    inline_match = re.search(
        r"<script nonce=\"[^\"]+\">[\s\S]*?gtag\('config','G-Z3ESSERP7W'",
        html,
    )
    assert inline_match is not None
    assert 'nonce="' in inline_match.group(0)

    assert html.index(external_match.group(0)) < html.index(inline_match.group(0))
    assert "gtag('config','AW-17681413584')" in html

    csp_header = response.headers.get("Content-Security-Policy", "")
    assert "'nonce-" in csp_header
    assert "googletagmanager.com" in csp_header
    assert "google-analytics.com" in csp_header
    assert "region1.google-analytics.com" in csp_header
    assert "doubleclick.net" in csp_header
    for expected in (
        "script-src-elem",
        "style-src-elem",
        "https://www.googletagmanager.com",
        "https://www.google-analytics.com",
        "https://*.googletagmanager.com",
        "https://*.google-analytics.com",
        "https://*.doubleclick.net",
        "https://*.google.com",
        "https://*.gstatic.com",
        "https://fonts.googleapis.com",
        "https://fonts.gstatic.com",
        "https://cdnjs.cloudflare.com",
        "https://cdn.plot.ly",
        "https://region1.google-analytics.com",
        "https://stats.g.doubleclick.net",
    ):
        assert expected in csp_header

    directives = _parse_csp_header(csp_header)

    script_sources = directives.get("script-src", [])
    script_elem_sources = directives.get("script-src-elem", [])
    assert "script-src-elem" in directives
    for domain in (
        "https://www.googletagmanager.com",
        "https://*.googletagmanager.com",
        "https://www.google-analytics.com",
        "https://*.google-analytics.com",
        "https://*.doubleclick.net",
        "https://*.google.com",
        "https://*.gstatic.com",
        "https://cdn.plot.ly",
    ):
        assert domain in script_sources
        assert domain in script_elem_sources

    style_sources = directives.get("style-src", [])
    style_elem_sources = directives.get("style-src-elem", [])
    assert "style-src-elem" in directives
    assert "https://cdnjs.cloudflare.com" in style_sources
    assert "https://fonts.googleapis.com" in style_sources
    assert style_elem_sources == style_sources
    assert "'unsafe-inline'" in style_sources

    connect_sources = directives.get("connect-src", [])
    assert "https://region1.google-analytics.com" in connect_sources
    assert "https://stats.g.doubleclick.net" in connect_sources
    assert "https://*.doubleclick.net" in connect_sources
    assert "https://*.googletagmanager.com" in connect_sources
    assert "https://*.google.com" in connect_sources
    assert "https://*.gstatic.com" in connect_sources


def _strip_nonces(values: List[str]) -> List[str]:
    return [value for value in values if not value.startswith("'nonce-")]


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
    for domain in (
        "https://www.googletagmanager.com",
        "https://*.googletagmanager.com",
        "https://www.google-analytics.com",
        "https://*.google-analytics.com",
        "https://*.doubleclick.net",
        "https://*.google.com",
        "https://*.gstatic.com",
        "https://cdn.plot.ly",
    ):
        assert domain in script_sources
    assert script_elem_sources == script_sources

    style_sources = policy.get("style-src", [])
    assert "https://cdnjs.cloudflare.com" in style_sources
    assert "https://fonts.googleapis.com" in style_sources
    assert "'unsafe-inline'" in style_sources

    connect_sources = policy.get("connect-src", [])
    assert "https://region1.google-analytics.com" in connect_sources
    assert "https://stats.g.doubleclick.net" in connect_sources
    assert "https://*.doubleclick.net" in connect_sources
    assert "https://*.googletagmanager.com" in connect_sources
    assert "https://*.google.com" in connect_sources
    assert "https://*.gstatic.com" in connect_sources


def test_csp_test_endpoint_returns_home_header(monkeypatch):
    monkeypatch.setenv("GA_ENABLE", "true")
    app = create_app({"TESTING": True})
    client = app.test_client()

    response = client.get("/csp/test")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status_code"] == 200
    header_value = payload["content_security_policy"]
    assert isinstance(header_value, str)
    assert "https://www.googletagmanager.com" in header_value
    assert "https://*.googletagmanager.com" in header_value
    assert "https://*.google-analytics.com" in header_value


def test_csp_echo_returns_applied_header(monkeypatch):
    monkeypatch.setenv("GA_ENABLE", "true")
    app = create_app({"TESTING": True})
    client = app.test_client()

    echo_response = client.get("/csp/echo")
    assert echo_response.status_code == 200
    payload = echo_response.get_json()
    header_value = echo_response.headers.get("Content-Security-Policy", "")
    assert payload == {"header": header_value}
    assert "'nonce-" in header_value
    assert "https://cdn.plot.ly" in header_value

    home_response = client.get("/")
    home_header = home_response.headers.get("Content-Security-Policy", "")
    directives_home = _parse_csp_header(home_header)
    directives_echo = _parse_csp_header(header_value)

    for directive_name, source_list in directives_echo.items():
        if directive_name in {"script-src", "script-src-elem"}:
            assert set(_strip_nonces(source_list)) == set(
                _strip_nonces(directives_home.get(directive_name, []))
            )
        else:
            assert directives_home.get(directive_name, []) == source_list
