"""Public Etna Experience routes."""

from __future__ import annotations

from typing import Iterable, Tuple

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from sqlalchemy.exc import SQLAlchemyError

from ..models import db
from ..models.partner import PARTNER_CATEGORIES, Partner
from ..utils.auth import get_current_user
from ..utils.csrf import validate_csrf_token
from ..utils.partners import extract_partner_payload, normalize_category


bp = Blueprint("experience", __name__)


_FILTER_LABELS: dict[str, str] = {
    "all": "Tutti",
    "Guide": "Guide",
    "Hotel": "Hotel",
    "Ristorante": "Ristoranti",
    "Tour": "Tour",
    "Altro": "Altro",
}


def _available_filters() -> Iterable[Tuple[str, str]]:
    return [(key, label) for key, label in _FILTER_LABELS.items()]


@bp.route("/experience")
def experience_home():
    """Display the public Etna Experience directory."""

    selected_category = normalize_category(request.args.get("category"))

    stats = {"total": 0, "guides": 0, "verified": 0, "categories": 0}

    try:
        base_query = Partner.query.filter(Partner.visible.is_(True))
        partners_query = base_query
        if selected_category:
            partners_query = partners_query.filter(Partner.category == selected_category)

        partners = (
            partners_query.order_by(Partner.verified.desc(), Partner.created_at.desc())
            .limit(200)
            .all()
        )

        stats["total"] = base_query.count()
        stats["guides"] = base_query.filter(Partner.category == "Guide").count()
        stats["verified"] = base_query.filter(Partner.verified.is_(True)).count()

        category_rows = (
            db.session.query(Partner.category)
            .filter(Partner.visible.is_(True))
            .distinct()
            .all()
        )
        stats["categories"] = len({row[0] or "Altro" for row in category_rows})
    except SQLAlchemyError:
        current_app.logger.exception("Failed to load partners for experience page")
        db.session.rollback()
        flash(
            "Al momento non è possibile mostrare i partner disponibili. Riprova più tardi.",
            "warning",
        )
        partners = []

    if selected_category and not partners:
        flash(
            "Nessun partner disponibile per la categoria selezionata in questo momento.",
            "info",
        )

    experience_stats = [
        {"label": "Esperienze pubblicate", "value": stats["total"]},
        {"label": "Guide specializzate", "value": stats["guides"]},
        {"label": "Partner verificati", "value": stats["verified"]},
        {"label": "Categorie coperte", "value": stats["categories"]},
    ]

    return render_template(
        "experience.html",
        partners=partners,
        filter_labels=_available_filters(),
        selected_category=selected_category,
        experience_stats=experience_stats,
        user=get_current_user(),
        page_title="Etna Experience – Scopri le attività e le guide dell'Etna",
        page_description="Strutture, escursioni e tour selezionati collegati all'attività vulcanica.",
        page_og_title="Etna Experience – Scopri le attività e le guide dell'Etna",
        page_og_description="Strutture, escursioni e tour selezionati collegati all'attività vulcanica.",
    )


@bp.route("/become-partner", methods=["GET", "POST"])
def become_partner():
    """Allow organisations to apply for Etna Experience visibility."""

    if request.method == "POST":
        if not validate_csrf_token(request.form.get("csrf_token")):
            flash("Token CSRF non valido. Riprova.", "error")
            return redirect(url_for("experience.become_partner"))

        payload, errors = extract_partner_payload(request.form)

        if not request.form.get("privacy_consent"):
            errors.append(
                "Devi acconsentire al trattamento dei dati per inviare la richiesta."
            )

        if errors:
            for message in errors:
                flash(message, "error")
        else:
            partner = Partner(**payload)

            db.session.add(partner)
            try:
                db.session.commit()
            except Exception as exc:  # pragma: no cover - defensive logging
                current_app.logger.exception("Failed to store partner request")
                db.session.rollback()
                flash(
                    "Si è verificato un errore durante l'invio della candidatura. Riprovare più tardi.",
                    "error",
                )
            else:
                flash(
                    "Grazie! La tua candidatura è stata inviata e sarà esaminata dal team di EtnaMonitor.",
                    "success",
                )
                return redirect(url_for("experience.become_partner"))

    return render_template(
        "become_partner.html",
        categories=_available_filters()[1:],  # exclude "Tutti"
        page_title="Diventa partner – Etna Experience",
        page_description="Invia la tua attività per apparire nella sezione Etna Experience di EtnaMonitor.",
        page_og_title="Diventa partner – Etna Experience",
        page_og_description="Invia la tua attività per apparire nella sezione Etna Experience di EtnaMonitor.",
    )

