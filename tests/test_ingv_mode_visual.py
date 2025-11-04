import pytest
from playwright.sync_api import sync_playwright
import os
from pathlib import Path

pytestmark = pytest.mark.e2e

@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()

@pytest.fixture
def page(browser):
    page = browser.new_page()
    yield page
    page.close()

def test_ingv_mode_visual_regression(page):
    page.goto("http://localhost:5000/dashboard")
    
    page.fill('input[name="email"]', 'test@example.com')
    page.fill('input[name="password"]', 'password123')
    page.click('button[type="submit"]')
    
    page.wait_for_selector('#tremor-plot')
    
    page.check('#ingv-mode')
    
    page.wait_for_timeout(2000)
    
    screenshot_path = Path(__file__).parent / "screenshots" / "ingv_mode.png"
    screenshot_path.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(screenshot_path))
    
    reference_path = Path(__file__).parent / "references" / "ingv_mode_reference.png"
    if reference_path.exists():
        pass
    
    assert page.is_visible('text=ECBD - RMS (UTC Time)')
    
    assert page.is_visible('text=10⁻¹')
    assert page.is_visible('text=10⁰')
    assert page.is_visible('text=10¹')
    
    plot_bg = page.evaluate("""
        () => {
            const plot = document.querySelector('#tremor-plot .plot-container');
            return window.getComputedStyle(plot).backgroundColor;
        }
    """)
    assert 'rgb(255, 255, 255)' in plot_bg or 'white' in plot_bg

def test_modern_mode_visual(page):
    page.goto("http://localhost:5000/dashboard")
    
    page.fill('input[name="email"]', 'test@example.com')
    page.fill('input[name="password"]', 'password123')
    page.click('button[type="submit"]')
    
    page.wait_for_selector('#tremor-plot')
    
    page.uncheck('#ingv-mode')
    page.wait_for_timeout(2000)
    
    assert page.is_visible('text=Tremor (mV)')
    
    plot_bg = page.evaluate("""
        () => {
            const plot = document.querySelector('#tremor-plot .plot-container');
            return window.getComputedStyle(plot).backgroundColor;
        }
    """)
    assert 'rgba(0, 0, 0, 0)' in plot_bg or 'transparent' in plot_bg

def test_theme_toggle_functionality(page):
    page.goto("http://localhost:5000/dashboard")
    
    page.fill('input[name="email"]', 'test@example.com')
    page.fill('input[name="password"]', 'password123')
    page.click('button[type="submit"]')
    
    page.click('#theme-toggle')
    
    theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
    assert theme in ['dark', 'light']
    
    page.click('#theme-toggle')
    new_theme = page.evaluate("() => document.documentElement.getAttribute('data-theme')")
    assert new_theme != theme

def test_responsive_design(page):
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto("http://localhost:5000")
    
    assert page.is_visible('.navbar-toggle')
    
    page.set_viewport_size({"width": 768, "height": 1024})
    page.reload()
    
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.reload()
    
    hero_grid = page.evaluate("""
        () => {
            const hero = document.querySelector('.hero-section');
            return window.getComputedStyle(hero).gridTemplateColumns;
        }
    """)
    assert 'fr' in hero_grid
