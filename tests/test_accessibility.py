"""
Tests for Accessibility using Playwright and axe-core.
Ensures all public pages have zero serious/critical accessibility violations.
"""

import pytest
from playwright.sync_api import sync_playwright
from axe_playwright_python.sync_playwright import Axe
import subprocess
import time
import os
import signal


# Test server configuration
TEST_SERVER_PORT = 5555
TEST_SERVER_HOST = "127.0.0.1"
BASE_URL = f"http://{TEST_SERVER_HOST}:{TEST_SERVER_PORT}"


# List of public pages to test
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


@pytest.fixture(scope="module")
def test_server():
    """Start a test Flask server for Playwright to test against."""
    # Set environment variables for test server
    env = os.environ.copy()
    env.update({
        'FLASK_ENV': 'testing',
        'SECRET_KEY': 'test-secret-key',
        'DISABLE_SCHEDULER': '1',
        'TELEGRAM_BOT_MODE': 'off',
        'PORT': str(TEST_SERVER_PORT),
        'TESTING': '1',
        'ENABLE_SEO_ROUTES': '1',
    })
    
    # Start Flask server in subprocess
    process = subprocess.Popen(
        ['python', '-m', 'flask', 'run', '--host', TEST_SERVER_HOST, '--port', str(TEST_SERVER_PORT)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # Wait for server to be ready
    max_attempts = 30
    for _ in range(max_attempts):
        try:
            import requests
            response = requests.get(f"{BASE_URL}/", timeout=1)
            if response.status_code in [200, 404]:
                break
        except:
            pass
        time.sleep(0.5)
    else:
        process.terminate()
        pytest.fail("Test server failed to start")
    
    yield BASE_URL
    
    # Cleanup: terminate server
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


@pytest.fixture(scope="module")
def browser():
    """Create a Playwright browser instance."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    """Create a new browser page for each test."""
    page = browser.new_page()
    yield page
    page.close()


def _categorize_violations(violations):
    """
    Categorize axe violations by impact level.
    
    Returns:
        dict: {
            'critical': [...],
            'serious': [...],
            'moderate': [...],
            'minor': [...]
        }
    """
    categorized = {
        'critical': [],
        'serious': [],
        'moderate': [],
        'minor': []
    }
    
    for violation in violations:
        impact = violation.get('impact', 'moderate')
        if impact not in categorized:
            impact = 'moderate'
        categorized[impact].append(violation)
    
    return categorized


def _format_violation(violation):
    """Format a violation for readable error messages."""
    impact = violation.get('impact', 'unknown')
    rule_id = violation.get('id', 'unknown')
    description = violation.get('description', 'No description')
    help_text = violation.get('help', 'No help available')
    help_url = violation.get('helpUrl', '')
    
    nodes = violation.get('nodes', [])
    node_count = len(nodes)
    
    message = [
        f"  [{impact.upper()}] {rule_id}",
        f"    Description: {description}",
        f"    Help: {help_text}",
        f"    Affected elements: {node_count}",
    ]
    
    if help_url:
        message.append(f"    More info: {help_url}")
    
    # Show first 2 affected elements
    for i, node in enumerate(nodes[:2]):
        target = node.get('target', ['unknown'])
        html = node.get('html', 'N/A')
        message.append(f"    Element {i+1}: {target}")
        message.append(f"      HTML: {html[:100]}...")
    
    return "\n".join(message)


@pytest.mark.parametrize('page_path', PUBLIC_PAGES)
def test_page_accessibility_no_critical_serious(test_server, browser, page_path):
    """
    Test that public pages have zero critical and serious accessibility violations.
    
    This test uses axe-core to scan pages for WCAG violations.
    Only critical and serious violations cause test failure.
    """
    page = browser.new_page()
    
    try:
        url = f"{test_server}{page_path}"
        
        # Navigate to page
        response = page.goto(url, wait_until="networkidle", timeout=10000)
        
        # Skip if page doesn't exist
        if response.status == 404:
            pytest.skip(f"Page {page_path} not found (404)")
            return
        
        assert response.status == 200, f"Failed to load {page_path}"
        
        # Wait for page to be fully loaded
        page.wait_for_load_state("domcontentloaded")
        
        # Run axe accessibility scan
        axe = Axe()
        results = axe.run(page)
        
        violations = results.get('violations', [])
        
        if not violations:
            # No violations - test passes
            return
        
        # Categorize violations by severity
        categorized = _categorize_violations(violations)
        
        critical = categorized['critical']
        serious = categorized['serious']
        moderate = categorized['moderate']
        minor = categorized['minor']
        
        # Build error message if critical or serious violations exist
        if critical or serious:
            error_parts = [
                f"\n\n{'='*70}",
                f"Accessibility violations found on {page_path}",
                f"{'='*70}\n",
            ]
            
            if critical:
                error_parts.append(f"\nCRITICAL violations ({len(critical)}):")
                for violation in critical:
                    error_parts.append(_format_violation(violation))
            
            if serious:
                error_parts.append(f"\nSERIOUS violations ({len(serious)}):")
                for violation in serious:
                    error_parts.append(_format_violation(violation))
            
            # Note about moderate/minor (but don't fail on them)
            if moderate or minor:
                error_parts.append(
                    f"\n\nNote: This page also has {len(moderate)} moderate "
                    f"and {len(minor)} minor violations (not failing test)."
                )
            
            error_parts.append(
                f"\n\n{'='*70}\n"
                f"Fix critical and serious accessibility issues before merging.\n"
                f"{'='*70}"
            )
            
            pytest.fail("\n".join(error_parts))
        
        # If we only have moderate/minor violations, log them but don't fail
        if moderate or minor:
            print(f"\nNote: {page_path} has {len(moderate)} moderate and {len(minor)} minor A11y issues.")
    
    finally:
        page.close()


def test_axe_installation():
    """Verify that axe-core is properly installed."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Create a simple test page
        page.set_content('<html><body><h1>Test</h1></body></html>')
        
        # Try to run axe
        axe = Axe()
        results = axe.run(page)
        
        assert 'violations' in results, "axe-core should return results with violations key"
        
        page.close()
        browser.close()


def test_accessibility_test_coverage():
    """Verify that we're testing a reasonable number of pages."""
    assert len(PUBLIC_PAGES) >= 5, "Should test at least 5 public pages for accessibility"
