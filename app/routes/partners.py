"""Public routes for the partner directory."""

from __future__ import annotations

from datetime import datetime

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy.orm import joinedload

from app.models import db
from app.models.partner import Partner, PartnerLead, PartnerWaitlist
from app.services.email_service import send_email
from app.utils.csrf import validate_csrf_token
from app.utils.partners import (
    build_contact_actions,
    build_lead_payload,
    build_waitlist_payload,
    filter_visible_partners,
    load_category_with_partners,
    partner_directory_enabled,
    rate_limit,
    require_partner_directory_enabled,
    serialize_partner_for_ldjson,
)


bp = Blueprint("partners", __name__)


def _directory_or_404():
    if not partner_directory_enabled():
        abort(404)


@bp.route("/experience")
def legacy_experience_redirect():
    """Redirect the old experience landing to the partners directory."""

    _directory_or_404()
    return redirect(url_for("category.category_view", slug="guide"))


@bp.route("/guide")
def direct_guide_listing():
    _directory_or_404()
    return redirect(url_for("category.category_view", slug="guide"))


@bp.route("/hotel")
def direct_hotel_listing():
    _directory_or_404()
    return redirect(url_for("category.category_view", slug="hotel"))


@bp.route("/ristoranti")
def direct_restaurant_listing():
    _directory_or_404()
    return redirect(url_for("category.category_view", slug="ristoranti"))


@bp.route("/categoria/<slug>/waitlist", methods=["POST"])
def join_waitlist(slug: str):
    require_partner_directory_enabled()

    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(url_for("category.category_view", slug=slug))

    if not rate_limit(f"waitlist::{slug}"):
        flash("Stai inviando troppe richieste. Riprova tra qualche minuto.", "warning")
        return redirect(url_for("category.category_view", slug=slug))

    category = load_category_with_partners(slug)
    if not category:
        abort(404)

    payload, errors = build_waitlist_payload(request.form)
    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(url_for("category.category_view", slug=slug))

    waitlist = PartnerWaitlist(category_id=category.id, **payload)
    db.session.add(waitlist)
    db.session.commit()

    flash(
        "Grazie! Ti contatteremo non appena si libera uno slot nella categoria.",
        "success",
    )

    admin_email = current_app.config.get("ADMIN_EMAIL")
    if admin_email:
        send_email(
            subject=f"Nuova richiesta lista d'attesa - {category.name}",
            recipients=[admin_email],
            body=render_template(
                "email/partners/waitlist_notification.txt",
                category=category,
                waitlist=waitlist,
            ),
        )

    return redirect(url_for("category.category_view", slug=slug))


@bp.route("/categoria/<slug>/<partner_slug>")
def partner_detail(slug: str, partner_slug: str):
    require_partner_directory_enabled()

    partner = (
        Partner.query.options(
            joinedload(Partner.category),
            joinedload(Partner.subscriptions),
        )
        .filter(Partner.slug == partner_slug)
        .first_or_404()
    )

    if partner.category.slug != slug or not partner.is_publicly_visible():
        abort(404)

    contact_actions = build_contact_actions(partner)
    structured_data = serialize_partner_for_ldjson(partner)
    structured_data["@type"] = "LocalBusiness"
    structured_data["@context"] = "https://schema.org"

    related = [
        other
        for other in filter_visible_partners(partner.category.partners)
        if other.id != partner.id
    ][:4]

    return render_template(
        "partners/detail.html",
        partner=partner,
        category=partner.category,
        contact_actions=contact_actions,
        related_partners=related,
        structured_data=structured_data,
    )


@bp.route("/lead/<int:partner_id>", methods=["POST"])
def create_partner_lead(partner_id: int):
    require_partner_directory_enabled()

    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token di sicurezza non valido.", "error")
        return redirect(request.referrer or url_for("partners.legacy_experience_redirect"))

    if not rate_limit(f"lead::{partner_id}"):
        flash("Hai già inviato un messaggio. Riprova più tardi.", "warning")
        return redirect(request.referrer or url_for("partners.legacy_experience_redirect"))

    partner = (
        Partner.query.options(joinedload(Partner.category), joinedload(Partner.subscriptions))
        .filter_by(id=partner_id)
        .first_or_404()
    )
    if not partner.is_publicly_visible():
        abort(404)

    payload, errors = build_lead_payload(request.form)
    if errors:
        for message in errors:
            flash(message, "error")
        return redirect(
            url_for("partners.partner_detail", slug=partner.category.slug, partner_slug=partner.slug)
        )

    lead = PartnerLead(partner_id=partner.id, **payload)
    db.session.add(lead)
    db.session.commit()

    admin_email = current_app.config.get("ADMIN_EMAIL")
    recipients = [partner.email] if partner.email else []
    bcc = [admin_email] if admin_email else []
    delivery_recipients = recipients or bcc

    if delivery_recipients:
        send_email(
            subject=f"Nuovo contatto per {partner.name}",
            recipients=delivery_recipients,
            bcc=bcc if recipients else None,
            body=render_template(
                "email/partners/lead_notification.txt",
                partner=partner,
                lead=lead,
            ),
        )

    flash("Richiesta inviata con successo.", "success")
    return redirect(
        url_for("partners.partner_detail", slug=partner.category.slug, partner_slug=partner.slug)
    )
