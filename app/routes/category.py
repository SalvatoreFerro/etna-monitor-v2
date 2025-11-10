"""Public category listings for Etna Experience."""

from __future__ import annotations

from datetime import date

from flask import Blueprint, abort, current_app, render_template
from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from app.models import db
from app.models.partner import Partner, PartnerCategory, PartnerSubscription
from app.services.partner_categories import (
    DEFAULT_CATEGORY_FALLBACKS,
    StaticCategory,
    missing_table_error,
)


bp = Blueprint("category", __name__, url_prefix="/categoria")


@bp.route("/<slug>")
def category_view(slug: str):
    """Render the public listing for a partner category."""

    # Defensive rollback to avoid stale failed transactions.
    db.session.rollback()

    if not current_app.config.get("PARTNER_DIRECTORY_ENABLED"):
        abort(404)

    today = date.today()

    try:
        category = (
            PartnerCategory.query.filter_by(slug=slug, is_active=True).first()
        )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive logging
        db.session.rollback()
        if missing_table_error(exc, "partner_categories"):
            static_category: StaticCategory | None = DEFAULT_CATEGORY_FALLBACKS.get(slug)
            if static_category is None:
                current_app.logger.warning(
                    "Category %s requested but partner_categories table missing and no fallback available",
                    slug,
                )
                abort(404)
            current_app.logger.warning(
                "Partner categories table unavailable; using static fallback for %s",
                slug,
            )
            category = static_category
        else:
            current_app.logger.error(
                "Unable to load category %s: %s", slug, exc, exc_info=exc
            )
            abort(500)

    if category is None:
        abort(404)

    try:
        if getattr(category, "id", None) is None:
            partners = []
        else:
            partners = (
                Partner.query.filter(
                    Partner.category_id == category.id,
                    Partner.status == "approved",
                    Partner.subscriptions.any(
                        and_(
                            PartnerSubscription.status == "paid",
                            PartnerSubscription.valid_to >= today,
                            or_(
                                PartnerSubscription.valid_from == None,  # noqa: E711
                                PartnerSubscription.valid_from <= today,
                            ),
                        )
                    ),
                )
                .order_by(
                    Partner.featured.desc(),
                    Partner.sort_order.asc(),
                    Partner.approved_at.asc(),
                )
                .limit(category.max_slots)
                .all()
            )
    except SQLAlchemyError as exc:  # pragma: no cover - defensive logging
        db.session.rollback()
        if missing_table_error(exc, "partner_subscriptions"):
            current_app.logger.warning(
                "Partner subscriptions table unavailable; falling back to empty listing for category %s",
                slug,
            )
            partners = []
        else:
            current_app.logger.error(
                "Unable to load partners for %s: %s", slug, exc, exc_info=exc
            )
            abort(500)

    occupied = len(partners)
    max_slots = category.max_slots
    is_full = occupied >= max_slots

    return render_template(
        "category/list.html",
        category=category,
        partners=partners,
        occupied=occupied,
        is_full=is_full,
        max_slots=max_slots,
    )
