"""
Tests for SEO: Duplicate titles and meta descriptions.
Ensures no two public pages have the same <title> or meta description.
"""

import pytest
from bs4 import BeautifulSoup
from sqlalchemy.pool import StaticPool

from app import create_app
from app.models import db


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Create and configure a test Flask application."""
    monkeypatch.setenv("SKIP_CURVA_BOOTSTRAP", "1")
    data_dir = tmp_path / "data"
    csv_path = data_dir / "curva.csv"
    config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "SQLALCHEMY_ENGINE_OPTIONS": {
            "connect_args": {"check_same_thread": False},
            "poolclass": StaticPool,
        },
        "DATA_DIR": str(data_dir),
        "CSV_PATH": str(csv_path),
        "SECRET_KEY": "test-secret",
        "TELEGRAM_BOT_MODE": "off",
        "DISABLE_SCHEDULER": True,
        "ENABLE_SEO_ROUTES": True,
    }
    app = create_app(config)
    with app.app_context():
        db.create_all()
        # Create test CSV
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text("timestamp,value\n2024-01-01 00:00:00,50\n2024-01-01 01:00:00,55\n")
        yield app
        db.drop_all()


@pytest.fixture
def client(app):
    """Create a test client for the app."""
    return app.test_client()


def _extract_title(html_content):
    """Extract the <title> tag content from HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    title_tag = soup.find('title')
    if title_tag:
        return title_tag.get_text().strip()
    return None


def _extract_meta_description(html_content):
    """Extract the meta description content from HTML."""
    soup = BeautifulSoup(html_content, 'html.parser')
    meta_tag = soup.find('meta', attrs={'name': 'description'})
    if meta_tag:
        return meta_tag.get('content', '').strip()
    return None


# List of public pages to test (exclude /admin, /dashboard, /auth)
PUBLIC_PAGES = [
    '/',
    '/pricing',
    '/etna3d',
    '/experience',
    '/become-partner',
    '/roadmap',
    '/sponsor',
    '/cookies',
    '/privacy',
    '/terms',
]


def test_no_duplicate_titles_across_pages(client):
    """Test that no two public pages have the same <title>."""
    titles = {}
    
    for page_url in PUBLIC_PAGES:
        response = client.get(page_url)
        
        # Skip if page doesn't exist
        if response.status_code == 404:
            continue
        
        assert response.status_code == 200, f"Failed to load {page_url}"
        
        html_content = response.get_data(as_text=True)
        title = _extract_title(html_content)
        
        if title:
            if title in titles:
                pytest.fail(
                    f"\n\nDuplicate title found:\n"
                    f"  Title: '{title}'\n"
                    f"  Pages: {titles[title]} and {page_url}\n\n"
                    f"Each page must have a unique <title> tag for SEO."
                )
            titles[title] = page_url


def test_no_duplicate_meta_descriptions_across_pages(client):
    """Test that no two public pages have the same meta description."""
    descriptions = {}
    
    for page_url in PUBLIC_PAGES:
        response = client.get(page_url)
        
        # Skip if page doesn't exist
        if response.status_code == 404:
            continue
        
        assert response.status_code == 200, f"Failed to load {page_url}"
        
        html_content = response.get_data(as_text=True)
        description = _extract_meta_description(html_content)
        
        # Skip pages without meta descriptions (will be caught by another test)
        if not description:
            continue
        
        if description in descriptions:
            pytest.fail(
                f"\n\nDuplicate meta description found:\n"
                f"  Description: '{description[:100]}...'\n"
                f"  Pages: {descriptions[description]} and {page_url}\n\n"
                f"Each page must have a unique meta description for SEO."
            )
        descriptions[description] = page_url


def test_all_public_pages_have_titles(client):
    """Test that all public pages have a <title> tag."""
    missing_titles = []
    
    for page_url in PUBLIC_PAGES:
        response = client.get(page_url)
        
        # Skip if page doesn't exist
        if response.status_code == 404:
            continue
        
        assert response.status_code == 200, f"Failed to load {page_url}"
        
        html_content = response.get_data(as_text=True)
        title = _extract_title(html_content)
        
        if not title:
            missing_titles.append(page_url)
    
    if missing_titles:
        pytest.fail(
            f"\n\nPages without <title> tags:\n"
            + "\n".join(f"  - {url}" for url in missing_titles)
            + "\n\nAll public pages must have a <title> tag."
        )


def test_all_public_pages_have_meta_descriptions(client):
    """Test that all public pages have a meta description."""
    missing_descriptions = []
    
    for page_url in PUBLIC_PAGES:
        response = client.get(page_url)
        
        # Skip if page doesn't exist
        if response.status_code == 404:
            continue
        
        assert response.status_code == 200, f"Failed to load {page_url}"
        
        html_content = response.get_data(as_text=True)
        description = _extract_meta_description(html_content)
        
        if not description:
            missing_descriptions.append(page_url)
    
    if missing_descriptions:
        pytest.fail(
            f"\n\nPages without meta description:\n"
            + "\n".join(f"  - {url}" for url in missing_descriptions)
            + "\n\nAll public pages must have a <meta name='description'> tag."
        )


def test_title_length_recommendations(client):
    """Test that titles are within recommended length (50-60 characters optimal)."""
    too_long = []
    too_short = []
    
    for page_url in PUBLIC_PAGES:
        response = client.get(page_url)
        
        # Skip if page doesn't exist
        if response.status_code == 404:
            continue
        
        assert response.status_code == 200, f"Failed to load {page_url}"
        
        html_content = response.get_data(as_text=True)
        title = _extract_title(html_content)
        
        if title:
            length = len(title)
            if length > 70:
                too_long.append((page_url, title, length))
            elif length < 30:
                too_short.append((page_url, title, length))
    
    warnings = []
    if too_long:
        warnings.append("\nTitles longer than 70 characters (may be truncated in search results):")
        for url, title, length in too_long:
            warnings.append(f"  - {url} ({length} chars): '{title}'")
    
    if too_short:
        warnings.append("\nTitles shorter than 30 characters (may not be descriptive enough):")
        for url, title, length in too_short:
            warnings.append(f"  - {url} ({length} chars): '{title}'")
    
    # This is a warning, not a failure - log to test output
    if warnings:
        print("\n".join(warnings))


def test_meta_description_length_recommendations(client):
    """Test that meta descriptions are within recommended length (150-160 chars optimal)."""
    too_long = []
    too_short = []
    
    for page_url in PUBLIC_PAGES:
        response = client.get(page_url)
        
        # Skip if page doesn't exist
        if response.status_code == 404:
            continue
        
        assert response.status_code == 200, f"Failed to load {page_url}"
        
        html_content = response.get_data(as_text=True)
        description = _extract_meta_description(html_content)
        
        if description:
            length = len(description)
            if length > 170:
                too_long.append((page_url, description, length))
            elif length < 120:
                too_short.append((page_url, description, length))
    
    warnings = []
    if too_long:
        warnings.append("\nMeta descriptions longer than 170 characters (may be truncated):")
        for url, desc, length in too_long:
            warnings.append(f"  - {url} ({length} chars): '{desc[:60]}...'")
    
    if too_short:
        warnings.append("\nMeta descriptions shorter than 120 characters (could be more descriptive):")
        for url, desc, length in too_short:
            warnings.append(f"  - {url} ({length} chars): '{desc}'")
    
    # This is a warning, not a failure - log to test output
    if warnings:
        print("\n".join(warnings))
