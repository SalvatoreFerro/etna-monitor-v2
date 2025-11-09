# Privacy, GDPR e moderazione community

Questa sezione descrive il flusso completo introdotto per rispondere ai requisiti GDPR (export/cancellazione dati) e per gestire i contenuti generati dagli utenti.

## Self-service account deletion

1. L'utente autenticato compila il form nelle impostazioni (`/account/delete-request`).
2. Dopo la validazione CSRF/rate-limit viene inviata una mail con link firmato (`itsdangerous`, validità 48h configurabile via `ACCOUNT_DELETE_TOKEN_MAX_AGE`).
3. Il link (`/account/delete-confirm/<token>`) esegue:
   - `soft_delete()` → `deleted_at` e `is_active=False`.
   - `anonymize()` → email/token random, azzera campi personali, revoca notifiche.
   - Pianificazione purge: il job `scripts/purge_erased_accounts.py` rimuove definitivamente i contenuti dopo `ACCOUNT_SOFT_DELETE_TTL_DAYS` (default 30).
4. `erased_at` viene valorizzato dal job per tracciare l'avvenuto purge.

> Nota legale: eventuali record fiscali restano anonimi ma non cancellati, come richiesto dalla normativa contabile.

## Export dati utente

- Endpoint autenticato `GET /account/export-data` → restituisce JSON con informazioni profilo, impostazioni principali e tutti i post/moderation log associati.
- Utilizza `application/json` per consentire portabilità machine-readable.

## Community posts & moderazione

- Nuovo modello `posts` con stati `draft`, `pending`, `approved`, `rejected`, `hidden`.
- I contenuti sono sanificati con `bleach` (tag consentiti: paragrafi, liste, link, code).
- Creazione via `/community/new` (opzionale reCAPTCHA se `RECAPTCHA_SITE_KEY`/`SECRET_KEY` sono configurati).
- Pending visibili solo all'autore autenticato e ai moderatori.
- Moderazione in `/admin/moderation/queue` (ruoli `admin` e `moderator`), azioni `approve`/`reject` con audit trail nella tabella `moderation_actions` e notifica email.

### Ruoli e permessi

| Ruolo       | Permessi principali |
|-------------|---------------------|
| `free`      | Accesso base, creazione post (pending) |
| `premium`   | Stesse azioni free + badge visivo |
| `moderator` | Accesso coda moderazione, approvazione/rifiuto post |
| `admin`     | Tutti i permessi esistenti + promozione utenti |

`moderator` non può gestire utenti/donazioni.

## Sicurezza e qualità

- **CSRF**: tutti i form usano token session-based.
- **Rate limit**: gestito con `Flask-Limiter` (es. 3 richieste/ora per delete/export, 10/min per azioni moderazione).
- **Captcha**: se abilitato (`COMMUNITY_RECAPTCHA_*`) viene richiesto agli utenti non verificati/premium.
- **Audit**: tutte le azioni di moderazione sono registrate con timestamp e motivazione.
- **Purge**: eseguire periodicamente `python scripts/purge_erased_accounts.py` (cron/worker) per completare il ciclo GDPR.

## Variabili d'ambiente rilevanti

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `ACCOUNT_SOFT_DELETE_TTL_DAYS` | `30` | Giorni di retention prima del purge definitivo. |
| `ACCOUNT_DELETE_TOKEN_MAX_AGE` | `172800` | Validità link conferma in secondi (48h). |
| `RECAPTCHA_SITE_KEY` / `RECAPTCHA_SECRET_KEY` | vuoto | Attiva il captcha nel form community. |
| `COMMUNITY_CAPTCHA_OPTIONAL` | `true` | Se `false` richiede sempre il captcha quando attivo. |

## Testing

- `pytest tests/test_account_community.py` copre soft-delete, export, moderazione e flusso end-to-end.
- Email inviate salvate in memoria (`app.extensions['email']['outbox']`) per asserzioni nelle suite.
