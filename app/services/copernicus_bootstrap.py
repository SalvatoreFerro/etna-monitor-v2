"""Startup helpers for Copernicus Smart View previews."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

_BOOTSTRAP_DONE = False


def ensure_copernicus_previews(app: Flask) -> None:
    """Ensure Copernicus preview images exist at boot."""

    global _BOOTSTRAP_DONE
    if _BOOTSTRAP_DONE:
        return
    _BOOTSTRAP_DONE = True

    static_folder = Path(app.static_folder) / "copernicus"
    static_folder.mkdir(parents=True, exist_ok=True)

    s1_path = static_folder / "s1_latest.png"
    s2_path = static_folder / "s2_latest.png"
    if s1_path.exists() and s2_path.exists():
        app.logger.info("[BOOT] Copernicus previews già presenti: %s", static_folder)
        return

    try:
        from scripts.update_copernicus_previews import main as update_previews

        app.logger.info("[BOOT] Copernicus preview mancanti: avvio update_copernicus_previews")
        update_previews()
        return
    except Exception as exc:
        app.logger.warning(
            "[BOOT] Copernicus update fallito: %s. Scrivo PNG di test.", exc
        )

    try:
        from scripts.write_test_png import write_test_pngs

        outputs = write_test_pngs(static_folder)
        app.logger.info("[BOOT] Copernicus test PNG scritti: %s", outputs)
    except Exception as exc:
        app.logger.error("[BOOT] Scrittura PNG di test fallita: %s", exc)
