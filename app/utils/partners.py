"""Helpers for the partner directory flows."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
import re
from typing import Iterable, Mapping

from flask import current_app, session
from slugify import slugify
from sqlalchemy.orm import joinedload

from app.models.partner import Partner, PartnerCategory


_CONTACT_ACTIONS_PRIORITY = {"call": 0, "whatsapp": 1, "email": 2, "website": 3, "social": 4}
_ALLOWED_SOCIALS = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "tiktok": "TikTok",
}
_RATE_LIMIT_SECONDS = 60
_RATE_LIMIT_BUCKET = 3


def partner_directory_enabled() -> bool:
    return bool(current_app.config.get("PARTNER_DIRECTORY_ENABLED"))


def require_partner_directory_enabled() -> None:
    if not partner_directory_enabled():
        from flask import abort

        abort(404)


def slugify_partner_name(name: str) -> str:
    base = slugify(name or "partner")[:110]
    return base or "partner"


def next_partner_slug(name: str) -> str:
    base = slugify_partner_name(name)
    candidate = base
    suffix = 1
    while Partner.query.filter_by(slug=candidate).first():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def load_category_with_partners(slug: str) -> PartnerCategory | None:
    return (
        PartnerCategory.query.options(
            joinedload(PartnerCategory.partners).joinedload(Partner.subscriptions)
        )
        .filter_by(slug=slug, is_active=True)
        .first()
    )


def filter_visible_partners(partners: Iterable[Partner], *, reference_date=None) -> list[Partner]:
    visible = [partner for partner in partners if partner.is_publicly_visible(reference_date)]
    visible.sort(
        key=lambda partner: (
            -int(partner.featured),
            partner.sort_order,
            partner.approved_at.timestamp() if partner.approved_at else float("inf"),
        )
    )
    return visible


def build_contact_actions(partner: Partner) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []

    if partner.phone:
        sanitized = re.sub(r"[^\d+]", "", partner.phone)
        actions.append(
            {
                "type": "call",
                "label": "Chiama",
                "href": f"tel:{sanitized}",
                "display": partner.phone,
            }
        )

    if partner.whatsapp:
        sanitized = re.sub(r"[^\d+]", "", partner.whatsapp)
        href = f"https://wa.me/{sanitized}"
        actions.append(
            {
                "type": "whatsapp",
                "label": "Chatta su WhatsApp",
                "href": href,
                "display": partner.whatsapp,
            }
        )

    if partner.email:
        actions.append(
            {
                "type": "email",
                "label": "Scrivi via email",
                "href": f"mailto:{partner.email}",
                "display": partner.email,
            }
        )

    if partner.website_url:
        actions.append(
            {
                "type": "website",
                "label": "Visita il sito",
                "href": partner.website_url,
                "display": partner.website_url,
            }
        )

    for attr, label in _ALLOWED_SOCIALS.items():
        value = getattr(partner, attr)
        if value:
            actions.append(
                {
                    "type": "social",
                    "label": f"Apri {label}",
                    "href": value,
                    "display": value,
                }
            )

    actions.sort(key=lambda item: (_CONTACT_ACTIONS_PRIORITY.get(item["type"], 99)))
    return actions


def serialize_partner_for_ldjson(partner: Partner) -> dict[str, object]:
    data: dict[str, object] = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": partner.name,
        "url": current_app.config.get("SITE_URL", "https://www.etnamonitor.it")
        + f"/categoria/{partner.category.slug}/{partner.slug}",
        "description": partner.short_desc or partner.long_desc or "",
        "address": {
            "@type": "PostalAddress",
            "streetAddress": partner.address or "",
            "addressLocality": partner.city or "",
            "addressRegion": "CT",
            "addressCountry": "IT",
        },
    }
    if partner.phone:
        data["telephone"] = partner.phone
    if partner.email:
        data["email"] = partner.email
    if partner.website_url:
        data["sameAs"] = [partner.website_url]
    socials = [getattr(partner, key) for key in _ALLOWED_SOCIALS.keys() if getattr(partner, key)]
    if socials:
        data.setdefault("sameAs", []).extend(socials)
    return data


def rate_limit(key: str) -> bool:
    bucket_key = f"partner_rl::{key}"
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=_RATE_LIMIT_SECONDS)

    entries = deque(session.get(bucket_key, []))
    while entries and datetime.fromisoformat(entries[0]) < window_start:
        entries.popleft()

    if len(entries) >= _RATE_LIMIT_BUCKET:
        session[bucket_key] = list(entries)
        session.modified = True
        return False

    entries.append(now.isoformat())
    session[bucket_key] = list(entries)
    session.modified = True
    return True


def build_waitlist_payload(form: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip()
    phone = (form.get("phone") or "").strip()
    notes = (form.get("notes") or "").strip()

    errors: list[str] = []
    if not name:
        errors.append("Il nome è obbligatorio.")
    if not email or "@" not in email:
        errors.append("Inserisci un'email valida.")

    payload = {
        "name": name,
        "email": email,
        "phone": phone,
        "notes": notes,
    }
    return payload, errors


def build_lead_payload(form: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    name = (form.get("name") or "").strip()
    email = (form.get("email") or "").strip()
    phone = (form.get("phone") or "").strip()
    message = (form.get("message") or "").strip()

    errors: list[str] = []
    if not name:
        errors.append("Il nome è obbligatorio.")
    if not email or "@" not in email:
        errors.append("Inserisci un'email valida.")

    payload = {
        "name": name,
        "email": email,
        "phone": phone,
        "message": message,
        "source": {
            "utm": {key: form.get(key) for key in ("utm_source", "utm_medium", "utm_campaign") if form.get(key)},
        },
    }
    return payload, errors
