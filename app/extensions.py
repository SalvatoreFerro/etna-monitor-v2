"""Application-wide extension instances."""

from flask_caching import Cache

# Simple in-memory cache suitable for single-process deployments like Render Free.
cache = Cache()

__all__ = ["cache"]
