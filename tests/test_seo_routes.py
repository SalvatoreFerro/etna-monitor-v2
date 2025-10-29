"""Tests for SEO routes (robots.txt and sitemap.xml)"""
import re
import pytest
from app import create_app


@pytest.fixture
def client():
    """Create test client"""
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'SECRET_KEY': 'test-key'
    })
    with app.test_client() as client:
        yield client


def test_robots_txt_exists(client):
    """Test that /robots.txt route exists and returns 200"""
    response = client.get('/robots.txt')
    assert response.status_code == 200
    assert response.content_type == 'text/plain; charset=utf-8'


def test_robots_txt_content(client):
    """Test that robots.txt contains correct directives"""
    response = client.get('/robots.txt')
    content = response.data.decode('utf-8')
    
    # Check required directives
    assert 'User-agent: *' in content
    assert 'Allow: /' in content
    assert 'Disallow: /admin' in content
    assert 'Disallow: /dashboard' in content
    assert 'Disallow: /auth' in content
    assert 'Disallow: /api' in content
    assert 'Disallow: /internal' in content
    assert 'Sitemap:' in content
    assert '/sitemap.xml' in content


def test_sitemap_xml_exists(client):
    """Test that /sitemap.xml route exists and returns 200"""
    response = client.get('/sitemap.xml')
    assert response.status_code == 200
    assert response.content_type == 'application/xml; charset=utf-8'


def test_sitemap_xml_structure(client):
    """Test that sitemap.xml has valid XML structure"""
    response = client.get('/sitemap.xml')
    content = response.data.decode('utf-8')
    
    # Check XML declaration and urlset
    assert '<?xml version="1.0" encoding="UTF-8"?>' in content
    assert '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' in content
    assert '</urlset>' in content


def test_sitemap_includes_public_routes(client):
    """Test that sitemap includes expected public routes"""
    response = client.get('/sitemap.xml')
    content = response.data.decode('utf-8')
    
    # Expected public routes
    expected_routes = [
        '/',
        '/pricing',
        '/etna-3d',
        '/experience',
        '/become-partner',
        '/roadmap',
        '/sponsor',
        '/cookies',
        '/privacy',
        '/terms',
    ]
    
    for route in expected_routes:
        assert route in content, f"Expected route {route} not found in sitemap"


def test_sitemap_excludes_private_routes(client):
    """Test that sitemap excludes admin, dashboard, auth, api, and internal routes"""
    response = client.get('/sitemap.xml')
    content = response.data.decode('utf-8')
    
    # Extract all URLs from sitemap
    urls = re.findall(r'<loc>(.*?)</loc>', content)
    
    # Check that no excluded paths are in the sitemap
    excluded_patterns = ['/admin', '/dashboard', '/auth', '/api', '/internal', 
                        '/billing', '/livez', '/readyz', '/healthz', '/seo']
    
    for url in urls:
        for pattern in excluded_patterns:
            assert pattern not in url.lower(), f"Excluded pattern {pattern} found in URL: {url}"


def test_sitemap_url_elements(client):
    """Test that each URL in sitemap has loc, lastmod, and changefreq"""
    response = client.get('/sitemap.xml')
    content = response.data.decode('utf-8')
    
    # Extract all URL blocks
    url_blocks = re.findall(r'<url>(.*?)</url>', content, re.DOTALL)
    
    assert len(url_blocks) > 0, "No URLs found in sitemap"
    
    for block in url_blocks:
        assert '<loc>' in block and '</loc>' in block, "Missing <loc> element"
        assert '<lastmod>' in block and '</lastmod>' in block, "Missing <lastmod> element"
        assert '<changefreq>' in block and '</changefreq>' in block, "Missing <changefreq> element"


def test_sitemap_excludes_itself(client):
    """Test that sitemap.xml and robots.txt don't include themselves"""
    response = client.get('/sitemap.xml')
    content = response.data.decode('utf-8')
    
    # Extract all URLs from sitemap
    urls = re.findall(r'<loc>(.*?)</loc>', content)
    
    # Check that sitemap and robots don't reference themselves
    for url in urls:
        assert not url.endswith('/sitemap.xml'), "Sitemap should not include itself"
        assert not url.endswith('/robots.txt'), "Sitemap should not include robots.txt"


def test_sitemap_no_duplicate_urls(client):
    """Test that sitemap doesn't contain duplicate URLs"""
    response = client.get('/sitemap.xml')
    content = response.data.decode('utf-8')
    
    # Extract all URLs
    urls = re.findall(r'<loc>(.*?)</loc>', content)
    
    # Check for duplicates
    assert len(urls) == len(set(urls)), "Sitemap contains duplicate URLs"
