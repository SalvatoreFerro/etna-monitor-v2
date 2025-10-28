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
from app.utils.auth import hash_password

@pytest.fixture
def app():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SQLALCHEMY_ENGINE_OPTIONS': {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
    })

    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture
def client(app):
    with app.test_client() as client:
        yield client

@pytest.fixture
def admin_user(app):
    with app.app_context():
        user = User(
            email="admin@test.com",
            password_hash=hash_password("password123"),
            is_admin=True
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        return user_id

def test_register_success(client):
    response = client.post('/register', data={
        'email': 'test@example.com',
        'password': 'password123'
    })
    assert response.status_code == 302

def test_register_duplicate_email(client):
    client.post('/register', data={
        'email': 'test@example.com',
        'password': 'password123'
    })
    
    response = client.post('/register', data={
        'email': 'test@example.com',
        'password': 'password456'
    })
    assert b'Email already registered' in response.data

def test_login_success(client, app):
    with app.app_context():
        user = User(email="test@example.com", password_hash=hash_password("password123"))
        db.session.add(user)
        db.session.commit()
    
    response = client.post('/login', data={
        'email': 'test@example.com',
        'password': 'password123'
    })
    assert response.status_code == 302

def test_login_invalid_credentials(client):
    response = client.post('/login', data={
        'email': 'nonexistent@example.com',
        'password': 'wrongpassword'
    })
    assert b'Invalid email or password' in response.data

def test_dashboard_requires_login(client):
    response = client.get('/dashboard/')
    assert response.status_code == 302

def test_admin_requires_admin_user(client, admin_user):
    response = client.get('/admin/')
    assert response.status_code == 302
    
    with client.session_transaction() as sess:
        sess['user_id'] = admin_user
    
    response = client.get('/admin/')
    assert response.status_code == 200

def test_premium_toggle(client, admin_user, app):
    with app.app_context():
        regular_user = User(email="user@test.com", password_hash=hash_password("pass"))
        db.session.add(regular_user)
        db.session.commit()
        user_id = regular_user.id
    
    with client.session_transaction() as sess:
        sess['user_id'] = admin_user
    
    response = client.post(f'/admin/toggle_premium/{user_id}')
    assert response.status_code == 302
    
    with app.app_context():
        user = User.query.get(user_id)
        assert user.has_premium_access is True


def test_admin_activate_premium_lifetime(client, admin_user, app):
    with app.app_context():
        donor = User(
            email="donor@test.com",
            password_hash=hash_password("pass"),
            donation_tx="PAY12345"
        )
        db.session.add(donor)
        db.session.commit()
        donor_id = donor.id

    with client.session_transaction() as sess:
        sess['user_id'] = admin_user
        sess['_csrf_token'] = 'csrf-token'

    response = client.post(
        f'/admin/activate_premium/{donor_id}',
        data={'csrf_token': 'csrf-token'}
    )

    assert response.status_code == 302

    with app.app_context():
        updated = User.query.get(donor_id)
        assert updated.has_premium_access is True
        assert updated.premium_lifetime is True
        assert updated.premium_since is not None
        assert updated.donation_tx == "PAY12345"


def test_homepage_cache_respects_login_state(client, app):
    with app.app_context():
        cached_user = User(
            email="cache-test@example.com",
            password_hash=hash_password("cache-pass"),
        )
        db.session.add(cached_user)
        db.session.commit()

    response_anon = client.get('/')
    assert response_anon.status_code == 200
    assert b'Accedi con Google' in response_anon.data

    login_response = client.post('/login', data={
        'email': 'cache-test@example.com',
        'password': 'cache-pass'
    })
    assert login_response.status_code == 302

    response_logged_in = client.get('/')
    assert response_logged_in.status_code == 200
    assert b'Esci' in response_logged_in.data
    assert b'Accedi con Google' not in response_logged_in.data


def test_google_login_handles_missing_theme_preference(monkeypatch, client, app):
    from sqlalchemy.exc import ProgrammingError

    class DummyResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = str(payload)

        def json(self):
            return self._payload

    token_response = DummyResponse(200, {"access_token": "access", "refresh_token": "refresh"})
    userinfo_response = DummyResponse(
        200,
        {
            "sub": "theme-user",
            "email": "theme-missing@example.com",
            "name": "Theme Missing",
            "picture": "https://example.com/avatar.png",
        },
    )

    responses = iter([token_response, userinfo_response])

    monkeypatch.setattr(
        "app.routes.auth._google_oauth_request",
        lambda *args, **kwargs: next(responses),
    )

    from app.utils import user_columns as user_columns_utils
    from app.routes import auth as auth_routes

    user_columns_utils.reset_login_safe_user_columns_cache()

    def safe_columns_without_theme():
        from app.models.user import User

        return (
            User.id,
            User.email,
            User.google_id,
            User.name,
            User.picture_url,
            User.password_hash,
            User.is_premium,
            User.premium,
            User.premium_lifetime,
            User.telegram_opt_in,
        )

    monkeypatch.setattr(user_columns_utils, "get_login_safe_user_columns", safe_columns_without_theme)
    monkeypatch.setattr(auth_routes, "get_login_safe_user_columns", safe_columns_without_theme)

    def failing_get(*args, **kwargs):
        raise ProgrammingError(
            "SELECT", {}, Exception("no such column: users.theme_preference")
        )

    monkeypatch.setattr(db.session, "get", failing_get)

    with client.session_transaction() as session:
        session["oauth_state"] = "state-token"

    response = client.get(
        "/auth/callback?code=auth-code&state=state-token",
        follow_redirects=True,
    )

    assert response.status_code == 200

    with app.app_context():
        user = User.query.filter_by(email="theme-missing@example.com").one()
        assert user.google_id == "theme-user"
