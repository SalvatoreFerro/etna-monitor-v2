"""Minimal stub for playwright.sync_api used in tests."""

from __future__ import annotations

import contextlib

import pytest


class _StubBrowser:
    def __init__(self) -> None:
        self._closed = False

    def new_page(self):  # pragma: no cover - only used when not skipped
        pytest.skip("Playwright non disponibile in questo ambiente")

    def close(self) -> None:
        self._closed = True


class _StubChromium:
    def launch(self, headless: bool = True):  # pragma: no cover - only used when not skipped
        pytest.skip("Playwright non disponibile in questo ambiente")


class _StubContext:
    chromium = _StubChromium()

    def __enter__(self):
        pytest.skip("Playwright non disponibile in questo ambiente")

    def __exit__(self, exc_type, exc, tb):
        return False


def sync_playwright():
    """Return a context manager that skips tests when Playwright is unavailable."""

    @contextlib.contextmanager
    def _manager():
        pytest.skip("Playwright non disponibile in questo ambiente")
        yield _StubBrowser()

    return _manager()
