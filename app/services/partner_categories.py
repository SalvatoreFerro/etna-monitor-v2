"""Shared helpers for partner categories fallbacks and admin bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from flask import current_app
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

