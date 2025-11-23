"""Utilities to generate EtnaMonitor blog drafts with OpenAI.

Add your OpenAI API key to the environment, for example in a local ``.env`` file::

    OPENAI_API_KEY="la_tua_chiave"

Or configure it from your hosting provider's environment variable section (Render, Railway, etc.).
The key is loaded at runtime via ``os.getenv('OPENAI_API_KEY')``; never hardcode it in the codebase.
"""

from __future__ import annotations

import os
from typing import Any

from openai import OpenAI

# Configure the OpenAI client using the environment variable.
# You can swap the model (e.g. ``gpt-5.1`` or ``gpt-4.1-mini``) by
# editing the ``model`` parameter inside ``generate_ai_article``.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


def _extract_meta_fields(markdown_text: str) -> tuple[str | None, str | None]:
    """Return (meta_title, meta_description) from annotated markdown lines."""

    meta_title = None
    meta_description = None
    for line in markdown_text.splitlines():
        normalized = line.lower().strip()
        if normalized.startswith("meta title") or normalized.startswith("meta titolo"):
            meta_title = line.split(":", 1)[1].strip() if ":" in line else line[10:].strip()
        if normalized.startswith("meta description") or normalized.startswith("descrizione meta"):
            meta_description = line.split(":", 1)[1].strip() if ":" in line else line[16:].strip()
    return meta_title or None, meta_description or None


def _extract_title(markdown_text: str, fallback: str) -> str:
    """Return the first H1 title or a sanitized fallback."""

    for line in markdown_text.splitlines():
        striped = line.strip()
        if striped.startswith("# "):
            return striped.lstrip("# ").strip() or fallback
    return fallback


def _extract_response_text(response: Any) -> str | None:
    """Return the first text block from a Responses API payload."""

    try:
        content_blocks = response.output[0].content  # type: ignore[index,attr-defined]
    except Exception:
        return None

    for block in content_blocks:
        text = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if text:
            return str(text)
    return None


def generate_ai_article(topic: str, main_keyword: str, target_length: str, tone: str) -> dict[str, Any]:
    """Generate a markdown draft for the EtnaMonitor blog using OpenAI.

    Returns a mapping with ``markdown`` plus optional ``meta_title`` and
    ``meta_description`` keys. Raises ``RuntimeError`` on failures so the caller
    can surface a user-friendly message.
    """

    if not OPENAI_API_KEY or not OPENAI_API_KEY.strip():
        raise RuntimeError("Configura OPENAI_API_KEY nelle variabili d'ambiente.")

    system_prompt = (
        "Sei un redattore scientifico per EtnaMonitor.it. Scrivi in italiano, tono chiaro, "
        "prudente e non allarmistico. Spiega concetti su Etna, sismicità e tremore vulcanico "
        "in modo comprensibile, senza inventare dati o allerte ufficiali. Se servono riferimenti "
        "specifici su allerte o bollettini, invita a consultare INGV o Protezione Civile."
    )

    user_prompt = (
        "Crea un articolo di blog in markdown con queste indicazioni:\n"
        f"- Argomento: {topic}\n"
        f"- Keyword principale: {main_keyword}\n"
        f"- Lunghezza desiderata: {target_length} (max ~1200 parole)\n"
        f"- Tono: {tone}\n\n"
        "Includi un Titolo H1, un meta title consigliato, una meta description consigliata, "
        "struttura con H2/H3, corpo testuale in markdown, 3-5 FAQ finali e suggerimenti di 2-3 link interni pertinenti "
        "(es. /eruzione-etna-oggi, /webcam-etna, /etnabot, /experience). Evita toni allarmistici e "
        "ricorda di rimandare alle fonti ufficiali (INGV) per eventuali allerte."
    )

    try:
        if hasattr(client, "responses"):
            response = client.responses.create(
                model="gpt-5.1-mini",
                input=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = _extract_response_text(response)
        else:  # pragma: no cover - legacy SDK compatibility
            import openai as legacy_openai

            legacy_openai.api_key = OPENAI_API_KEY
            completion = legacy_openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            content = completion.choices[0].message["content"]
    except Exception as exc:  # pragma: no cover - network/API errors
        raise RuntimeError(f"Errore nella generazione dell'articolo: {exc}") from exc

    if not content or not str(content).strip():
        raise RuntimeError("La risposta di OpenAI è vuota.")

    markdown = str(content).strip()
    meta_title, meta_description = _extract_meta_fields(markdown)
    title = _extract_title(markdown, fallback=topic)

    return {
        "markdown": markdown,
        "title": title,
        "meta_title": meta_title,
        "meta_description": meta_description,
    }
