import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("PARTNER_DIRECTORY_ENABLED", "1")

from app import create_app
from app.models import db
from app.models.partner import (
    Partner,
    PartnerCategory,
    PartnerSubscription,
    generate_invoice_number,
)
from app.services.partner_directory import (
    can_approve_partner,
    create_subscription,
    generate_invoice_pdf,
    slots_available,
)
from app.utils.partners import next_partner_slug


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
        }
    )
    with app.app_context():
        db.create_all()
        # seed categories similar to migration
        guide = PartnerCategory(slug="guide", name="Guide autorizzate", max_slots=2)
        db.session.add(guide)
        db.session.commit()
        yield app
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def category(app):
    with app.app_context():
        return PartnerCategory.query.filter_by(slug="guide").first()


@pytest.fixture()
def partner_factory(app, category):
    created = []

    def _create(name: str, status: str = "draft") -> Partner:
        partner = Partner(
            category=category,
            name=name,
            slug=next_partner_slug(name),
            status=status,
        )
        db.session.add(partner)
        db.session.commit()
        created.append(partner)
        return partner

    yield _create

    with app.app_context():
        for partner in created:
            db.session.delete(partner)
        db.session.commit()


def _activate_partner(partner: Partner, *, paid_at: datetime) -> PartnerSubscription:
    subscription = create_subscription(
        partner,
        year=paid_at.year,
        price_eur=Decimal("30"),
        payment_method="cash",
        payment_ref=None,
        paid_at=paid_at,
    )
    partner.mark_approved()
    db.session.commit()
    return subscription


def test_category_listing_limits_to_max_slots(client, app, category, partner_factory):
    with app.app_context():
        p1 = partner_factory("Partner A")
        p2 = partner_factory("Partner B")
        p3 = partner_factory("Partner C")
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        _activate_partner(p1, paid_at=now)
        _activate_partner(p2, paid_at=now)
        _activate_partner(p3, paid_at=now)

    response = client.get("/categoria/guide")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    # Only two partners can appear because of max_slots=2
    assert "Partner A" in body
    assert "Partner B" in body
    assert "Partner C" not in body
    assert "COMPLETA (2/2)" in body


def test_category_view_returns_404_for_missing_category(client):
    response = client.get("/categoria/non-esiste")
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    assert "Pagina non trovata" in body


def test_category_view_handles_empty_partner_list(client):
    response = client.get("/categoria/guide")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Nessun partner disponibile" in body


def test_category_view_handles_missing_subscription_table(client, app, category, partner_factory):
    with app.app_context():
        partner = partner_factory("Legacy Partner", status="approved")
        partner.approved_at = datetime.now(timezone.utc)
        db.session.commit()
        db.session.execute(db.text("DROP TABLE partner_subscriptions"))
        db.session.commit()

    response = client.get("/categoria/guide")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Nessun partner disponibile" in body

    with app.app_context():
        from app.models.partner import PartnerSubscription

        PartnerSubscription.__table__.create(db.engine)
        db.session.commit()


def test_price_first_vs_renewal(app, category, partner_factory):
    with app.app_context():
        partner = partner_factory("Nuovo Partner")
        assert partner.compute_price(first_year_price=30, renewal_price=50) == 30
        _activate_partner(partner, paid_at=datetime(2024, 7, 1, tzinfo=timezone.utc))
        assert partner.compute_price(first_year_price=30, renewal_price=50) == 50


def test_subscription_validity_and_invoice(tmp_path, app, category, partner_factory):
    with app.app_context():
        partner = partner_factory("Partner PDF")
        paid_at = datetime(2025, 3, 10, tzinfo=timezone.utc)
        subscription = create_subscription(
            partner,
            year=2025,
            price_eur=Decimal("50"),
            payment_method="paypal_manual",
            payment_ref="PP-1",
            paid_at=paid_at,
        )
        db.session.commit()
        assert subscription.valid_from == paid_at.date()
        assert subscription.valid_to == paid_at.date() + timedelta(days=365)
        pdf_path = generate_invoice_pdf(subscription)
        assert pdf_path.exists()
        assert pdf_path.read_bytes().startswith(b"%PDF")


def test_cannot_approve_when_slots_full(app, category, partner_factory):
    with app.app_context():
        now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        p1 = partner_factory("Slot 1")
        p2 = partner_factory("Slot 2")
        p3 = partner_factory("Slot 3")
        _activate_partner(p1, paid_at=now)
        _activate_partner(p2, paid_at=now)
        assert slots_available(category) == 0
        assert not can_approve_partner(p3)


def test_generate_invoice_number_format():
    number = generate_invoice_number(5, year=2025)
    assert number == "EM-PARTNER-2025-0005"


def test_categories_seed_cli(app):
    with app.app_context():
        PartnerCategory.query.delete(synchronize_session=False)
        db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["categories-ensure-seed"])

    assert result.exit_code == 0
    with app.app_context():
        categories = {category.slug: category for category in PartnerCategory.query.all()}
        assert {"guide", "hotel", "ristoranti"}.issubset(categories.keys())
        assert all(category.max_slots == 10 for category in categories.values())
