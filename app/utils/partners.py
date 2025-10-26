"""Utilities shared between public and admin partner flows."""

from __future__ import annotations

from typing import Any, Mapping, Tuple

from app.models.partner import PARTNER_CATEGORIES


_BOOL_TRUE = {"1", "true", "on", "yes", "y", "si", "sì"}
_MAX_DESCRIPTION_LENGTH = 800
_MAX_URL_LENGTH = 512
_MAX_CONTACT_LENGTH = 255


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

