import os
from urllib.parse import urlparse

import pytest
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DISABLE_SCHEDULER", "1")

from app import create_app
from app.models import CommunityPost, ModerationAction, User, db
from app.utils.auth import hash_password


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SERVER_NAME": "localhost",
            "PREFERRED_URL_SCHEME": "http",
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


@pytest.fixture()
def client(app):
    with app.test_client() as client:
        yield client


@pytest.fixture()
def user_data(app):
    with app.app_context():
        raw_password = "password123"
        user = User(
            email="user@example.com",
            password_hash=hash_password(raw_password),
        )
        db.session.add(user)
        db.session.commit()
        return {"id": user.id, "email": user.email, "password": raw_password}


@pytest.fixture()
def moderator_data(app):
    with app.app_context():
        raw_password = "password123"
        moderator = User(
            email="moderator@example.com",
            password_hash=hash_password(raw_password),
            role="moderator",
        )
        db.session.add(moderator)
        db.session.commit()
        return {
            "id": moderator.id,
            "email": moderator.email,
            "password": raw_password,
        }


@pytest.fixture()
def admin_data(app):
    with app.app_context():
        raw_password = "password123"
        admin = User(
            email="admin@example.com",
            password_hash=hash_password(raw_password),
            role="admin",
            is_admin=True,
        )
        db.session.add(admin)
        db.session.commit()
        return {
            "id": admin.id,
            "email": admin.email,
            "password": raw_password,
        }


def login(client, email, password):
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )
    # Ensure a CSRF token is available for subsequent form submissions
    with client.session_transaction() as session:
        session["_csrf_token"] = "csrf-token"
    return response


def test_soft_delete_and_anonymize(app, user_data):
    with app.app_context():
        user = User.query.get(user_data["id"])
        user.soft_delete()
        user.anonymize()
        db.session.commit()
        assert user.deleted_at is not None
        assert user.email.startswith("deleted-user-")
        assert user.is_active is False


def test_create_post_with_suspicious_markup_auto_hides(client, app, user_data):
    login(client, user_data["email"], user_data["password"])
    response = client.post(
        "/community/new",
        data={
            "title": "Analisi tremore Etna",
            "body": "<script>alert(1)</script><p>Contenuto valido</p>",
            "csrf_token": "csrf-token",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    with app.app_context():
        post = CommunityPost.query.first()
        assert post is not None
        assert post.status == "hidden"
        assert post.body_html_sanitized == "<p>Contenuto valido</p>"
        action = (
            ModerationAction.query.filter_by(post_id=post.id, action="auto_hide_xss")
            .order_by(ModerationAction.created_at.desc())
            .first()
        )
        assert action is not None
        assert action.reason == "XSS sanitization"


def test_role_required_blocks_non_moderator(client, user_data, app):
    login(client, user_data["email"], user_data["password"])
    response = client.post(
        "/admin/moderation/approve/1",
        data={"csrf_token": "csrf-token"},
    )
    assert response.status_code == 403


def test_moderation_flow(client, app, user_data, moderator_data):
    login(client, user_data["email"], user_data["password"])
    client.post(
        "/community/new",
        data={
            "title": "Osservazioni campo base",
            "body": "<p>Report dettagliato e analisi approfondita degli ultimi eventi registrati.</p>",
            "csrf_token": "csrf-token",
        },
    )
    with app.app_context():
        post = CommunityPost.query.first()
        slug = post.slug
        post_id = post.id

    # Public should not see pending post
    client.get("/auth/logout", follow_redirects=True)
    response = client.get(f"/community/{slug}")
    assert response.status_code == 404

    login(client, moderator_data["email"], moderator_data["password"])
    response = client.post(
        f"/admin/moderation/approve/{post_id}",
        data={"csrf_token": "csrf-token", "reason": "Ottimo contributo"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        post = CommunityPost.query.get(post_id)
        assert post.status == "approved"
        assert post.moderated_by == moderator_data["id"]
        action = ModerationAction.query.filter_by(post_id=post.id).first()
        assert action is not None
        assert action.action == "approve"
        assert "<p>" in post.body_html_sanitized

    response = client.get(f"/community/{slug}")
    assert response.status_code == 200
    assert b"Report dettagliato" in response.data


def test_moderator_cannot_approve_suspicious_post(client, app, moderator_data):
    with app.app_context():
        post = CommunityPost(
            title="Test XSS",
            body="<img src=x onerror=alert(1)>",
            author_id=moderator_data["id"],
            status="pending",
        )
        post.body_html_sanitized = post.sanitize_body(post.body)
        db.session.add(post)
        db.session.commit()
        post_id = post.id

    login(client, moderator_data["email"], moderator_data["password"])
    response = client.post(
        f"/admin/moderation/approve/{post_id}",
        data={"csrf_token": "csrf-token"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        post = CommunityPost.query.get(post_id)
        assert post.status == "hidden"
        action = (
            ModerationAction.query.filter_by(post_id=post_id)
            .order_by(ModerationAction.created_at.desc())
            .first()
        )
        assert action is not None
        assert action.action == "auto_hide_xss"


def test_export_data_includes_posts(client, app, user_data):
    login(client, user_data["email"], user_data["password"])
    client.post(
        "/community/new",
        data={
            "title": "Report notte",
            "body": "<p>Aggiornamento completo con osservazioni dettagliate sugli andamenti notturni.</p>",
            "csrf_token": "csrf-token",
        },
    )
    response = client.get("/account/export-data")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user"]["email"].startswith("user@")
    assert len(payload["posts"]) == 1


def test_delete_request_flow(client, app, user_data):
    login(client, user_data["email"], user_data["password"])
    response = client.post(
        "/account/delete-request",
        data={"csrf_token": "csrf-token"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        outbox = app.extensions.get("email", {}).get("outbox", [])
        assert outbox
        message = outbox[-1]
        assert "Conferma eliminazione" in message.subject
        confirm_url = None
        for line in message.text.splitlines():
            if line.startswith("http"):
                confirm_url = line.strip()
                break
        assert confirm_url

    path = urlparse(confirm_url).path
    response = client.get(path)
    assert response.status_code == 200

    with app.app_context():
        refreshed = User.query.get(user_data["id"])
        assert refreshed.deleted_at is not None
        assert refreshed.is_active is False
        assert refreshed.email.startswith("deleted-user-")


def test_admin_dashboard_displays_shortcuts(client, app, admin_data):
    login(client, admin_data["email"], admin_data["password"])

    response = client.get("/admin", follow_redirects=True)
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Strumenti rapidi" in html
    assert "Moderazione community" in html
    assert "Lifecycle account" in html
