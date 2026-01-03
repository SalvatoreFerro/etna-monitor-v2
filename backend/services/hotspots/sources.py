from __future__ import annotations

from .config import HotspotsConfig


def build_sources(config: HotspotsConfig) -> tuple[list[str], list[str]]:
    sources: list[str] = []
    platforms: list[str] = []
    if config.dataset == "VIIRS":
        platform_map = {
            "SNPP": "VIIRS_SNPP_NRT",
            "NOAA20": "VIIRS_NOAA20_NRT",
            "NOAA21": "VIIRS_NOAA21_NRT",
        }
        candidates = list(config.include_platforms) or ["SNPP", "NOAA20", "NOAA21"]
        for platform in candidates:
            source = platform_map.get(platform.upper())
            if source:
                platforms.append(platform.upper())
                sources.append(source)
    else:
        sources.append(config.source)
        if config.dataset == "MODIS":
            platforms.append("MODIS")

    if config.include_modis and "MODIS_NRT" not in sources:
        sources.append("MODIS_NRT")
        platforms.append("MODIS")

    if not sources:
        sources.append(config.source)

    return sources, platforms


__all__ = ["build_sources"]
