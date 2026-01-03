from __future__ import annotations

from .config import HotspotsConfig


def _platforms_from_products(products: list[str]) -> list[str]:
    platforms: list[str] = []
    for product in products:
        upper = product.upper()
        if "MODIS" in upper:
            platform = "MODIS"
        elif "NOAA20" in upper:
            platform = "NOAA20"
        elif "NOAA21" in upper:
            platform = "NOAA21"
        elif "SNPP" in upper:
            platform = "SNPP"
        elif "VIIRS" in upper:
            platform = "VIIRS"
        else:
            platform = "UNKNOWN"
        if platform not in platforms:
            platforms.append(platform)
    return platforms


def build_sources(config: HotspotsConfig) -> tuple[list[str], list[str]]:
    sources: list[str] = []
    platforms: list[str] = []
    if config.products:
        sources = list(dict.fromkeys(config.products))
        platforms = _platforms_from_products(sources)
        return sources, platforms

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
