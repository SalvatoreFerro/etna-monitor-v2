web: FLASK_APP=app:create_app flask db upgrade && gunicorn wsgi:app --workers 3 --threads 2 --timeout 120
