"""Test navbar fixes: removal of 'Guida rapida' button and Dashboard duplication."""
import pytest
from app import create_app


@pytest.fixture
def app():
    """Create test app instance."""
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-secret',
        'DATABASE_URL': 'sqlite:///:memory:',
        'DISABLE_SCHEDULER': True,
        'GA_ENABLE': 'false',
    })
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


def test_guida_rapida_button_removed(client):
    """Test that 'Guida rapida' button is not present in the navbar."""
    # Test as logged out user
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    
    # The button with the trigger attribute should not be present in navbar
    assert 'data-onboarding-trigger' not in html
    # The specific button element in the navbar actions should not exist
    assert '<button type="button" class="btn btn-ghost btn-sm" data-onboarding-trigger>' not in html


def test_dashboard_not_duplicated_when_logged_out(client):
    """Test that Dashboard link doesn't appear when logged out."""
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    
    # Dashboard should not be visible when not logged in
    # Check that there's no Dashboard button visible in the navbar
    assert 'href="/dashboard/"' not in html or html.count('href="/dashboard/"') == 0


def test_dashboard_mobile_only_class_present(client, app):
    """Test that Dashboard link in mobile menu has mobile-only class when logged in."""
    # We verify the template structure by checking the navbar HTML directly
    # The mobile Dashboard link should have the mobile-only class
    
    # Read the navbar template to verify structure
    import os
    navbar_path = os.path.join(app.root_path, 'templates', 'partials', 'navbar.html')
    with open(navbar_path, 'r') as f:
        navbar_content = f.read()
    
    # Verify that when user is logged in, Dashboard link has mobile-only class
    assert "'label': 'Dashboard'" in navbar_content
    assert "'extra_class': 'site-nav__link--mobile-only'" in navbar_content
    
    # Verify that the quick guide button is not in the template
    assert 'data-onboarding-trigger' not in navbar_content


def test_navbar_structure_valid(client):
    """Test that the navbar HTML structure is valid after changes."""
    response = client.get('/')
    assert response.status_code == 200
    html = response.data.decode('utf-8')
    
    # Check that site-nav__actions div exists
    assert 'site-nav__actions' in html
    
    # Check that the navbar has proper structure
    assert 'site-nav__menu' in html
    assert 'site-nav__links' in html
