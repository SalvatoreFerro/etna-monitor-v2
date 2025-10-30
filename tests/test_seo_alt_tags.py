"""
Tests for SEO: Image alt attributes.
Ensures all <img> tags in public pages have non-empty alt attributes.
Excludes: SVG, favicons, sprites, tracking pixels (1x1), and aria-hidden images.
"""

import pytest
import re
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


def _is_excluded_image(img_tag):
    """
    Check if an image should be excluded from alt attribute requirement.
    
    Excluded images:
    - SVG images (src ends with .svg)
    - Favicons (src contains 'favicon' or 'icon')
    - Sprites (src contains 'sprite')
    - Tracking pixels (width=1 and height=1)
    - aria-hidden images
    - Images with role="presentation"
    """
    src = img_tag.get('src', '')
    
    # Check if it's SVG
    if src.endswith('.svg'):
        return True
    
    # Check if it's a favicon or icon
    if 'favicon' in src.lower() or '/icon' in src.lower() or 'icons/' in src.lower():
        return True
    
    # Check if it's a sprite
    if 'sprite' in src.lower():
        return True
    
    # Check if it's a tracking pixel (1x1)
    width = img_tag.get('width', '')
    height = img_tag.get('height', '')
    if width == '1' and height == '1':
        return True
    
    # Check if it's aria-hidden
    if img_tag.get('aria-hidden') == 'true':
        return True
    
    # Check if it has role="presentation"
    if img_tag.get('role') == 'presentation':
        return True
    
    return False


def _check_alt_attributes(html_content, page_url):
    """
    Check all img tags in HTML content for alt attributes.
    
    Returns:
        tuple: (is_valid, missing_images) where missing_images is a list of problematic img tags
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    img_tags = soup.find_all('img')
    
    missing_alt = []
    
    for img in img_tags:
        # Skip excluded images
        if _is_excluded_image(img):
            continue
        
        # Check if alt attribute exists and is not empty
        alt = img.get('alt', None)
        if alt is None or (isinstance(alt, str) and alt.strip() == ''):
            missing_alt.append({
                'tag': str(img)[:100],  # Truncate for readability
                'src': img.get('src', 'no-src'),
            })
    
    return len(missing_alt) == 0, missing_alt


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


@pytest.mark.parametrize('page_url', PUBLIC_PAGES)
def test_public_page_images_have_alt_attributes(client, page_url):
    """Test that all images on public pages have alt attributes."""
    response = client.get(page_url)
    
    # Skip if page doesn't exist (404)
    if response.status_code == 404:
        pytest.skip(f"Page {page_url} not found (404)")
        return
    
    assert response.status_code == 200, f"Failed to load {page_url}"
    
    html_content = response.get_data(as_text=True)
    is_valid, missing_images = _check_alt_attributes(html_content, page_url)
    
    if not is_valid:
        error_msg = f"\n\n{page_url} has images without alt attributes:\n"
        for img in missing_images:
            error_msg += f"  - src: {img['src']}\n    tag: {img['tag']}\n"
        error_msg += "\nAll non-decorative images must have descriptive alt attributes."
        error_msg += "\nDecorative images should use alt='' with aria-hidden='true'."
        pytest.fail(error_msg)


def test_homepage_has_images(client):
    """Sanity check: ensure homepage actually has images to test."""
    response = client.get('/')
    assert response.status_code == 200
    
    html_content = response.get_data(as_text=True)
    soup = BeautifulSoup(html_content, 'html.parser')
    img_tags = soup.find_all('img')
    
    # Filter out excluded images
    non_excluded = [img for img in img_tags if not _is_excluded_image(img)]
    
    # We expect at least some images on the homepage
    assert len(img_tags) > 0, "Homepage should have at least one image tag"


def test_alt_exclusions_work():
    """Test that exclusion logic works correctly."""
    # Test SVG exclusion
    soup = BeautifulSoup('<img src="logo.svg">', 'html.parser')
    assert _is_excluded_image(soup.find('img')) is True
    
    # Test favicon exclusion
    soup = BeautifulSoup('<img src="/static/icons/favicon.png">', 'html.parser')
    assert _is_excluded_image(soup.find('img')) is True
    
    # Test tracking pixel exclusion
    soup = BeautifulSoup('<img src="pixel.gif" width="1" height="1">', 'html.parser')
    assert _is_excluded_image(soup.find('img')) is True
    
    # Test aria-hidden exclusion
    soup = BeautifulSoup('<img src="image.jpg" aria-hidden="true">', 'html.parser')
    assert _is_excluded_image(soup.find('img')) is True
    
    # Test normal image (should NOT be excluded)
    soup = BeautifulSoup('<img src="photo.jpg">', 'html.parser')
    assert _is_excluded_image(soup.find('img')) is False
