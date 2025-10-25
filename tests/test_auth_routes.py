import pytest
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
