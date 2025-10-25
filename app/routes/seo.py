from __future__ import annotations

from datetime import datetime
from typing import Iterable, Tuple

from flask import Blueprint, Response, current_app, request, url_for


bp = Blueprint("seo", __name__)


@bp.route("/seo/health")
def health() -> str:
    return "ok"


def _canonical_base_url() -> str:
    host = current_app.config.get("CANONICAL_HOST") or request.host
    scheme = request.scheme if request.scheme in {"http", "https"} else "https"
    return f"{scheme}://{host}"


def _static_routes() -> Iterable[Tuple[str, str]]:
    return (
        ("main.index", "daily"),
        ("dashboard.dashboard_home", "hourly"),
        ("main.roadmap", "weekly"),
        ("main.sponsor", "weekly"),
        ("main.pricing", "weekly"),
        ("main.privacy", "yearly"),
        ("main.terms", "yearly"),
    )


@bp.route("/sitemap.xml")
def sitemap() -> Response:
    lastmod = datetime.utcnow().date().isoformat()
    base_url = _canonical_base_url()
    urls = []
    for endpoint, changefreq in _static_routes():
        try:
            absolute = url_for(endpoint, _external=True)
        except Exception:
            continue
        absolute = absolute.replace(request.host_url.rstrip("/"), base_url, 1)
        urls.append((absolute, changefreq))

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
    content = "\n".join(
        [
            "User-agent: *",
            "Disallow: /admin",
            f"Sitemap: {sitemap_url}",
            "",
        ]
    )
    return Response(content, mimetype="text/plain")
