"""Shared helpers for partner categories fallbacks and admin bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from flask import current_app
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.models import db
from app.models.partner import PartnerCategory


@dataclass
class StaticCategory:
    slug: str
    name: str
    description: str | None = None
    max_slots: int = 10


DEFAULT_CATEGORY_FALLBACKS: dict[str, StaticCategory] = {
    "guide": StaticCategory(
        slug="guide",
        name="Guide autorizzate",
        description="Professionisti certificati per esplorare l'Etna in sicurezza.",
    ),
    "hotel": StaticCategory(
        slug="hotel",
        name="Hotel",
        description="Strutture selezionate per vivere l'esperienza Etna al massimo.",
    ),
    "ristoranti": StaticCategory(
        slug="ristoranti",
        name="Ristoranti",
        description="Sapori autentici del territorio per completare la tua esperienza.",
    ),
}


CATEGORY_FORM_FIELDS: dict[str, list[dict[str, object]]] = {
    "guide": [
        {
            "name": "guide_license_id",
            "label": "Numero licenza guida",
            "type": "text",
            "required": True,
            "placeholder": "es. GT12345",
            "help": "Codice identificativo rilasciato dalla Regione Sicilia.",
        },
        {
            "name": "guide_specializations",
            "label": "Specializzazioni",
            "type": "textarea",
            "rows": 2,
            "placeholder": "Escursioni sul cratere, ciaspolate, tour al tramonto...",
        },
        {
            "name": "guide_languages",
            "label": "Lingue parlate",
            "type": "text",
            "placeholder": "Italiano, Inglese, Francese",
        },
    ],
    "hotel": [
        {
            "name": "hotel_rating",
            "label": "Classificazione stelle",
            "type": "select",
            "required": True,
            "options": [
                {"value": "1", "label": "1 stella"},
                {"value": "2", "label": "2 stelle"},
                {"value": "3", "label": "3 stelle"},
                {"value": "4", "label": "4 stelle"},
                {"value": "5", "label": "5 stelle"},
            ],
        },
        {
            "name": "hotel_rooms",
            "label": "Numero camere",
            "type": "number",
            "min": 1,
        },
        {
            "name": "hotel_services",
            "label": "Servizi principali",
            "type": "textarea",
            "rows": 2,
            "placeholder": "Spa, transfer aeroporto, ristorante interno...",
        },
    ],
    "ristoranti": [
        {
            "name": "restaurant_specialty",
            "label": "Specialità della casa",
            "type": "text",
            "required": True,
            "placeholder": "Caponata, pasta alla norma, degustazione vini...",
        },
        {
            "name": "restaurant_menu",
            "label": "Descrizione menu",
            "type": "textarea",
            "rows": 2,
            "placeholder": "Percorsi degustazione, menu turistici, abbinamenti vino...",
        },
        {
            "name": "restaurant_dietary",
            "label": "Opzioni alimentari",
            "type": "text",
            "placeholder": "Vegetariano, vegano, senza glutine",
        },
    ],
}


def missing_table_error(err: SQLAlchemyError, table_name: str) -> bool:
    message = str(getattr(err, "orig", err)).lower()
    if table_name not in message:
        return False
    return any(
        hint in message
        for hint in (
            "no such table",
            "does not exist",
            "undefined table",
            "unknown table",
        )
    )


def missing_column_error(err: SQLAlchemyError, table_name: str, column_name: str) -> bool:
    """Return True when the error indicates a missing column."""

    message = str(getattr(err, "orig", err)).lower()
    if table_name not in message or column_name not in message:
        return False
    return any(
        hint in message
        for hint in (
            "column",
            "unknown column",
            "does not exist",
            "no such column",
            "undefined column",
        )
    )


def ensure_partner_extra_data_column() -> bool:
    """Add the partners.extra_data column when missing.

    Returns True when the column has been created, False if it already exists.
    """

    engine = db.engine
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("partners")}
    if "extra_data" in columns:
        return False

    dialect = engine.dialect.name
    if dialect == "postgresql":
        column_type = "JSONB"
        default_clause = "DEFAULT '{}'::jsonb"
    else:
        column_type = "JSON"
        default_clause = "DEFAULT '{}'"

    alter_sql = text(
        f"ALTER TABLE partners ADD COLUMN extra_data {column_type} NOT NULL {default_clause}"
    )

    with engine.begin() as connection:
        connection.execute(alter_sql)

    current_app.logger.info("Added partners.extra_data column via ensure helper")
    return True


def ensure_partner_category_fk() -> bool:
    """Create the partners.category_id column when operating on legacy schemas.

    Older databases stored the partner category slug inside a ``category`` text
    column.  When that legacy column is detected we automatically backfill the
    new foreign key so that the public listings and admin dashboard keep
    working without requiring a manual migration step.

    Returns ``True`` when the column has been created or backfilled.
    """

    engine = db.engine
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("partners")}

    if "category_id" in columns:
        return False

    if "category" not in columns:
        current_app.logger.warning(
            "partners.category_id column missing but no legacy 'category' column found"
        )
        return False

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE partners ADD COLUMN category_id INTEGER"))

    has_category_table = inspector.has_table("partner_categories")
    backfilled = 0
    unmatched: int | None = None

    if has_category_table:
        update_sql = text(
            """
            UPDATE partners
            SET category_id = (
                SELECT id
                FROM partner_categories
                WHERE slug = partners.category
                LIMIT 1
            )
            WHERE category IS NOT NULL AND category_id IS NULL
            """
        )

        try:
            with engine.begin() as connection:
                result = connection.execute(update_sql)
                backfilled = result.rowcount or 0

            with engine.begin() as connection:
                unmatched = connection.execute(
                    text(
                        "SELECT COUNT(*) FROM partners WHERE category IS NOT NULL AND category_id IS NULL"
                    )
                ).scalar_one()
        except SQLAlchemyError as exc:  # pragma: no cover - defensive safeguard
            current_app.logger.warning(
                "Automatic backfill of partners.category_id from legacy slug column failed", exc_info=exc
            )
            unmatched = None
        else:
            if unmatched:
                current_app.logger.warning(
                    "Unable to backfill %s partner rows with a category_id automatically",
                    unmatched,
                )
    else:
        current_app.logger.warning(
            "partner_categories table missing while creating partners.category_id; leaving values NULL"
        )

    current_app.logger.info(
        "Added partners.category_id column to legacy schema (backfilled %s rows)",
        backfilled,
    )
    return True


def ensure_partner_categories(seed_defaults: bool = True) -> list[PartnerCategory]:
    """Create the partner categories table when missing and seed defaults."""

    engine = db.engine
    with engine.begin() as connection:
        PartnerCategory.__table__.create(bind=connection, checkfirst=True)

    created = False
    if seed_defaults:
        for order, category in enumerate(DEFAULT_CATEGORY_FALLBACKS.values(), start=1):
            existing = PartnerCategory.query.filter_by(slug=category.slug).first()
            if existing:
                continue
            current_app.logger.info(
                "Bootstrapping default partner category %s", category.slug
            )
            new_category = PartnerCategory(
                slug=category.slug,
                name=category.name,
                description=category.description,
                max_slots=category.max_slots,
                is_active=True,
                sort_order=order * 10,
            )
            db.session.add(new_category)
            created = True

    if created:
        db.session.commit()

    return (
        PartnerCategory.query.order_by(PartnerCategory.sort_order, PartnerCategory.name).all()
    )


def serialize_category_fields(categories: Iterable[PartnerCategory]) -> dict[str, list[dict[str, object]]]:
    """Return the configured form fields for the provided categories."""

    return {
        category.slug: CATEGORY_FORM_FIELDS.get(category.slug, []) for category in categories
    }

