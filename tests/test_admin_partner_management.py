import os
from pathlib import Path

import pytest
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("PARTNER_DIRECTORY_ENABLED", "1")

from app import create_app
from app.models import db
from app.models.partner import Partner, PartnerCategory
from app.models.user import User


@pytest.fixture()
def app(tmp_path):
    static_root = tmp_path / "static"
    static_root.mkdir()

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SQLALCHEMY_ENGINE_OPTIONS": {
                "connect_args": {"check_same_thread": False},
                "poolclass": StaticPool,
            },
            "STATIC_FOLDER": str(static_root),
        }
    )

    with app.app_context():
        db.create_all()
        category = PartnerCategory(slug="guide", name="Guide autorizzate", max_slots=3)
        admin = User(email="admin@example.com", is_admin=True)
        db.session.add_all([category, admin])
        db.session.commit()
        yield app
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_user(app):
    with app.app_context():
        return User.query.filter_by(email="admin@example.com").first()


@pytest.fixture()
def category(app):
    with app.app_context():
        return PartnerCategory.query.filter_by(slug="guide").first()


def _authorize_admin_session(client, admin_user):
    with client.session_transaction() as session:
        session["_csrf_token"] = "csrf-token"
        session["user_id"] = admin_user.id


def test_create_partner_draft_succeeds(client, app, admin_user, category):
    _authorize_admin_session(client, admin_user)

    response = client.post(
        "/admin/partners",
        data={
            "csrf_token": "csrf-token",
            "name": "Partner Test",
            "category_id": str(category.id),
            "short_desc": "Descrizione",
            "guide_license_id": "GT12345",
        },
    )

    assert response.status_code == 302

    with app.app_context():
        partner = Partner.query.filter_by(name="Partner Test").one()
        assert partner.status == "draft"
        assert partner.category_id == category.id


def test_create_partner_rejects_invalid_category(client, app, admin_user):
    _authorize_admin_session(client, admin_user)

    response = client.post(
        "/admin/partners",
        data={
            "csrf_token": "csrf-token",
            "name": "Partner Non Valido",
            "category_id": "abc",
        },
    )

    assert response.status_code == 302

    with app.app_context():
        assert (
            db.session.query(Partner).filter_by(name="Partner Non Valido").count() == 0
        )


def test_delete_partner_removes_record_and_logo(client, app, admin_user, category):
    _authorize_admin_session(client, admin_user)

    static_root = Path(app.static_folder or "static")
    logo_rel = Path("images") / "partners" / "logo.png"
    logo_path = static_root / logo_rel
    logo_path.parent.mkdir(parents=True, exist_ok=True)
    logo_path.write_bytes(b"logo")

    with app.app_context():
        partner = Partner(
            category=category,
            name="Partner da Eliminare",
            slug="partner-da-eliminare",
            status="draft",
            logo_path=logo_rel.as_posix(),
        )
        db.session.add(partner)
        db.session.commit()
        partner_id = partner.id

    response = client.post(
        f"/admin/partners/{partner_id}/delete",
        data={"csrf_token": "csrf-token"},
    )

    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(Partner, partner_id) is None

    assert not logo_path.exists()
