import os

import pytest
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DISABLE_SCHEDULER", "1")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from app import create_app
from app.models import db
from app.models.admin_action import AdminActionLog
from app.models.billing import EventLog
from app.models.premium_request import PremiumRequest
from app.models.user import User


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


def _create_user(email: str, is_admin: bool = False) -> int:
    user = User(email=email, is_admin=is_admin)
    db.session.add(user)
    db.session.commit()
    return user.id


def test_confirm_donation_creates_or_updates_request(client, app):
    with app.app_context():
        user_id = _create_user("donor@example.com")

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["_csrf_token"] = "csrf-token"

    response = client.post(
        "/billing/confirm_donation",
        data={"csrf_token": "csrf-token", "tx_id": "TX123", "amount": "9.99"},
    )
    assert response.status_code == 302

    with app.app_context():
        requests = PremiumRequest.query.filter_by(email="donor@example.com").all()
        assert len(requests) == 1
        assert requests[0].paypal_tx_id == "TX123"
        assert requests[0].status == "pending"

    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["_csrf_token"] = "csrf-token"

    response = client.post(
        "/billing/confirm_donation",
        data={"csrf_token": "csrf-token", "tx_id": "TX456", "amount": "12.00"},
    )
    assert response.status_code == 302

    with app.app_context():
        requests = PremiumRequest.query.filter_by(email="donor@example.com").all()
        assert len(requests) == 1
        assert requests[0].paypal_tx_id == "TX456"


def test_admin_approves_premium_request(client, app):
    with app.app_context():
        user_id = _create_user("premium@example.com")
        admin_id = _create_user("admin@example.com", is_admin=True)
        request = PremiumRequest(
            user_id=user_id,
            email="premium@example.com",
            paypal_tx_id="TX789",
            status="pending",
            source="paypal",
        )
        db.session.add(request)
        db.session.commit()
        request_id = request.id

    with client.session_transaction() as sess:
        sess["user_id"] = admin_id
        sess["_csrf_token"] = "csrf-token"

    response = client.post(
        f"/admin/premium-requests/{request_id}/approve",
        data={"csrf_token": "csrf-token"},
    )
    assert response.status_code == 302

    with app.app_context():
        updated_request = PremiumRequest.query.get(request_id)
        user = User.query.get(user_id)
        assert updated_request.status == "approved"
        assert user.has_premium_access is True
        assert AdminActionLog.query.count() == 1
        assert EventLog.query.filter_by(event_type="premium_request.approved").count() == 1
