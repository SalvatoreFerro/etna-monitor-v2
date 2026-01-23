#!/usr/bin/env python3
"""Write placeholder Copernicus preview PNGs for smoke tests."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _draw_center_text(image: Image.Image, text: str) -> None:
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.load_default()
    except Exception:  # pragma: no cover - fallback guard
        font = None
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    x = (image.width - text_width) // 2
    y = (image.height - text_height) // 2
    draw.text((x, y), text, fill=(255, 255, 255), font=font)


def write_test_pngs(static_folder: Path | str | None = None) -> dict[str, Path]:
    if static_folder:
        target_folder = Path(static_folder)
    else:
        base_dir = Path(__file__).resolve().parents[1]
        target_folder = base_dir / "app" / "static" / "copernicus"
    target_folder.mkdir(parents=True, exist_ok=True)

    s1_path = target_folder / "s1_latest.png"
    s2_path = target_folder / "s2_latest.png"

    for path, label in ((s1_path, "S1 TEST OK"), (s2_path, "S2 TEST OK")):
        image = Image.new("RGB", (800, 450), color=(27, 42, 74))
        _draw_center_text(image, label)
        image.save(path, format="PNG")

    return {"s1": s1_path, "s2": s2_path}


def main() -> int:
    parser = argparse.ArgumentParser(description="Write test Copernicus preview PNGs.")
    parser.add_argument(
        "--static-dir",
        default=None,
        help="Optional base directory for static/copernicus (defaults to ./app/static/copernicus).",
    )
    args = parser.parse_args()

    target_dir = Path(args.static_dir) if args.static_dir else None
    outputs = write_test_pngs(target_dir)
    for key, path in outputs.items():
        print(f"{key}: {path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
