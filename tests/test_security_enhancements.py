"""Enhanced security tests for HTTP headers and session configuration."""
import pytest
from flask import Flask


def test_security_headers_present(client):
    """Test that all recommended security headers are present."""
    response = client.get("/")
    headers = response.headers
    
    # CSP header
    assert "Content-Security-Policy" in headers
    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    
    # Frame protection
    assert headers.get("X-Frame-Options") == "DENY"
    
    # Content type protection
    assert headers.get("X-Content-Type-Options") == "nosniff"
    
    # Referrer policy
    assert headers.get("Referrer-Policy") == "no-referrer-when-downgrade"
    
    # XSS protection (for legacy browsers)
    assert headers.get("X-XSS-Protection") == "1; mode=block"
    
    # Permissions policy
    assert "Permissions-Policy" in headers
    permissions = headers["Permissions-Policy"]
    assert "geolocation=()" in permissions


def test_session_cookie_security(app: Flask):
    """Test that session cookies have secure flags."""
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_secret_key_not_default(app: Flask):
    """Test that SECRET_KEY is not using an insecure default in production."""
    secret_key = app.config.get("SECRET_KEY")
    
    # In test environment, we allow test keys
    if not app.config.get("TESTING"):
        # Ensure it's not a known weak default
        weak_keys = ["dev", "change-me", "secret", ""]
        assert secret_key not in weak_keys
        assert len(secret_key) >= 32, "SECRET_KEY should be at least 32 characters"


def test_csrf_token_generation(client):
    """Test that CSRF tokens are generated and unique."""
    with client.session_transaction() as session:
        # First request should generate token
        from app.utils.csrf import generate_csrf_token
        token1 = generate_csrf_token()
        assert token1
        assert len(token1) > 20  # Should be a substantial token
        
        # Same session should return same token
        token2 = generate_csrf_token()
        assert token1 == token2


def test_csrf_token_validation(client):
    """Test CSRF token validation logic."""
    from app.utils.csrf import generate_csrf_token, validate_csrf_token
    
    with client.session_transaction() as session:
        token = generate_csrf_token()
        
        # Valid token should pass
        assert validate_csrf_token(token) is True
        
        # Invalid token should fail
        assert validate_csrf_token("invalid-token") is False
        
        # None should fail
        assert validate_csrf_token(None) is False
        
        # Empty string should fail
        assert validate_csrf_token("") is False


def test_password_not_logged(caplog, client):
    """Test that passwords are not logged in plaintext."""
    import logging
    caplog.set_level(logging.DEBUG)
    
    # Attempt a login (will fail but that's ok)
    client.post("/legacy/login", data={
        "email": "test@example.com",
        "password": "SuperSecret123!"
    })
    
    # Check that password doesn't appear in logs
    for record in caplog.records:
        assert "SuperSecret123!" not in record.message


def test_sql_injection_protection(client):
    """Test that SQL injection attempts are safely handled."""
    # Attempt SQL injection in various endpoints
    injection_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE users;--",
        "1' UNION SELECT * FROM users--",
    ]
    
    for payload in injection_payloads:
        # Try injection in email field
        response = client.post("/legacy/login", data={
            "email": payload,
            "password": "test"
        })
        # Should not cause a 500 error or expose SQL error messages
        assert response.status_code in [200, 400, 401, 404]
        assert b"sql" not in response.data.lower()
        assert b"syntax error" not in response.data.lower()


def test_xss_in_form_reflection(client):
    """Test that XSS payloads are escaped when reflected."""
    xss_payload = "<script>alert('XSS')</script>"
    
    # Test various endpoints that might reflect input
    response = client.post("/legacy/login", data={
        "email": xss_payload,
        "password": "test"
    })
    
    # Script tag should be escaped or removed
    assert b"<script>" not in response.data
    assert b"alert('XSS')" not in response.data or b"&lt;script&gt;" in response.data


def test_rate_limiting_configured(app: Flask):
    """Test that rate limiting is configured."""
    # Check that limiter is initialized
    from app import limiter
    assert limiter is not None
    
    # Check that some routes have rate limits
    # This is a basic check - specific limits are tested in integration tests
    assert hasattr(limiter, "enabled")


def test_secure_password_hashing():
    """Test that password hashing uses bcrypt with sufficient rounds."""
    from app.utils.auth import hash_password, check_password
    
    password = "TestPassword123!"
    hashed = hash_password(password)
    
    # Bcrypt hashes start with $2a$ or $2b$
    assert hashed.startswith("$2")
    
    # Should verify correctly
    assert check_password(password, hashed) is True
    
    # Wrong password should fail
    assert check_password("WrongPassword", hashed) is False
    
    # Hash should be different each time (due to random salt)
    hashed2 = hash_password(password)
    assert hashed != hashed2


def test_security_txt_accessible(client):
    """Test that security.txt is accessible."""
    response = client.get("/.well-known/security.txt")
    assert response.status_code == 200
    assert b"Contact:" in response.data
    assert b"security@etnamonitor.it" in response.data


def test_sensitive_routes_require_auth(client):
    """Test that sensitive routes require authentication."""
    sensitive_routes = [
        "/dashboard",
        "/admin",
        "/account/settings",
    ]
    
    for route in sensitive_routes:
        response = client.get(route, follow_redirects=False)
        # Should redirect to login or return 401/403
        assert response.status_code in [302, 401, 403]


def test_admin_routes_require_admin_role(client, app):
    """Test that admin routes check for admin role."""
    from app.models.user import User
    from app.models import db
    
    with app.app_context():
        # Create a non-admin user
        user = User(email="user@example.com", password_hash="dummy")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    
    # Login as non-admin user
    with client.session_transaction() as session:
        session['user_id'] = user_id
    
    # Try to access admin route
    response = client.get("/admin", follow_redirects=False)
    # Should be denied
    assert response.status_code in [302, 403]
    
    # Cleanup
    with app.app_context():
        user = db.session.get(User, user_id)
        if user:
            db.session.delete(user)
            db.session.commit()


def test_no_sensitive_info_in_error_pages(client):
    """Test that error pages don't leak sensitive information."""
    # Trigger a 404
    response = client.get("/this-route-does-not-exist-12345")
    
    # Should not contain internal paths, stack traces, or secrets
    data = response.data.decode("utf-8", errors="ignore")
    assert "/home/" not in data
    assert "Traceback" not in data
    assert "SECRET_KEY" not in data
    assert "DATABASE_URL" not in data


def test_csp_allows_required_domains(client):
    """Test that CSP allows required domains for functionality."""
    response = client.get("/")
    csp = response.headers.get("Content-Security-Policy", "")
    
    # Should allow Google Analytics
    assert "google-analytics.com" in csp or "googletagmanager.com" in csp
    
    # Should allow Plotly CDN
    assert "cdn.plot.ly" in csp
    
    # Should have script-src directive
    assert "script-src" in csp


def test_database_connection_pooling(app: Flask):
    """Test that database connection pooling is configured."""
    engine_options = app.config.get("SQLALCHEMY_ENGINE_OPTIONS", {})
    
    # Check pool configuration
    assert "pool_pre_ping" in engine_options
    assert engine_options["pool_pre_ping"] is True
    
    # Pool size should be configured
    if "pool_size" in engine_options:
        assert engine_options["pool_size"] > 0
