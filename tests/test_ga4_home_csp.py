from app import create_app


def test_home_includes_ga4_and_csp_allows_google():
    app = create_app({"TESTING": True})
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "https://www.googletagmanager.com/gtag/js?id=G-Z3ESSERP7W" in html
    assert "gtag('config', 'G-Z3ESSERP7W'" in html

    csp = response.headers.get("Content-Security-Policy", "")
    assert "https://www.googletagmanager.com" in csp
    assert "https://region1.google-analytics.com" in csp
