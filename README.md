# EtnaMonitor — Panoramica

![Badge Python](https://img.shields.io/badge/Built_with-Python_3.11+-blue.svg) ![Badge Flask](https://img.shields.io/badge/Backend-Flask-green.svg) ![Badge Plotly](https://img.shields.io/badge/Charts-Plotly-orange.svg)

EtnaMonitor è una piattaforma dedicata al monitoraggio del tremore vulcanico dell'Etna. Il sistema raccoglie i grafici pubblici dell'INGV, elabora automaticamente la curva del tremore e fornisce visualizzazioni interattive e notifiche tempestive.

Obiettivi principali:
- Visualizzazione web in tempo reale con grafico logaritmico e soglia di allerta configurabile.
- Analisi automatica dell'ultima finestra temporale per riconoscere trend in crescita, stabili o in calo.
- Sistema di alert tramite bot Telegram con gestione utenti Free/Premium e riduzione dello spam.


---

## Indice
1. [Architettura del Sistema](#architettura-del-sistema)
2. [Funzionalità Chiave](#funzionalità-chiave)
3. [Directory partner](#directory-partner)
4. [Design system & UX tokens](#design-system--ux-tokens)
5. [Dipendenze & Requisiti](#dipendenze--requisiti)
6. [Setup Locale (Step-by-step)](#setup-locale-step-by-step)
7. [Configurazione (.env.example)](#configurazione-envexample)
8. [Pipeline Dati (PNG INGV → CSV → Grafico)](#pipeline-dati-png-ingv--csv--grafico)
9. [Hotspot FIRMS](#hotspot-firms)
10. [Notifiche Telegram](#notifiche-telegram)
11. [Gestione Utenti e Premium](#gestione-utenti-e-premium)
12. [Logging & Monitoraggio](#logging--monitoraggio)
13. [Deploy (Ambiente di Produzione)](#deploy-ambiente-di-produzione)
14. [Sicurezza & Privacy](#sicurezza--privacy)
15. [GA4 & CSP](#ga4--csp)
16. [Troubleshooting (FAQ Tecnica)](#troubleshooting-faq-tecnica)
17. [Roadmap](#roadmap)
18. [Licenza & Note Legali](#licenza--note-legali)
19. [Contatti](#contatti)

---

## Architettura del Sistema
```mermaid
flowchart LR
    A[Sorgente PNG INGV] --> B[Estrazione curva verde]
    B --> C[CSV Tremore]
    C --> D[Backend Flask]
    D --> E[Plotly Renderer]
    E --> F[Dashboard Web]
    D --> G[Bot Telegram]
    G --> H[Notifiche]
    D --> I[Logging]
```

### Componenti principali
- **Backend Flask**: fornisce API REST, gestione sessioni, orchestrazione pipeline e autenticazione utenti.
- **Plotly**: genera grafici interattivi con scala logaritmica, soglia rossa e annotazioni dell'ultimo aggiornamento.
- **Script analitici**: estraggono la curva verde dal PNG, applicano filtri e calcolano statistiche dell'ultima finestra.
- **Gestione utenti**: database con ruoli Free/Premium, salvataggio impostazioni personalizzate e cronologia accessi.
- **Bot Telegram**: invia alert, gestisce iscrizioni, conferma superamento soglia e applica hysteresis.
- **Storage locale (file/CSV)**: repository dei dati elaborati (`data/`) e log (`logs/`) con rotazione.
- **Logging**: centralizza eventi applicativi, notifiche e anomalie pipeline per audit e troubleshooting.

### Flusso dati
1. Scaricamento periodico del PNG INGV e parsing tramite script dedicati.
2. Normalizzazione della curva e scrittura su CSV.
3. Backend Flask carica i dati, esegue analisi statistica e prepara dataset per Plotly.
4. La dashboard web espone grafico interattivo e stato utenti, aggiornandosi automaticamente.
5. In parallelo il bot Telegram valuta le soglie per ogni utente e spedisce notifiche quando necessario.
6. Ogni passo registra log strutturati per verificabilità e auditing.

## Funzionalità Chiave
- **Dashboard web**: tema scuro, grafico interattivo con zoom, soglia rossa configurabile, badge di stato ultimo aggiornamento e trend.
- **Analisi automatica “ultima finestra”**: calcolo media mobile configurabile, identificazione trend (in crescita/stabile/in calo) e messaggistica in dashboard.
- **Sistema utenti**:
  - Free: soglia standard, accesso dashboard, log limitati.
  - Premium: soglie personalizzate, notifiche Telegram avanzate, storico eventi esteso.
- **Notifiche Telegram**: invio al superamento soglia, gestione hysteresis/debounce per evitare spam, alert riassuntivi.
- **Log eventi recenti**: elenco con timestamp, valore misurato, soglia applicata, esito alert visibile dalla dashboard.
- **Admin**: pannello opzionale per consultare utenti, promuovere/demozionare Premium e monitorare stato notifiche.

## Directory partner
La directory EtnaMonitor è organizzata in categorie a numero chiuso (es. Guide, Hotel, Ristoranti) con massimo 10 slot attivi per ognuna.

### Rotte pubbliche
- `GET /guide`, `GET /hotel`, `GET /ristoranti`, `GET /categoria/<slug>`: elenco ordinato con badge “Featured”, contatti rapidi e banner lista d'attesa quando la categoria è piena.
- `GET /categoria/<slug>/<partner>`: scheda dettagliata con CTA telefonica/WhatsApp, galleria immagini, JSON-LD LocalBusiness e modulo contatto che salva un `PartnerLead` e notifica admin/partner via email.
- Quando gli slot sono esauriti i visitatori possono registrarsi nella waitlist (`POST /categoria/<slug>/waitlist`).

### Gestione amministrativa `/admin/partners`
- Dashboard con stato slot per categoria, inserimento manuale dei partner e azioni di workflow (bozza → pending → approved/expired/disabled).
- “Approva & Crea sottoscrizione” genera un record `PartnerSubscription` con pagamento manuale (PayPal o contanti), calcolo prezzi dinamici (30 € primo anno, 50 € rinnovo) e fattura PDF salvata in `static/invoices/<anno>/` tramite ReportLab.
- Reminder e rinnovi sono gestiti interamente dall'admin (possibilità di segnare una sottoscrizione come scaduta o crearne una nuova). I pagamenti avvengono fuori dal sito e non è previsto alcun checkout.

## Design system & UX tokens
L'intera interfaccia adotta un sistema di token centralizzato definito in [`app/static/css/theme.css`](app/static/css/theme.css). I componenti devono riferirsi a queste variabili per garantire coerenza cromatica, tipografica e di spaziature.

### Palette cromatica
| Token | Valore | Uso consigliato |
|-------|--------|-----------------|
| `--color-bg-primary` | `#070b1a` | Sfondo principale delle pagine e delle sezioni full-bleed. |
| `--color-bg-secondary` | `#0c1427` | Pannelli secondari, footer e overlay modali. |
| `--color-surface` | `#0f1a30` | Card, contenitori hero, blocchi informativi. |
| `--color-surface-hover` | `#172640` | Stato hover/focus per card o link prominenti. |
| `--color-text-primary` | `#f4f8ff` | Testo base, titoli e CTA. |
| `--color-text-secondary` | `#c0cae6` | Testo descrittivo, paragrafi lunghi e metadati. |
| `--color-text-tertiary` | `#8f9bb9` | Label secondarie, badge e micro copy. |
| `--color-accent-primary` | `#00d2ff` | Elementi d'azione, indicatori live e icone interattive. |
| `--color-accent-secondary` | `#6366f1` | Gradients complementari, stati attivi o CTA secondarie. |
| `--color-success` / `--color-warning` / `--color-error` | Palette stato | Badge stato e messaggi contestuali. |

### Tipografia
| Token | Valore | Uso |
|-------|--------|-----|
| `--font-family-primary` | `Inter`, fallback system | Corpo testo, pulsanti, input. |
| `--font-family-headings` | `Montserrat`, fallback system | Titoli, hero heading, numeri KPI. |
| `--font-size-2xs` → `--font-size-5xl` | Scala 11–48px | Clamp e step modulari per testo responsive. |
| `--font-weight-regular` / `--font-weight-medium` / `--font-weight-semibold` / `--font-weight-bold` | 400–700 | Peso tipografico coerente su componenti interattivi e titoli. |
| `--line-height-tight` / `--line-height-normal` / `--line-height-relaxed` | 1.25–1.75 | Gestione leggibilità per hero, paragrafi e note. |

### Spaziature & raggi
| Token | Valore | Uso |
|-------|--------|-----|
| `--space-2xs` → `--space-7xl` | Scala 4–96px | Margini e gap generali; usare alias `--space-1/2/...` per retrocompatibilità. |
| `--radius-sm` / `--radius-md` / `--radius-lg` / `--radius-2xl` | 6–24px | Rounding di card, badge e layout hero. |

### Z-index & shadow
| Token | Valore | Uso |
|-------|--------|-----|
| `--z-nav` / `--z-fixed` / `--z-modal` | 1100–1150 | Layering per navbar sticky, floating nav e modali. |
| `--shadow-sm` → `--shadow-floating` | Preset morbidi e profondi | Ombre per card, tooltip, hero e componenti sospesi. |
| `--gradient-primary` / `--gradient-hero` | Gradients brand | Background hero, CTA prominenti, highlight grafico. |

> **Suggerimento**: quando si introduce un nuovo componente, preferire i token esistenti. Se serve un nuovo valore, aggiungerlo in `theme.css` e documentarlo qui per mantenere la singola fonte di verità.

## Dipendenze & Requisiti
- **Runtime**: Python 3.11+, pip, virtualenv.
- **Librerie principali**: Flask, Plotly, pandas, Pillow o OpenCV (per analisi PNG), numpy, requests, python-dotenv, schedule (o cron equivalent), SQLAlchemy (per utenti), gunicorn (per deploy), loguru o logging standard.
- **Requisiti di sistema**: CPU dual-core, 2 GB RAM, 200 MB storage libero per dataset storici. Funziona su Linux, Windows e macOS.

## Setup Locale (Step-by-step)
```bash
# 1. Clonare il repository
git clone https://github.com/<ORGANIZZAZIONE>/etna-monitor.git
cd etna-monitor

# 2. Creare e attivare l'ambiente virtuale
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate

# 3. Installare le dipendenze
pip install -r requirements.txt

# 4. Configurare l'ambiente
cp .env.example .env  # oppure creare manualmente seguendo la sezione dedicata

# 5. Applicare le migrazioni del database
flask db upgrade  # richiede Flask-Migrate installato

# 6. Avviare il backend Flask
python app.py  # in alternativa: flask run

# 7. Aprire la dashboard
open http://127.0.0.1:5000  # Windows: start, Linux: xdg-open
```

> **Nota**: l'uso di `flask db` richiede il pacchetto `Flask-Migrate`. In ambienti senza accesso a internet
> assicurarsi di installarlo manualmente oppure eseguire le migrazioni su una macchina con accesso al pacchetto.

## Configurazione (.env.example)
```env
# Sicurezza
SECRET_KEY=change-me

# Database
DATABASE_URL=postgresql+psycopg2://user:password@host:5432/etnamonitor

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ENABLE_TELEGRAM_BOT=false

# Stripe
STRIPE_PUBLIC_KEY=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
STRIPE_PRICE_PREMIUM=

# OAuth e analytics
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=
PLAUSIBLE_DOMAIN=
GA_MEASUREMENT_ID=

# Generali
ADMIN_EMAILS=
CANONICAL_HOST=
LOG_DIR=logs
DATA_DIR=data
DISABLE_SCHEDULER=false
INGV_URL=https://www.ct.ingv.it/RMS_Etna/2.png
ALERT_THRESHOLD_DEFAULT=2.0
```

| Variabile | Descrizione |
|-----------|-------------|
| `SECRET_KEY` | Chiave segreta per sessioni e CSRF; **obbligatoria** in produzione. |
| `DATABASE_URL` | Connessione al database (PostgreSQL, MySQL o SQLite). |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Credenziali Telegram; lasciare vuote per disattivare il bot. |
| `ENABLE_TELEGRAM_BOT` | Abilita l'avvio del bot Telegram all'avvio dell'app. |
| `STRIPE_*` | Chiavi e prezzi per l'integrazione Stripe. |
| `GOOGLE_*` | Credenziali OAuth Google. |
| `PLAUSIBLE_DOMAIN`, `GA_MEASUREMENT_ID` | Identificativi analytics opzionali. |
| `ADMIN_EMAILS` | Lista di email (separate da virgola) da promuovere automaticamente come admin. |
| `LOG_DIR`, `DATA_DIR` | Directory persistenti per log e dati. |
| `DISABLE_SCHEDULER` | Imposta `true`/`1` per evitare l'avvio dello scheduler (utile nei test). |
| `ALERT_THRESHOLD_DEFAULT` | Soglia tremore predefinita (mV). |
| `PARTNER_DIRECTORY_ENABLED` | Imposta `0` per nascondere completamente la directory partner. |
| `PARTNER_DEFAULT_MAX_SLOTS` | Numero massimo di partner approvati per categoria (default 10). |
| `PARTNER_FIRST_YEAR_PRICE` / `PARTNER_RENEWAL_PRICE` | Prezzi in euro per sottoscrizioni manuali (30 € primo anno, 50 € rinnovo). |
| `PARTNER_PAYMENT_METHODS` | Metodi ammessi per pagamenti manuali (es. `paypal_manual,cash`). |

## Pipeline Dati (PNG INGV → CSV → Grafico)
1. **Download**: uno scheduler scarica periodicamente il grafico PNG pubblico fornito da INGV.
2. **Estrazione curva verde**: applicazione di una maschera HSV o filtro colore per isolare la curva del tremore; successiva pulizia tramite median blur e thinning per ottenere punti vettoriali.
3. **Conversione unità**: trasformazione della posizione dei pixel in valori di tremore in millivolt con scala log10 secondo la legenda del PNG.
4. **Persistenza**: salvataggio in CSV con schema `timestamp, valore_mV, media_mobile, note`. File archiviati in `data/` con rotazione giornaliera.
5. **Rendering**: Plotly genera grafico linea verde su asse Y logaritmico, sovrappone soglia rossa e indicatori dell'ultimo valore.
6. **Considerazioni**: gestione ritardi aggiornamento sorgente, retry con backoff esponenziale, notifiche di errore se il PNG non è aggiornato oltre una soglia temporale.

## Hotspot FIRMS
EtnaMonitor integra i dati NASA FIRMS per visualizzare hotspot termici satellitari in un canale indipendente dal tremore.

### Variabili ambiente
```env
HOTSPOTS_ENABLED=false
FIRMS_MAP_KEY=
FIRMS_SOURCE=VIIRS_SNPP_NRT
ETNA_BBOX=14.85,37.55,15.25,37.90
HOTSPOTS_DAY_RANGE=1
HOTSPOTS_CACHE_TTL_MIN=180
HOTSPOTS_DEDUP_KM=1.0
HOTSPOTS_DEDUP_HOURS=2
HOTSPOTS_NEW_WINDOW_HOURS=12
```

### Aggiornamento cache
```bash
python backend/scripts/update_hotspots.py
```

### Test endpoint e pagina
```bash
curl http://127.0.0.1:5000/api/hotspots/latest
open http://127.0.0.1:5000/hotspots
```

## Notifiche Telegram
- **Collegamento account**: l'utente fornisce il proprio `chat_id` tramite comando `/start`, che viene associato al profilo in dashboard.
- **Trigger alert**: viene inviato un messaggio quando la media dell'ultima finestra supera la soglia personalizzata. L'hysteresis evita notifiche ripetute finché il valore non rientra sotto la soglia meno un margine.
- **Frequenza consigliata**: impostare `TELEGRAM_ALERT_INTERVAL_MIN` tra 60 e 180 minuti per bilanciare tempestività e riduzione dello spam.
- **Best practice sicurezza**: non pubblicare il token del bot, archiviarlo solo nel file `.env` e limitare l'accesso ai log che contengono `chat_id`.

## Gestione Utenti e Premium
- **Registrazione/Login**: form con validazione email; password memorizzate con hashing (es. PBKDF2/Bcrypt). Possibile integrazione OAuth opzionale.
- **Dashboard**: badge che indica stato Free o Premium e riepilogo delle impostazioni personali.
- **Attivazione Premium**: pagamento manuale tramite link placeholder `<PAYPAL_DONATION_LINK>`; l'admin abilita lo stato Premium dal pannello dedicato.
- **Soglie personalizzate**: interfaccia per modificare il livello di allerta; validazione su range plausibili (es. 0.5–10 mV) con persistenza su database.
- **Privacy self-service**: l'utente autenticato può esportare i propri dati in JSON (`/account/export-data`) e richiedere in autonomia la cancellazione con conferma via email (`/account/delete-request`). Il purge definitivo avviene entro 30 giorni (configurabile tramite `ACCOUNT_SOFT_DELETE_TTL_DAYS`).
- **Ruoli avanzati**: oltre agli admin è disponibile il ruolo `moderator`, abilitato alla sola approvazione/rifiuto dei post community.
- **Community hub**: ogni utente può creare post (default `pending`) dall'area community, con moderazione e audit trail disponibili nel pannello `/admin/moderation/queue`.

## Logging & Monitoraggio
- **Storage log**: file testuali in `./logs`, rotazione giornaliera e livelli (INFO, WARNING, ERROR). Possibile integrazione con `logging.handlers.RotatingFileHandler`.
- **Eventi alert**: ogni notifica registra timestamp, valore, soglia, utente e esito (inviato/scartato). I record sono consultabili dalla dashboard e via API admin.
- **Estensioni future**: esportazione verso ELK/Graylog o metriche Prometheus per dashboarding avanzato.

## Deploy (Ambiente di Produzione)
1. **Target**: servizi PaaS (Render, Fly.io) o VPS con Docker/gunicorn + Nginx come reverse proxy.
2. **Variabili ambiente**: replicare il contenuto di `.env` tramite segreti del provider. Non caricare file `.env` direttamente.
3. **Static & storage**: montare volumi persistenti per `data/` e `logs/`; configurare caching statici.
4. **Scheduler**: impostare cron job o worker separato per eseguire la pipeline PNG→CSV (es. `python etna_loop.py`).
5. **Hardening**: usare `SECRET_KEY` robusto, abilitare HTTPS, configurare header di sicurezza (HSTS, CSP), limitare rate sulle API e monitorare errori.

### Render – Start Command
- Impostare `FLASK_APP=app:create_app` nelle variabili di ambiente di Render.
- Configurare lo **Start Command** su Render a:

  ```bash
  flask db upgrade && gunicorn wsgi:app --workers 3 --threads 2 --timeout 120
  ```

  In questo modo le migrazioni vengono applicate automaticamente prima dell'avvio di Gunicorn.

- Configurare il **Pre-deploy Command** su Render a:

  ```bash
  ALEMBIC_RUNNING=1 SKIP_SCHEMA_VALIDATION=1 ALEMBIC_SKIP_BACKFILL=1 PYTHONPATH=. alembic -c alembic.ini upgrade head
  ```

  Questo export evita side-effect applicativi durante l'esecuzione delle migration.

### Zero-downtime migrations on Render

Il deploy su Render si articola ora in tre step per mantenere il downtime nullo:

1. **Schema-only** – Il pre-deploy (`alembic upgrade head` con `ALEMBIC_SKIP_BACKFILL=1`) applica solo la migrazione 202503010002,
   aggiungendo `partners.category_id`, l'indice e il vincolo `NOT VALID` senza bloccare tabelle.
2. **One-off backfill** – Dopo il deploy eseguire un job one-off per popolare i dati:

   ```bash
   render one-off: python app/scripts/run_backfill_partners_category.py
   ```

   oppure, riutilizzando il contesto Flask:

   ```bash
   render one-off: flask backfill-partners-category
   ```

   Lo script legge `DATABASE_URL`, elabora chunk configurabili via `BACKFILL_CHUNK` (default 2000) con keyset pagination e logga i
   progressi (riprende automaticamente da dove si ferma).
3. **Validazione FK** – Una volta completato il backfill rimuovere `ALEMBIC_SKIP_BACKFILL` e validare il vincolo con una seconda
   one-off:

   ```bash
   render one-off: alembic -c alembic.ini upgrade head
   ```

   In alternativa è possibile targettare direttamente la migrazione `202503010003_validate_fk`.

- Se in produzione la tabella `partners` è già presente ma Alembic risulta fermo a `20240702_add_plan_fields`, dopo aver reso la migration idempotente puoi, se necessario, riallineare manualmente lo stato con:

  ```bash
  alembic stamp 202407200001
  ```

  Usa questo comando solo per sanare ambienti già esistenti; non automatizzarlo nel flusso di deploy.

## Sicurezza & Privacy
- Non committare `.env`, token o database con dati reali; usare gitignore e segreti di deploy.
- Validare e sanificare input utente; proteggere form con CSRF token e rate limiting.
- Gestire sessioni server-side con scadenze definite e revoca manuale per account compromessi.
- Eseguire backup regolari di `data/` e `logs/` su storage cifrato; testare procedure di restore.
- Raccogliere solo dati minimi necessari; informare gli utenti sull'uso dei dati in modo conforme alle normative locali (es. GDPR).


## GA4 & CSP
- L'head template con GA attivo carica **un solo** script loader di Google Ads (`AW-17681413584`) e, nello stesso blocco inline protetto da nonce, invoca `gtag('config', 'AW-17681413584')` e `gtag('config', 'G-Z3ESSERP7W')`. Il setup è centralizzato in [`app/templates/layout.html`](app/templates/layout.html) per evitare duplicazioni e mantenere l'allineamento con la CSP.
- Per attivare il debug imposta la variabile d'ambiente `GA_DEBUG=true` prima di avviare l'app **oppure** apri qualsiasi pagina con l'aggiunta del parametro `?dbg=1` alla query string.
- La Content Security Policy è definita in [`app/security.py`](app/security.py) e include i domini di Google necessari a GA4/Ads (`https://*.googletagmanager.com`, `https://*.google-analytics.com`, `https://*.doubleclick.net`, `https://*.google.com`, `https://*.google.it`, `https://*.gstatic.com`) e le CDN per i font/stili (`https://fonts.googleapis.com`, `https://fonts.gstatic.com`, `https://cdnjs.cloudflare.com`, `https://cdn.plot.ly`). `https://www.google.it` è esplicitamente consentito (insieme al wildcard) per evitare blocchi CSP su pixel di remarketing regionalizzati.
- Per verificare il tracciamento apri Chrome DevTools → Network dopo aver visitato la home con `?dbg=1` e controlla che la richiesta `https://www.googletagmanager.com/gtag/js?id=AW-17681413584` risponda con `200` e che compaiano chiamate `https://region1.google-analytics.com/g/collect` (stato `204`).
- La pagina di diagnostica `/ga4/diagnostics` mostra lo stato di `window.gtag`, la lunghezza della `dataLayer` e include un link rapido alla home con debug per accelerare i test. L'endpoint `/csp/test` restituisce l'header CSP applicato alla home per velocizzare i controlli.

## Troubleshooting (FAQ Tecnica)
- **Il grafico è piatto o sballato**: controllare che l'asse Y sia in scala log, verificare che il PNG INGV sia aggiornato e che la soglia sia correttamente impostata.
- **Non arrivano gli alert**: assicurarsi che il `chat_id` sia associato, il `TELEGRAM_BOT_TOKEN` sia valido, la finestra di analisi non sia troppo ampia e l'intervallo antispam non blocchi gli invii.
- **Errori di permessi su `data/` o `logs/`**: verificare i permessi della directory, su Linux usare `chmod 755` e su Windows eseguire come amministratore o modificare le ACL.
- **Timeout nel download PNG**: aumentare timeout richieste, abilitare retry con backoff e confermare che l'URL INGV sia raggiungibile dalla macchina.

## 🔐 Security & XSS protection
- Tutti i contributi della community vengono sanificati tramite `bleach` con whitelist di tag, attributi e protocolli sicuri.
- Il campo `body_html_sanitized` viene utilizzato in produzione e nelle template per impedire l'esecuzione di script salvati.
- La coda di moderazione mostra differenze rispetto al contenuto originale ed evidenzia markup rimosso.
- Utilizza lo script `python scripts/remove_suspicious_posts.py` per oscurare rapidamente post contenenti payload sospetti.
- I template front-end e le risposte Flask restituiscono header di sicurezza (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy) e cookie di sessione `Secure`, `HttpOnly`, `SameSite=Lax`.

## Roadmap
- Integrazione con mappa interattiva dei sensori regionali.
- Supporto a sensori fisici tramite LoRa/IoT per arricchire il dataset.
- Algoritmi di analisi predittiva basati su AI/ML.
- Esportazione dataset aggregati e anonimizzati per uso pubblico.
- Pannello admin avanzato con filtri, statistiche e gestione massiva utenti.

## Licenza & Note Legali
- **Licenza del codice**: Per il riutilizzo del progetto è necessario ricevere autorizzazione scritta dal creatore del progetto.
- **Fonti dati**: grafici pubblici INGV, soggetti ai loro termini d'uso.

> EtnaMonitor utilizza esclusivamente grafici pubblici forniti dall’INGV per scopi divulgativi.  
> Il progetto non è affiliato né approvato da INGV. Tutti gli algoritmi di analisi, la piattaforma web e i sistemi di notifica sono proprietà intellettuale del progetto EtnaMonitor.

## Contatti
- Email: `salvoferro16@gmail.com`
- Pagina About: `https://etnamonitor.it`

---
