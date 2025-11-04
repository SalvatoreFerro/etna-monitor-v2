"""Utility script to remove legacy <br> tags from stored blog posts."""

from __future__ import annotations

from app import create_app
from app.filters import strip_literal_breaks
from app.models import BlogPost, db


def main() -> None:
    app = create_app()
    with app.app_context():
        updated = 0
        for post in BlogPost.query.all():
            original_content = post.content or ""
            cleaned_content = strip_literal_breaks(original_content).strip()
            if cleaned_content != original_content:
                post.content = cleaned_content
                updated += 1

        if updated:
            db.session.commit()

        print(f"Sanitized {updated} blog posts.")


if __name__ == "__main__":
    main()

