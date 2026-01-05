"""SEO-related tests for blog articles and news sitemap."""

from datetime import datetime, timezone

import pytest

from app import create_app
from app.models import db
from app.models.blog import BlogPost


@pytest.fixture()
def app():
    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test-key",
        }
    )
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def _create_post():
    post = BlogPost(
        title="Aggiornamento Etna",
        summary="Sintesi del monitoraggio.",
        content="Contenuto dell'articolo con abbastanza parole per la lettura.",
        published=True,
        published_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        hero_image_url="https://example.com/hero.jpg",
    )
    db.session.add(post)
    db.session.commit()
    return {"slug": post.slug, "title": post.title}


def test_blog_detail_includes_seo_and_byline(client, app):
    with app.app_context():
        post_data = _create_post()

    response = client.get(f"/community/blog/{post_data['slug']}/")
    content = response.data.decode("utf-8")

    assert response.status_code == 200
    assert f"<h1 class=\"post__title\" itemprop=\"headline\">{post_data['title']}</h1>" in content
    assert "Pubblicato" in content
    assert "Salvatore Ferro" in content
    assert "\"@type\": \"NewsArticle\"" in content
    assert "property=\"og:title\"" in content
    assert "property=\"og:description\"" in content
    assert "name=\"twitter:card\"" in content
    assert "rel=\"canonical\"" in content


def test_news_sitemap_includes_recent_posts(client, app):
    with app.app_context():
        post_data = _create_post()

    response = client.get("/news-sitemap.xml")
    content = response.data.decode("utf-8")

    assert response.status_code == 200
    assert "<news:publication>" in content
    assert post_data["title"] in content
