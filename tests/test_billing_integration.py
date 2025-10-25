import pytest
import json
from unittest.mock import patch, MagicMock
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import create_app
from app.models import db
from app.models.user import User
from app.utils.auth import hash_password

@pytest.fixture
def app():
    app = create_app()
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()

@pytest.fixture
def user(app):
    with app.app_context():
        user = User(
            email="test@example.com",
            password_hash=hash_password("password123"),
            premium=False
        )
        db.session.add(user)
        db.session.commit()
        return user.id

@pytest.fixture
def premium_user(app):
    with app.app_context():
        user = User(
            email="premium@example.com",
            password_hash=hash_password("password123"),
            premium=True,
            stripe_customer_id="cus_test123"
        )
        db.session.add(user)
        db.session.commit()
        return user.id

def test_create_checkout_session_requires_login(client):
    response = client.post('/billing/create-checkout-session')
    assert response.status_code == 302

@patch('stripe.checkout.Session.create')
@patch('stripe.Customer.create')
def test_create_checkout_session_success(mock_customer, mock_session, client, user, app):
    mock_customer.return_value = MagicMock(id='cus_test123')
    mock_session.return_value = MagicMock(url='https://checkout.stripe.com/test')
    
    with client.session_transaction() as sess:
        sess['user_id'] = user
    
    response = client.post('/billing/create-checkout-session')
    
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'checkout_url' in data
    assert data['checkout_url'] == 'https://checkout.stripe.com/test'

def test_customer_portal_requires_stripe_customer(client, user):
    with client.session_transaction() as sess:
        sess['user_id'] = user
    
    response = client.get('/billing/customer-portal')
    assert response.status_code == 302

@patch('stripe.billing_portal.Session.create')
def test_customer_portal_success(mock_portal, client, premium_user):
    mock_portal.return_value = MagicMock(url='https://billing.stripe.com/test')
    
    with client.session_transaction() as sess:
        sess['user_id'] = premium_user
    
    response = client.get('/billing/customer-portal')
    assert response.status_code == 302
    assert response.location == 'https://billing.stripe.com/test'

def test_stripe_webhook_checkout_completed(client, user, app):
    webhook_payload = {
        'type': 'checkout.session.completed',
        'data': {
            'object': {
                'id': 'cs_test123',
                'subscription': 'sub_test123',
                'metadata': {'user_id': str(user)}
            }
        }
    }
    
    with patch('stripe.Webhook.construct_event') as mock_webhook:
        mock_webhook.return_value = webhook_payload
        
        response = client.post('/billing/webhook',
                             data=json.dumps(webhook_payload),
                             headers={'Stripe-Signature': 'test_signature'})
        
        assert response.status_code == 200
        
        with app.app_context():
            updated_user = User.query.get(user)
            assert updated_user.has_premium_access is True
            assert updated_user.is_premium is True
            assert updated_user.subscription_status == 'active'


def test_confirm_donation_records_transaction(client, user, app):
    with client.session_transaction() as sess:
        sess['user_id'] = user
        sess['_csrf_token'] = 'token123'

    response = client.post(
        '/billing/confirm_donation',
        data={'csrf_token': 'token123', 'tx_id': 'PAYPAL123', 'amount': '12.50'}
    )

    assert response.status_code == 302

    with app.app_context():
        updated_user = User.query.get(user)
        assert updated_user.donation_tx == 'PAYPAL123'
        assert updated_user.has_premium_access is False
