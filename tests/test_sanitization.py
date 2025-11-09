from app import create_app
from app.models import db
from app.utils.sanitize import find_suspicious_html, sanitize_html


def test_sanitize_html_removes_script_tag():
    html = "<p>Safe</p><script>alert(1)</script>"
    sanitized = sanitize_html(html)
    assert "<script" not in sanitized
    assert sanitized == "<p>Safe</p>"


def test_sanitize_html_strips_onerror_attribute():
    html = '<img src="x" onerror="alert(1)">'
    sanitized = sanitize_html(html)
    assert "onerror" not in sanitized
    assert sanitized.startswith("<img")


def test_sanitize_html_rejects_javascript_uri():
    html = '<a href="javascript:alert(1)">Click</a>'
    sanitized = sanitize_html(html)
    assert "javascript:" not in sanitized
    assert "href" not in sanitized or "href=\"" in sanitized and "javascript" not in sanitized


def test_find_suspicious_html_detects_encoded_script():
    html = "%3Cscript%3Ealert(1)%3C/script%3E"
    matches = find_suspicious_html(html)
    assert any("encoded" in match for match in matches)


def test_security_headers_include_csp_nonce():
    app = create_app(
        {
            "TESTING": True,
            "SERVER_NAME": "localhost",
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        }
    )
    with app.app_context():
        db.create_all()
    with app.test_client() as client:
        response = client.get("/")
    csp_header = response.headers.get("Content-Security-Policy")
    assert csp_header is not None
    assert "default-src 'self'" in csp_header
    assert "script-src 'self'" in csp_header
    assert "nonce-" in csp_header
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy") == "no-referrer-when-downgrade"
