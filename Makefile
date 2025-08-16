.PHONY: dev test fmt

dev:
	FLASK_APP=app flask run --debug

test:
	pytest -q

fmt:
	@echo "(placeholder for ruff/black if added)"
