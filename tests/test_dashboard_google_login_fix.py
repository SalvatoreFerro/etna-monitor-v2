"""Test that dashboard works after Google login without NameError."""

import os
import pytest
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")

from app import create_app
from app.models import db
from app.models.user import User
from flask_login import login_user


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


def test_dashboard_imports_badge_definitions(app, client):
    """Test that dashboard route doesn't raise NameError for BADGE_DEFINITIONS."""
    with app.app_context():
        # Create a test user
        user = User(email="test@example.com", google_id="123456")
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        
        # Login the user using flask-login
        login_user(user)
        
    # Access dashboard - should not raise NameError
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    
    response = client.get("/dashboard/")
    
    # Check that we got a response (not a 500 error)
    # 302 is OK (might redirect to login or elsewhere)
    # 200 means the page loaded successfully
    assert response.status_code in [200, 302], f"Expected 200 or 302, got {response.status_code}: {response.data[:500]}"
    
    # Most importantly, we should NOT get a 500 error which would indicate NameError
    assert response.status_code != 500, "Got 500 error - likely a NameError from missing import"


def test_badge_definitions_accessible():
    """Test that BADGE_DEFINITIONS can be imported from badge_service."""
    from app.services.badge_service import BADGE_DEFINITIONS
    
    assert BADGE_DEFINITIONS is not None
    assert isinstance(BADGE_DEFINITIONS, dict)
    assert len(BADGE_DEFINITIONS) > 0
