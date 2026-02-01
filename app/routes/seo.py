from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import html
from pathlib import Path
from typing import Tuple

from flask import Blueprint, Response, current_app, request, url_for
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import joinedload

from app.models.blog import BlogPost
from app.models.forum import ForumThread
from app.models.hotspots_record import HotspotsRecord
from app.models.partner import Partner, PartnerCategory, PartnerSubscription
from app.utils.config import get_curva_csv_path
from backend.services.hotspots.config import HotspotsConfig


bp = Blueprint("seo", __name__)

# SEO exclusion patterns shared between sitemap and tests
EXCLUDED_PREFIXES = (
    "/admin",
    "/auth",
)

EXCLUDED_ENDPOINTS = {
    "static",
    "legacy_auth.legacy_login",
    "main.ads_txt",
    "seo.robots_txt",
    "seo.sitemap",
    "seo.sitemap_index",
    "main.ga4_diagnostics",
    "main.ga4_test_csp",
    "main.csp_test",
    "main.csp_echo",
    "main.csp_probe",
    "status.show_csp_header",
    "partners.legacy_experience_redirect",
}

STATIC_PAGES: Tuple[Tuple[str, str, str], ...] = (
    ("main.pricing", "weekly", "0.8"),
    ("main.etna_bot", "weekly", "0.8"),
    ("main.webcam_etna", "weekly", "0.9"),
    ("main.eruzione_oggi", "hourly", "1.0"),
    ("main.faq", "weekly", "0.9"),
    ("main.tecnologia", "weekly", "0.8"),
    ("main.progetto", "yearly", "0.5"),
    ("main.team", "yearly", "0.5"),
    ("main.news", "monthly", "0.7"),
    ("main.etna3d", "weekly", "0.9"),
    ("main.roadmap", "monthly", "0.6"),
    ("main.about", "monthly", "0.9"),
    ("main.sponsor", "monthly", "0.5"),
    ("main.privacy", "yearly", "0.3"),
    ("main.terms", "yearly", "0.3"),
    ("main.cookies", "yearly", "0.3"),
    ("community.community_landing", "weekly", "0.7"),
    ("community.forum_home", "weekly", "0.5"),
    ("partners.direct_guide_listing", "weekly", "0.6"),
    ("partners.direct_hotel_listing", "weekly", "0.6"),
    ("partners.direct_restaurant_listing", "weekly", "0.6"),
)


@bp.route("/seo/health")
def health() -> str:
    return "ok"


def _canonical_base_url() -> str:
    host = current_app.config.get("CANONICAL_HOST") or request.host
    scheme = request.scheme if request.scheme in {"http", "https"} else "https"
    return f"{scheme}://{host}"


def _default_lastmod() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _normalize_external_url(raw_url: str, base_url: str) -> str:
    return raw_url.replace(request.host_url.rstrip("/"), base_url, 1)


def _parse_timestamp(value: str) -> datetime | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    try:
        normalized = normalized.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(normalized, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _homepage_lastmod() -> str:
    csv_path = get_curva_csv_path()
    latest_timestamp: datetime | None = None

    try:
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames and "timestamp" in reader.fieldnames:
                    for row in reader:
                        parsed = _parse_timestamp(row.get("timestamp", ""))
                        if parsed and (latest_timestamp is None or parsed > latest_timestamp):
                            latest_timestamp = parsed
            if latest_timestamp:
                return latest_timestamp.date().isoformat()
            file_mtime = datetime.fromtimestamp(
                csv_path.stat().st_mtime, timezone.utc
            )
            return file_mtime.date().isoformat()
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.warning(
            "[SITEMAP] Failed to read CSV for homepage lastmod: %s", exc
        )

    return _default_lastmod()


def _analysis_lastmod() -> str:
    try:
        latest_record = (
            HotspotsRecord.query.order_by(HotspotsRecord.acq_datetime.desc()).first()
        )
    except Exception as exc:  # pragma: no cover - defensive logging
        current_app.logger.warning("[SITEMAP] Failed to fetch hotspots record: %s", exc)
        return _default_lastmod()

    if not latest_record or not latest_record.acq_datetime:
        return _default_lastmod()
    latest_dt = latest_record.acq_datetime
    if latest_dt.tzinfo is None:
        latest_dt = latest_dt.replace(tzinfo=timezone.utc)
    else:
        latest_dt = latest_dt.astimezone(timezone.utc)
    return latest_dt.date().isoformat()


def _render_static_seo_file(filename: str) -> str | None:
    static_dir = Path(current_app.static_folder or "")
    file_path = static_dir / filename
    if not file_path.exists():
        return None
    content = file_path.read_text(encoding="utf-8")
    base_url = _canonical_base_url()
    return content.replace("{{BASE_URL}}", base_url)


def _append_url(
    urls: list[tuple[str, str, str, str]],
    seen: set[str],
    loc: str,
    lastmod: str,
    changefreq: str,
    priority: str,
) -> None:
    if loc in seen:
        return
    urls.append((loc, lastmod, changefreq, priority))
    seen.add(loc)


@bp.route("/sitemap.xml")
def sitemap() -> Response:
    base_url = _canonical_base_url()
    urls: list[tuple[str, str, str, str]] = []
    seen_urls: set[str] = set()
    today = date.today()
    valid_subscription_clause = and_(
        PartnerSubscription.status == "paid",
        PartnerSubscription.valid_to.isnot(None),
        PartnerSubscription.valid_to >= today,
        or_(
            PartnerSubscription.valid_from.is_(None),
            PartnerSubscription.valid_from <= today,
        ),
    )

    # Homepage
    _append_url(
        urls,
        seen_urls,
        f"{base_url}/",
        _homepage_lastmod(),
        "hourly",
        "1.0",
    )

    # Static marketing/utility pages
    static_lastmod = (
        current_app.config.get("STATIC_CONTENT_LASTMOD") or "2024-01-01"
    )
    for endpoint, changefreq, priority in STATIC_PAGES:
        if endpoint in EXCLUDED_ENDPOINTS:
            continue
        try:
            absolute = _normalize_external_url(url_for(endpoint, _external=True), base_url)
        except Exception:
            continue
        lastmod = _default_lastmod() if endpoint == "main.about" else static_lastmod
        _append_url(urls, seen_urls, absolute, lastmod, changefreq, priority)

    analysis_pages = []
    hotspots_config = HotspotsConfig.from_env()
    if hotspots_config.enabled:
        analysis_pages.append(("main.hotspots", _analysis_lastmod(), "hourly", "0.8"))
    analysis_pages.append(("main.observatory", _homepage_lastmod(), "hourly", "0.9"))
    for endpoint, lastmod, changefreq, priority in analysis_pages:
        try:
            absolute = _normalize_external_url(url_for(endpoint, _external=True), base_url)
        except Exception:
            continue
        _append_url(urls, seen_urls, absolute, lastmod, changefreq, priority)

    # Blog index and articles
    blog_posts: list[BlogPost] = []
    try:
        now = datetime.now(timezone.utc)
        blog_posts = (
            BlogPost.query.filter(
                BlogPost.published.is_(True),
                or_(BlogPost.published_at.is_(None), BlogPost.published_at <= now),
            )
            .order_by(BlogPost.updated_at.desc(), BlogPost.created_at.desc())
            .all()
        )
    except Exception as exc:  # pragma: no cover - defensive log
        current_app.logger.warning("[SITEMAP] Failed to fetch blog posts: %s", exc)

    for post in blog_posts:
        try:
            absolute = _normalize_external_url(
                url_for("community.blog_detail", slug=post.slug, _external=True),
                base_url,
            )
        except Exception:
            continue
        lastmod = (post.updated_at or post.created_at or datetime.now(timezone.utc)).date().isoformat()
        _append_url(urls, seen_urls, absolute, lastmod, "weekly", "0.7")

    try:
        blog_index_url = _normalize_external_url(
            url_for("community.blog_index", _external=True), base_url
        )
        latest_post_dt = max(
            (post.updated_at or post.created_at for post in blog_posts),
            default=None,
        )
        lastmod = (
            (latest_post_dt or datetime.now(timezone.utc)).date().isoformat()
            if latest_post_dt
            else _default_lastmod()
        )
        _append_url(urls, seen_urls, blog_index_url, lastmod, "daily", "0.8")
    except Exception:
        pass

    # Partner categories
    try:
        categories = (
            PartnerCategory.query.filter_by(is_active=True)
            .order_by(PartnerCategory.sort_order.asc())
            .all()
        )
    except Exception as exc:  # pragma: no cover - log db failures
        current_app.logger.warning("[SITEMAP] Failed to fetch categories: %s", exc)
        categories = []

    for category in categories:
        try:
            absolute = _normalize_external_url(
                url_for("category.category_view", slug=category.slug, _external=True),
                base_url,
            )
        except Exception:
            continue

        last_partner = (
            Partner.query.filter(
                Partner.category_id == category.id,
                Partner.status == "approved",
                Partner.subscriptions.any(valid_subscription_clause),
            )
            .order_by(Partner.updated_at.desc(), Partner.id.desc())
            .first()
        )
        if last_partner and (last_partner.updated_at or last_partner.created_at):
            lastmod_dt = last_partner.updated_at or last_partner.created_at
            lastmod = lastmod_dt.date().isoformat()
        else:
            fallback = category.updated_at or datetime.now(timezone.utc)
            lastmod = fallback.date().isoformat()
        _append_url(urls, seen_urls, absolute, lastmod, "daily", "0.9")

    # Partner detail pages
    try:
        partners = (
            Partner.query.options(
                joinedload(Partner.category), joinedload(Partner.subscriptions)
            )
            .filter(
                Partner.status == "approved",
                Partner.subscriptions.any(valid_subscription_clause),
            )
            .order_by(Partner.updated_at.desc(), Partner.id.asc())
            .all()
        )
    except Exception as exc:  # pragma: no cover - log
        current_app.logger.warning("[SITEMAP] Failed to fetch partners: %s", exc)
        partners = []

    for partner in partners:
        if not partner.category or not partner.category.is_active:
            continue
        try:
            absolute = _normalize_external_url(
                url_for(
                    "partners.partner_detail",
                    slug=partner.category.slug,
                    partner_slug=partner.slug,
                    _external=True,
                ),
                base_url,
            )
        except Exception:
            continue
        timestamp = partner.updated_at or partner.created_at or datetime.now(timezone.utc)
        _append_url(
            urls,
            seen_urls,
            absolute,
            timestamp.date().isoformat(),
            "monthly",
            "0.7",
        )

    # Forum threads (optional but useful for Q&A content freshness)
    try:
        threads = (
            ForumThread.query.filter(ForumThread.status != "archived")
            .order_by(ForumThread.updated_at.desc())
            .all()
        )
    except Exception as exc:  # pragma: no cover - log only
        current_app.logger.warning("[SITEMAP] Failed to fetch forum threads: %s", exc)
        threads = []

    for thread in threads:
        try:
            absolute = _normalize_external_url(
                url_for("community.thread_detail", slug=thread.slug, _external=True),
                base_url,
            )
        except Exception:
            continue
        timestamp = thread.updated_at or thread.created_at or datetime.now(timezone.utc)
        _append_url(
            urls,
            seen_urls,
            absolute,
            timestamp.date().isoformat(),
            "weekly",
            "0.5",
        )

    # Sort URLs alphabetically for consistency
    urls.sort(key=lambda item: item[0])

    xml = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">",
    ]
    for loc, lastmod, changefreq, priority in urls:
        xml.extend(
            [
                "  <url>",
                f"    <loc>{loc}</loc>",
                f"    <lastmod>{lastmod}</lastmod>",
                f"    <changefreq>{changefreq}</changefreq>",
                f"    <priority>{priority}</priority>",
                "  </url>",
            ]
        )
    xml.append("</urlset>")
    payload = "\n".join(xml)
    return Response(payload, mimetype="application/xml")


@bp.route("/sitemap_index.xml")
def sitemap_index() -> Response:
    static_payload = _render_static_seo_file("sitemap_index.xml")
    if static_payload:
        return Response(static_payload, mimetype="application/xml")

    base_url = _canonical_base_url()
    xml = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        "<sitemapindex xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">",
        "  <sitemap>",
        f"    <loc>{base_url}/sitemap.xml</loc>",
        "  </sitemap>",
        "  <sitemap>",
        f"    <loc>{base_url}/news-sitemap.xml</loc>",
        "  </sitemap>",
        "</sitemapindex>",
    ]
    payload = "\n".join(xml)
    return Response(payload, mimetype="application/xml")


@bp.route("/news-sitemap.xml")
def news_sitemap() -> Response:
    base_url = _canonical_base_url()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=48)
    posts: list[BlogPost] = []

    try:
        posts = (
            BlogPost.query.filter(
                BlogPost.published.is_(True),
                or_(BlogPost.published_at.is_(None), BlogPost.published_at <= now),
                func.coalesce(BlogPost.published_at, BlogPost.created_at) >= cutoff,
            )
            .order_by(func.coalesce(BlogPost.published_at, BlogPost.created_at).desc())
            .limit(200)
            .all()
        )
    except Exception as exc:  # pragma: no cover - defensive log
        current_app.logger.warning("[NEWS SITEMAP] Failed to fetch posts: %s", exc)

    xml = [
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>",
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\"",
        "  xmlns:news=\"http://www.google.com/schemas/sitemap-news/0.9\">",
    ]

    for post in posts:
        published_ts = post.published_at or post.created_at
        if published_ts is None:
            continue
        if published_ts.tzinfo is None:
            published_ts = published_ts.replace(tzinfo=timezone.utc)
        else:
            published_ts = published_ts.astimezone(timezone.utc)
        loc = _normalize_external_url(
            url_for("community.blog_detail", slug=post.slug, _external=True),
            base_url,
        )
        xml.extend(
            [
                "  <url>",
                f"    <loc>{loc}</loc>",
                "    <news:news>",
                "      <news:publication>",
                "        <news:name>EtnaMonitor</news:name>",
                "        <news:language>it</news:language>",
                "      </news:publication>",
                f"      <news:publication_date>{published_ts.isoformat()}</news:publication_date>",
                f"      <news:title>{html.escape(post.title)}</news:title>",
                "    </news:news>",
                "  </url>",
            ]
        )

    xml.append("</urlset>")
    payload = "\n".join(xml)
    return Response(payload, mimetype="application/xml")


@bp.route("/robots.txt")
def robots_txt() -> Response:
    static_payload = _render_static_seo_file("robots.txt")
    if static_payload:
        return Response(static_payload, mimetype="text/plain")

    base_url = _canonical_base_url()
    sitemap_index_url = f"{base_url}/sitemap_index.xml"
    news_sitemap_url = f"{base_url}/news-sitemap.xml"
    
    # Build content dynamically using shared exclusion constants
    content_lines = ["User-agent: *", "Allow: /"]
    
    # Add Disallow directives from shared constants
    for prefix in EXCLUDED_PREFIXES:
        content_lines.append(f"Disallow: {prefix}")
    
    content_lines.extend([f"Sitemap: {sitemap_index_url}", f"Sitemap: {news_sitemap_url}", ""])
    
    content = "\n".join(content_lines)
    return Response(content, mimetype="text/plain")
