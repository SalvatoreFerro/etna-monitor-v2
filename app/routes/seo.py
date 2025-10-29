from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Tuple

from flask import Blueprint, Response, current_app, request, url_for


bp = Blueprint("seo", __name__)

# SEO exclusion patterns shared between sitemap and tests
EXCLUDED_PREFIXES = (
    "/admin", "/dashboard", "/auth", "/api", "/internal", 
    "/seo", "/billing", "/livez", "/readyz", "/healthz"
)

EXCLUDED_ENDPOINTS = {
    "static", "legacy_auth.legacy_login", "main.ads_txt", 
    "seo.robots_txt", "seo.sitemap"
}


@bp.route("/seo/health")
def health() -> str:
    return "ok"


def _canonical_base_url() -> str:
    host = current_app.config.get("CANONICAL_HOST") or request.host
    scheme = request.scheme if request.scheme in {"http", "https"} else "https"
    return f"{scheme}://{host}"


def _static_routes() -> Iterable[Tuple[str, str]]:
    return (
        ("main.index", "hourly"),
        ("main.pricing", "weekly"),
        ("main.etna3d", "weekly"),
        ("experience.experience_home", "weekly"),
        ("experience.become_partner", "monthly"),
        ("main.roadmap", "weekly"),
        ("main.sponsor", "monthly"),
        ("main.cookies", "yearly"),
        ("main.privacy", "yearly"),
        ("main.terms", "yearly"),
    )


@bp.route("/sitemap.xml")
def sitemap() -> Response:
    lastmod = datetime.now(timezone.utc).date().isoformat()
    base_url = _canonical_base_url()
    
    # Build a map of static routes with their changefreq
    static_map = dict(_static_routes())
    
    urls = []
    seen_urls = set()
    
    # Traverse all Flask rules to find GET routes without parameters
    for rule in current_app.url_map.iter_rules():
        # Only include GET routes without parameters
        if "GET" not in rule.methods or "<" in str(rule):
            continue
            
        # Skip excluded endpoints
        if rule.endpoint in EXCLUDED_ENDPOINTS:
            continue
            
        # Skip routes that start with excluded prefixes
        if any(rule.rule.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        
        try:
            absolute = url_for(rule.endpoint, _external=True)
            absolute = absolute.replace(request.host_url.rstrip("/"), base_url, 1)
            
            # Avoid duplicates (some routes may have multiple rules)
            if absolute in seen_urls:
                continue
            seen_urls.add(absolute)
            
            # Use predefined changefreq if available, otherwise default to "weekly"
            changefreq = static_map.get(rule.endpoint, "weekly")
            urls.append((absolute, changefreq))
        except Exception:
            # Skip routes that can't be built (e.g., missing parameters, invalid URLs)
            # This catches werkzeug.routing.BuildError and other URL-related exceptions
            continue
    
    # Sort URLs alphabetically for consistency
    urls.sort(key=lambda x: x[0])

    xml = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">",
    ]
    for loc, changefreq in urls:
        xml.extend(
            [
                "  <url>",
                f"    <loc>{loc}</loc>",
                f"    <lastmod>{lastmod}</lastmod>",
                f"    <changefreq>{changefreq}</changefreq>",
                "  </url>",
            ]
        )
    xml.append("</urlset>")
    payload = "\n".join(xml)
    return Response(payload, mimetype="application/xml")


@bp.route("/robots.txt")
def robots_txt() -> Response:
    base_url = _canonical_base_url()
    sitemap_url = f"{base_url}/sitemap.xml"
    
    # Build content dynamically using shared exclusion constants
    content_lines = ["User-agent: *", "Allow: /"]
    
    # Add Disallow directives from shared constants
    for prefix in EXCLUDED_PREFIXES:
        content_lines.append(f"Disallow: {prefix}")
    
    content_lines.extend([f"Sitemap: {sitemap_url}", ""])
    
    content = "\n".join(content_lines)
    return Response(content, mimetype="text/plain")
