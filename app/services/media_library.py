"""Helpers for uploading media assets to Cloudinary."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterable

import cloudinary
import cloudinary.uploader
from flask import current_app
from slugify import slugify
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename


ALLOWED_MEDIA_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MEDIA_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


def configure_cloudinary() -> tuple[bool, str | None]:
    """Configure Cloudinary using environment variables."""

    cloud_name = current_app.config.get("CLOUDINARY_CLOUD_NAME")
    api_key = current_app.config.get("CLOUDINARY_API_KEY")
    api_secret = current_app.config.get("CLOUDINARY_API_SECRET")

    if not cloud_name or not api_key or not api_secret:
        return False, "Cloudinary non configurato: verifica le variabili ambiente."

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    return True, None


def validate_media_file(
    file_storage: FileStorage | None,
    *,
    max_bytes: int,
    allowed_extensions: Iterable[str] = ALLOWED_MEDIA_EXTENSIONS,
    allowed_mime_types: Iterable[str] = ALLOWED_MEDIA_MIME_TYPES,
) -> tuple[bool, str | None, int | None, str | None]:
    """Validate the uploaded file and return metadata needed for uploads."""

    if not file_storage or not file_storage.filename:
        return False, "Seleziona un file immagine da caricare.", None, None

    filename = secure_filename(file_storage.filename)
    if not filename:
        return False, "Nome file non valido.", None, None

    extension = Path(filename).suffix.lower()
    if extension not in set(allowed_extensions):
        return False, "Formato file non supportato. Usa JPG, PNG o WEBP.", None, None

    mimetype = (file_storage.mimetype or "").lower()
    if mimetype not in set(allowed_mime_types):
        return False, "Tipo MIME non supportato. Usa JPG, PNG o WEBP.", None, None

    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)

    if size > max_bytes:
        max_mb = max_bytes / (1024 * 1024)
        return False, f"File troppo grande. Limite: {max_mb:.1f}MB.", size, extension

    return True, None, size, extension


def build_cloudinary_public_id(filename: str) -> str:
    """Build a deterministic Cloudinary public ID for the file."""

    timestamp = int(datetime.utcnow().timestamp())
    base_slug = slugify(Path(filename).stem) or "media"
    now = datetime.utcnow()
    return f"etnamonitor/{now:%Y}/{now:%m}/{base_slug}-{timestamp}"


def upload_media_asset(file_storage: FileStorage) -> dict:
    """Upload the media asset to Cloudinary and return the upload payload."""

    public_id = build_cloudinary_public_id(file_storage.filename or "media")
    # NOTE: Cloudinary handles delivery transformations; EXIF stripping can be added later.
    return cloudinary.uploader.upload(
        file_storage,
        public_id=public_id,
        resource_type="image",
        overwrite=False,
    )
