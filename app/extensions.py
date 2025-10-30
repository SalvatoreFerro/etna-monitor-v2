"""Application-wide extension instances."""

from flask_caching import Cache
from flask_compress import Compress

# Simple in-memory cache suitable for single-process deployments like Render Free.
cache = Cache()

# Compression for responses (Brotli and Gzip)
compress = Compress()

__all__ = ["cache", "compress"]
