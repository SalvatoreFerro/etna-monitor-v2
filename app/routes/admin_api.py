from __future__ import annotations

from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy import func

from ..models import ApiClient, ApiKey, ApiUsageDaily, db
from ..utils.api_keys import generate_api_key
from ..utils.attribution import attribution_snippet
from ..utils.auth import admin_required
from ..utils.csrf import validate_csrf_token

bp = Blueprint("admin_api", __name__)

PLAN_OPTIONS = ["FREE", "PARTNER", "PRO"]


def _usage_summary(client_id: int) -> dict:
    today = datetime.utcnow().date()

    def _sum_range(days: int) -> int:
        start = today - timedelta(days=days - 1)
        total = (
            db.session.query(func.coalesce(func.sum(ApiUsageDaily.requests_count), 0))
            .join(ApiKey, ApiUsageDaily.key_id == ApiKey.id)
            .filter(
                ApiKey.client_id == client_id,
                ApiUsageDaily.date >= start,
                ApiUsageDaily.date <= today,
            )
            .scalar()
        )
        return int(total or 0)

    return {
        "today": _sum_range(1),
        "last_7_days": _sum_range(7),
        "last_30_days": _sum_range(30),
    }


@bp.get("/admin/api")
@admin_required
def api_clients():
    clients = (
        db.session.query(ApiClient, func.count(ApiKey.id).label("keys_count"))
        .outerjoin(ApiKey, ApiKey.client_id == ApiClient.id)
        .group_by(ApiClient.id)
        .order_by(ApiClient.created_at.desc())
        .all()
    )
    return render_template(
        "admin/api_clients.html",
        clients=clients,
    )


@bp.route("/admin/api/clients/new", methods=["GET", "POST"])
@admin_required
def api_clients_new():
    if request.method == "POST":
        if not validate_csrf_token(request.form.get("csrf_token")):
            flash("Token CSRF non valido.", "error")
            return redirect(url_for("admin_api.api_clients_new"))

        name = (request.form.get("name") or "").strip()
        contact_email = (request.form.get("contact_email") or "").strip() or None
        plan = (request.form.get("plan") or "FREE").strip().upper()
        is_active = request.form.get("is_active") == "on"

        if not name:
            flash("Il nome client è obbligatorio.", "error")
            return redirect(url_for("admin_api.api_clients_new"))

        if plan not in PLAN_OPTIONS:
            plan = "FREE"

        existing = ApiClient.query.filter_by(name=name).first()
        if existing:
            flash("Esiste già un client con questo nome.", "error")
            return redirect(url_for("admin_api.api_clients_new"))

        client = ApiClient(
            name=name,
            contact_email=contact_email,
            plan=plan,
            is_active=is_active,
        )
        db.session.add(client)
        db.session.commit()
        flash("Client creato con successo.", "success")
        return redirect(url_for("admin_api.api_client_detail", client_id=client.id))

    return render_template("admin/api_client_new.html", plans=PLAN_OPTIONS)


@bp.route("/admin/api/clients/<int:client_id>", methods=["GET", "POST"])
@admin_required
def api_client_detail(client_id: int):
    client = ApiClient.query.get_or_404(client_id)
    raw_key = None

    if request.method == "POST":
        if not validate_csrf_token(request.form.get("csrf_token")):
            flash("Token CSRF non valido.", "error")
            return redirect(url_for("admin_api.api_client_detail", client_id=client_id))

        action = request.form.get("action")
        if action == "update_client":
            name = (request.form.get("name") or "").strip()
            contact_email = (request.form.get("contact_email") or "").strip() or None
            plan = (request.form.get("plan") or client.plan).strip().upper()
            is_active = request.form.get("is_active") == "on"

            if not name:
                flash("Il nome client è obbligatorio.", "error")
                return redirect(
                    url_for("admin_api.api_client_detail", client_id=client_id)
                )

            if plan not in PLAN_OPTIONS:
                plan = client.plan

            client.name = name
            client.contact_email = contact_email
            client.plan = plan
            client.is_active = is_active
            db.session.commit()
            flash("Client aggiornato.", "success")
            return redirect(url_for("admin_api.api_client_detail", client_id=client_id))

        if action == "create_key":
            label = (request.form.get("label") or "").strip() or None
            raw_key, prefix, key_hash = generate_api_key()
            new_key = ApiKey(
                client_id=client.id,
                key_hash=key_hash,
                prefix=prefix,
                label=label,
            )
            db.session.add(new_key)
            db.session.commit()
            flash("Nuova API key generata.", "success")

    keys = (
        ApiKey.query.filter_by(client_id=client.id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    usage_summary = _usage_summary(client.id)

    return render_template(
        "admin/api_client_detail.html",
        client=client,
        keys=keys,
        raw_key=raw_key,
        plans=PLAN_OPTIONS,
        usage_summary=usage_summary,
        attribution=attribution_snippet(),
    )


@bp.post("/admin/api/keys/<int:key_id>/toggle")
@admin_required
def api_key_toggle(key_id: int):
    api_key = ApiKey.query.get_or_404(key_id)
    if not validate_csrf_token(request.form.get("csrf_token")):
        flash("Token CSRF non valido.", "error")
        return redirect(
            url_for("admin_api.api_client_detail", client_id=api_key.client_id)
        )

    api_key.is_revoked = not api_key.is_revoked
    db.session.commit()
    state_label = "revocata" if api_key.is_revoked else "riattivata"
    flash(f"API key {state_label}.", "success")
    return redirect(url_for("admin_api.api_client_detail", client_id=api_key.client_id))
