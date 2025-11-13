"""Test partner lead email routing to owner's personal email."""
import os
from unittest.mock import patch, MagicMock

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("PARTNER_DIRECTORY_ENABLED", "1")

import pytest
from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import db
from app.models.partner import Partner, PartnerCategory


@pytest.fixture()
def app(tmp_path):
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
            "STATIC_FOLDER": str(tmp_path),
            "WTF_CSRF_ENABLED": False,
            "ADMIN_EMAIL": "admin@example.com",
        }
    )
    with app.app_context():
        db.create_all()
        # Create test category
        category = PartnerCategory(slug="guide", name="Guide autorizzate", max_slots=10)
        db.session.add(category)
        db.session.commit()
        yield app
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def partner(app):
    with app.app_context():
        category = PartnerCategory.query.filter_by(slug="guide").first()
        partner = Partner(
            category=category,
            name="Test Guide",
            slug="test-guide",
            status="approved",
            email="partner@example.com",
        )
        db.session.add(partner)
        db.session.commit()
        return partner


def test_lead_email_sent_to_owner_personal_email(client, app, partner):
    """Test that lead emails are routed to salvoferro16@gmail.com."""
    with app.app_context():
        partner_obj = Partner.query.filter_by(slug="test-guide").first()
        partner_id = partner_obj.id

    with patch("app.routes.partners.send_email") as mock_send_email:
        response = client.post(
            f"/lead/{partner_id}",
            data={
                "name": "Test User",
                "email": "test@example.com",
                "phone": "1234567890",
                "message": "Test message",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert mock_send_email.called
        call_args = mock_send_email.call_args

        # Verify email is sent to owner's personal email
        assert call_args[1]["recipients"] == ["salvoferro16@gmail.com"]
        
        # Verify admin email is in BCC if different from owner email
        assert call_args[1]["bcc"] == ["admin@example.com"]
        
        # Verify subject includes partner name
        assert "Test Guide" in call_args[1]["subject"]


def test_lead_email_no_duplicate_bcc_when_admin_is_owner(client, app, partner):
    """Test that BCC is not duplicated when admin email matches owner email."""
    app.config["ADMIN_EMAIL"] = "salvoferro16@gmail.com"
    
    with app.app_context():
        partner_obj = Partner.query.filter_by(slug="test-guide").first()
        partner_id = partner_obj.id

    with patch("app.routes.partners.send_email") as mock_send_email:
        response = client.post(
            f"/lead/{partner_id}",
            data={
                "name": "Test User",
                "email": "test@example.com",
                "phone": "1234567890",
                "message": "Test message",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert mock_send_email.called
        call_args = mock_send_email.call_args

        # Verify email is sent to owner's personal email
        assert call_args[1]["recipients"] == ["salvoferro16@gmail.com"]
        
        # Verify BCC is empty when admin email matches owner email
        assert call_args[1]["bcc"] == []


def test_lead_email_sent_even_without_partner_email(client, app):
    """Test that leads are sent to owner email even if partner has no email."""
    with app.app_context():
        category = PartnerCategory.query.filter_by(slug="guide").first()
        partner_no_email = Partner(
            category=category,
            name="No Email Guide",
            slug="no-email-guide",
            status="approved",
            email=None,  # Partner has no email
        )
        db.session.add(partner_no_email)
        db.session.commit()
        partner_id = partner_no_email.id

    with patch("app.routes.partners.send_email") as mock_send_email:
        response = client.post(
            f"/lead/{partner_id}",
            data={
                "name": "Test User",
                "email": "test@example.com",
                "phone": "1234567890",
                "message": "Test message",
            },
            follow_redirects=True,
        )

        assert response.status_code == 200
        assert mock_send_email.called
        call_args = mock_send_email.call_args

        # Verify email is sent to owner's personal email
        assert call_args[1]["recipients"] == ["salvoferro16@gmail.com"]
