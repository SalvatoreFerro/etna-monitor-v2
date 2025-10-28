# QA Report

## Screenshots
- ![Home iPhone 14 Pro](browser:/invocations/onckizaz/artifacts/artifacts/home-iphone14pro.png)
- ![Home iPad](browser:/invocations/onckizaz/artifacts/artifacts/home-ipad.png)
- ![Home Desktop](browser:/invocations/onckizaz/artifacts/artifacts/home-desktop.png)

## Console & Network Observations
- Browser console still reports CSP blocks for external Google Ads scripts and inline snippets (expected per CSP). No JavaScript runtime errors observed.
- API bootstrap attempts to download INGV PNG assets fail behind proxy (HTTP 403), logged during Flask startup and `/api/curva` requests.
- `/api/curva` responds `200 OK` with empty dataset when upstream download fails. Sample response captured via curl below.

```
HTTP/1.1 200 OK
Content-Type: application/json
Content-Length: 46

{"data":[],"last_ts":null,"ok":true,"rows":0}
```

## Lighthouse
- `npx` based Lighthouse run blocked (HTTP 403 when downloading package). Unable to collect new report in container environment.

## Test Execution
- `SECRET_KEY=devkey pytest`
  - 54 tests passed, 11 failed, 4 errors. Failures caused by missing migrations/alembic.ini, external network blocks (Telegram/INGV), Playwright browser binaries absent, and legacy schema constraints.
- Initial `pytest` run without `SECRET_KEY` aborts during collection.

## Known Environment Warnings
- Database migrations fallback to schema guard because `migrations/alembic.ini` missing.
- Partner table creation fails due to `SERIAL` type in SQLite, logged at startup.
- External INGV PNG fetch and Telegram API calls blocked by proxy (HTTP 403).
- Playwright Chromium binary unavailable in sandbox, causing responsive visual tests to error.

