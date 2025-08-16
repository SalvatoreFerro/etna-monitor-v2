from app import create_app

def test_routes_respond_200():
    app = create_app()
    client = app.test_client()
    for path in ("/", "/dashboard/", "/admin/"):
        resp = client.get(path)
        assert resp.status_code == 200
