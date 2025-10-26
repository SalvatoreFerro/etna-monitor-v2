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

    try:
        query = Partner.query.filter(Partner.visible.is_(True))
        if selected_category:
            query = query.filter(Partner.category == selected_category)

        partners = (
            query.order_by(Partner.verified.desc(), Partner.created_at.desc())
            .limit(200)
            .all()
        )
    except SQLAlchemyError:
        current_app.logger.exception("Failed to load partners for experience page")
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

    return render_template(
        "experience.html",
        partners=partners,
        filter_labels=_available_filters(),
        selected_category=selected_category,
        user=get_current_user(),
        page_title="Etna Experience – Scopri le attività e le guide dell'Etna",
        page_description="Strutture, escursioni e tour selezionati collegati all'attività vulcanica.",
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
    )

