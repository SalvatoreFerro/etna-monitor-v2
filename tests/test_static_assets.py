from __future__ import annotations

from pathlib import Path


def _static_directories() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    static_root = repo_root / "app" / "static"
    return [
        static_root / "images",
        static_root / "icons",
        static_root / "screenshots",
    ]


def test_static_assets_are_non_empty_files():
    missing_dirs: list[Path] = []
    empty_files: list[Path] = []

    for directory in _static_directories():
        if not directory.exists():
            missing_dirs.append(directory)
            continue
        for file_path in directory.rglob("*"):
            if file_path.is_file() and file_path.stat().st_size == 0:
                empty_files.append(file_path)

    assert not missing_dirs, f"Static directories missing from repository: {missing_dirs}"
    assert not empty_files, f"Static asset files must not be empty: {empty_files}"
