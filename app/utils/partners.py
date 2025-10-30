"""Utilities shared between public and admin partner flows."""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Tuple
from urllib.parse import quote

from app.models.partner import PARTNER_CATEGORIES, Partner


_BOOL_TRUE = {"1", "true", "on", "yes", "y", "si", "sì"}
_MAX_DESCRIPTION_LENGTH = 800
_MAX_URL_LENGTH = 512
_MAX_CONTACT_LENGTH = 255

_PHONE_RE = re.compile(r"^(?:\+|00)?[\d\s().-]{6,}$")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def normalize_category(raw: str | None) -> str | None:
    """Return a sanitized category or ``None`` if invalid."""

    if not raw:
        return None
    value = raw.strip()
    if value.lower() == "ristoranti":
        value = "Ristorante"
    if value in PARTNER_CATEGORIES:
        return value
    return None


def _parse_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in _BOOL_TRUE


def _parse_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_partner_payload(
    form: Mapping[str, Any], *, is_admin: bool = False
) -> Tuple[dict[str, Any], list[str]]:
    """Validate incoming partner fields and normalize the payload."""

    errors: list[str] = []
    payload: dict[str, Any] = {}

    name = (form.get("name") or "").strip()
    if not name:
        errors.append("Il nome dell'attività è obbligatorio.")
    payload["name"] = name

    category = normalize_category(form.get("category"))
    if category is None:
        errors.append("Seleziona una categoria valida.")
        category = "Altro"
    payload["category"] = category

    description = (form.get("description") or "").strip()
    if len(description) > _MAX_DESCRIPTION_LENGTH:
        errors.append("La descrizione deve contenere al massimo 800 caratteri.")
    payload["description"] = description

    website = (form.get("website") or "").strip()
    if website and len(website) > _MAX_URL_LENGTH:
        errors.append("Il link fornito è troppo lungo.")
    payload["website"] = website

    contact = (form.get("contact") or "").strip()
    if contact and len(contact) > _MAX_CONTACT_LENGTH:
        errors.append("Il contatto fornito è troppo lungo.")
    payload["contact"] = contact

    image_url = (form.get("image_url") or "").strip()
    if image_url and len(image_url) > _MAX_URL_LENGTH:
        errors.append("Il link dell'immagine è troppo lungo.")
    payload["image_url"] = image_url

    if is_admin:
        payload["lat"] = _parse_float(form.get("lat"))
        payload["lon"] = _parse_float(form.get("lon"))
        payload["verified"] = _parse_bool(form.get("verified"))
        payload["visible"] = _parse_bool(form.get("visible"), default=True)
    else:
        payload["lat"] = None
        payload["lon"] = None
        payload["verified"] = False
        payload["visible"] = False

    return payload, errors


def build_contact_actions(partner: Partner) -> list[dict[str, str]]:
    """Return actionable contact buttons for a partner.

    The legacy ``contact`` field is free text, so we try to detect common
    patterns (emails, phone numbers, WhatsApp links, social URLs) and expose
    them as structured actions that the template can render as CTA buttons.
    """

    if not partner.contact:
        return []

    actions: list[dict[str, str]] = []
    raw_tokens: Iterable[str] = re.split(r"[,;/\n]+", partner.contact)

    for token in raw_tokens:
        value = token.strip()
        if not value:
            continue

        lower = value.lower()
        if lower.startswith("tel:"):
            number = value[4:]
            actions.append(
                {
                    "href": f"tel:{number.strip()}",
                    "label": "Chiama",
                    "display": number.strip(),
                }
            )
            continue

        if "@" in value and " " not in value:
            actions.append(
                {
                    "href": f"mailto:{value}",
                    "label": "Scrivi via email",
                    "display": value,
                }
            )
            continue

        if "wa.me" in lower or "whatsapp" in lower:
            href = value if _URL_RE.search(value) else f"https://wa.me/{value}"
            actions.append(
                {
                    "href": href,
                    "label": "Chatta su WhatsApp",
                    "display": value,
                }
            )
            continue

        if _URL_RE.search(value):
            label = "Apri link"
            if "instagram" in lower:
                label = "Apri Instagram"
            elif "facebook" in lower:
                label = "Apri Facebook"
            elif "tripadvisor" in lower:
                label = "Leggi su TripAdvisor"
            actions.append(
                {
                    "href": value,
                    "label": label,
                    "display": value,
                }
            )
            continue

        if _PHONE_RE.match(value):
            normalized = re.sub(r"[^\d+]", "", value)
            actions.append(
                {
                    "href": f"tel:{normalized}",
                    "label": "Chiama",
                    "display": value,
                }
            )
            continue

        actions.append(
            {
                "href": f"mailto:{quote(value)}",
                "label": "Contatta",
                "display": value,
            }
        )

    # Ensure deterministic order (emails first, then phones, then others)
    priority = {"Scrivi via email": 0, "Chiama": 1, "Chatta su WhatsApp": 2}
    actions.sort(key=lambda item: priority.get(item["label"], 3))
    return actions


def serialize_partner_for_ldjson(partner: Partner) -> dict[str, Any]:
    """Convert partner data into a schema.org compatible dictionary."""

    category = partner.category_label()
    partner_type = "LocalBusiness"
    if category == "Guide" or category == "Tour":
        partner_type = "TouristAttraction"

    data: dict[str, Any] = {
        "@type": partner_type,
        "name": partner.name,
        "url": partner.website or "",
        "description": partner.description or "",
        "areaServed": "Etna, Sicilia",
        "category": category,
        "identifier": partner.id,
    }

    if partner.image_url:
        data["image"] = partner.image_url
    if partner.contact:
        data["contactPoint"] = {
            "@type": "ContactPoint",
            "contactType": "customer support",
            "telephone": partner.contact,
        }
    if partner.lat and partner.lon:
        data["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": partner.lat,
            "longitude": partner.lon,
        }

    return data

