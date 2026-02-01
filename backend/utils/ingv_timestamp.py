from __future__ import annotations

import importlib.util
import logging
import re
from datetime import datetime, timezone

import cv2
import numpy as np

_PYTESSERACT_SPEC = importlib.util.find_spec("pytesseract")
if _PYTESSERACT_SPEC is not None:  # pragma: no cover - optional dependency
    import pytesseract
else:  # pragma: no cover - pytesseract not installed
    pytesseract = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

UPDATED_TIMESTAMP_REGEX = re.compile(
    r"(\d{1,2})\s*[\\/]\s*(\d{1,2})\s*[\\/]\s*(\d{4}).{0,40}?"
    r"(\d{1,2})\s*:\s*(\d{2})\s*UTC",
    re.IGNORECASE | re.DOTALL,
)


def _ensure_ocr_available() -> None:
    if pytesseract is None:
        raise RuntimeError("pytesseract non disponibile: OCR disabilitato per timestamp INGV.")


def _normalize_crop(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scaled = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    blurred = cv2.GaussianBlur(scaled, (3, 3), 0)
    _, thresholded = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresholded


def _parse_updated_timestamp(text: str) -> datetime:
    match = UPDATED_TIMESTAMP_REGEX.search(text)
    if not match:
        raise ValueError("Timestamp aggiornamento INGV non trovato nel testo OCR.")

    day, month, year, hour, minute = (int(part) for part in match.groups())
    current_year = datetime.now(timezone.utc).year
    if year < current_year - 1 or year > current_year + 1:
        raise ValueError(f"Anno OCR fuori range: {year}.")
    if not (1 <= month <= 12):
        raise ValueError(f"Mese OCR fuori range: {month}.")
    if not (1 <= day <= 31):
        raise ValueError(f"Giorno OCR fuori range: {day}.")
    if not (0 <= hour <= 23):
        raise ValueError(f"Ora OCR fuori range: {hour}.")
    if not (0 <= minute <= 59):
        raise ValueError(f"Minuti OCR fuori range: {minute}.")

    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def extract_updated_timestamp_from_image(image: np.ndarray) -> datetime:
    _ensure_ocr_available()
    if image is None or image.size == 0:
        raise ValueError("Immagine PNG INGV vuota; impossibile estrarre timestamp.")

    height, width = image.shape[:2]
    y_top = int(height * 0.22)
    crops = [
        image[:y_top, :],
        image[:y_top, : int(width * 0.7)],
        image[:y_top, int(width * 0.3) :],
    ]

    last_error: Exception | None = None
    for crop in crops:
        prepared = _normalize_crop(crop)
        text = pytesseract.image_to_string(prepared, config="--psm 6")
        try:
            return _parse_updated_timestamp(text)
        except ValueError as exc:
            last_error = exc
            logger.debug("[INGV OCR] Nessun match in crop: %s", text.replace("\n", " "))

    raise ValueError(
        "Timestamp aggiornamento INGV non valido dopo OCR."
        + (f" Ultimo errore: {last_error}" if last_error else "")
    )

