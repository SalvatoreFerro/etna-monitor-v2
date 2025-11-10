"""Public Etna Experience routes."""

from __future__ import annotations

from math import ceil
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
from ..utils.partners import (
    build_contact_actions,
    extract_partner_payload,
    normalize_category,
    serialize_partner_for_ldjson,
)


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
    page = max(request.args.get("page", default=1, type=int) or 1, 1)
    per_page = 12

    stats = {"total": 0, "guides": 0, "verified": 0, "categories": 0}
    base_query = Partner.query.filter(Partner.visible.is_(True))
    partners: list[Partner] = []
    total_results = 0

    try:
        partners_query = base_query
        if selected_category:
            partners_query = partners_query.filter(Partner.category == selected_category)

        total_results = partners_query.count()

        partners = (
            partners_query.order_by(Partner.verified.desc(), Partner.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
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
        total_results = 0

    if selected_category and not partners:
        flash(
            "Nessun partner disponibile per la categoria selezionata in questo momento.",
            "info",
        )

    pagination = {
        "page": page,
        "per_page": per_page,
        "total": total_results,
        "pages": ceil(total_results / per_page) if total_results else 1,
    }

    experience_stats = [
        {"label": "Esperienze pubblicate", "value": stats["total"]},
        {"label": "Guide specializzate", "value": stats["guides"]},
        {"label": "Partner verificati", "value": stats["verified"]},
        {"label": "Categorie coperte", "value": stats["categories"]},
    ]

    item_list_structured_data = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": "Etna Experience",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": index + 1,
                "item": serialize_partner_for_ldjson(partner),
            }
            for index, partner in enumerate(partners)
        ],
    }

    if selected_category:
        item_list_structured_data["about"] = selected_category

    faq_entries = [
        {
            "question": "Come funziona la prenotazione?",
            "answer": (
                "Scegli la proposta che preferisci e contatta le guide: riceverai una risposta entro 24 ore con disponibilità e suggerimenti personalizzati."
            ),
        },
        {
            "question": "Le esperienze sono per tutti i livelli?",
            "answer": (
                "Ogni partner indica difficoltà e attrezzatura: dai trekking family friendly alle ascese tecniche, trovi sempre briefing dedicati."
            ),
        },
        {
            "question": "Posso combinare più attività nello stesso giorno?",
            "answer": (
                "Sì, le guide EtnaMonitor coordinano logistica e trasferimenti per creare itinerari fluidi tra natura, gusto e relax."
            ),
        },
        {
            "question": "Quali garanzie ho sulla sicurezza?",
            "answer": (
                "Collaboriamo con operatori certificati, coperture assicurative aggiornate e monitoraggio costante dei bollettini vulcanologici."
            ),
        },
    ]

    faq_structured_data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": entry["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": entry["answer"],
                },
            }
            for entry in faq_entries
        ],
    }

    category_label = "Tutte le categorie"
    if selected_category:
        category_label = _FILTER_LABELS.get(selected_category, selected_category)

    page_title = "Etna Experience – escursioni, tour e attività Etna"
    page_description = "Catalogo curato di esperienze sull'Etna tra trekking, jeep tour, fotografia e momenti relax."
    if selected_category:
        page_description = (
            f"Scopri le migliori esperienze {category_label.lower()} curate dal team Etna Experience."
        )

    return render_template(
        "experience.html",
        partners=partners,
        pagination=pagination,
        filter_labels=_available_filters(),
        selected_category=selected_category,
        experience_stats=experience_stats,
        contact_actions={partner.id: build_contact_actions(partner) for partner in partners},
        faq_entries=faq_entries,
        category_label=category_label,
        user=get_current_user(),
        page_title=page_title,
        page_description=page_description,
        page_og_title=page_title,
        page_og_description=page_description,
        page_og_image=url_for(
            "static", filename="images/experience-og-banner.svg", _external=True
        ),
        page_structured_data=[item_list_structured_data, faq_structured_data],
        concierge_email="concierge@etnamonitor.it",
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

