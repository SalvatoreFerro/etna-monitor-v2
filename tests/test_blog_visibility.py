"""Blog visibility, slug, and list behavior tests."""

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


def _create_post(title: str, published: bool, published_at=None) -> dict[str, str]:
    post = BlogPost(
        title=title,
        summary="Sintesi articolo.",
        content="Testo dell'articolo con un numero di parole sufficiente per il rendering.",
        published=published,
        published_at=published_at,
        updated_at=datetime.now(timezone.utc),
    )
    db.session.add(post)
    db.session.commit()
    return {"slug": post.slug, "title": post.title}


def test_published_post_visible_in_list_and_detail(client, app):
    with app.app_context():
        post = _create_post(
            title="Aggiornamento Etna",
            published=True,
            published_at=datetime.now(timezone.utc),
        )

    list_response = client.get("/community/blog/")
    detail_response = client.get(f"/community/blog/{post['slug']}/")

    assert list_response.status_code == 200
    assert post["title"] in list_response.data.decode("utf-8")
    assert detail_response.status_code == 200


def test_draft_post_hidden_from_list_and_detail(client, app):
    with app.app_context():
        post = _create_post(
            title="Bozza Etna",
            published=False,
            published_at=datetime.now(timezone.utc),
        )

    list_response = client.get("/community/blog/")
    detail_response = client.get(f"/community/blog/{post['slug']}/")

    assert list_response.status_code == 200
    assert post["title"] not in list_response.data.decode("utf-8")
    assert detail_response.status_code == 404


def test_special_character_slug_is_stable(client, app):
    title = "L'Etna è vivo: perché oggi?"
    with app.app_context():
        post = _create_post(
            title=title,
            published=True,
            published_at=datetime.now(timezone.utc),
        )

    assert post["slug"] == BlogPost.build_slug(title)

    list_response = client.get("/community/blog/")
    detail_response = client.get(f"/community/blog/{post['slug']}/")

    assert list_response.status_code == 200
    assert f"/community/blog/{post['slug']}/" in list_response.data.decode("utf-8")
    assert detail_response.status_code == 200
