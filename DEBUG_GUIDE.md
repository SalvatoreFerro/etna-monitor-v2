# DEBUG GUIDE: Dashboard "Errore nel caricamento dati"

**Data:** 2026-02-03  
**Stato:** Post-fix PR #500 (robustness /api/curva)  
**Problema:** Dashboard mostra "Errore nel caricamento dati" nonostante i fix recenti

---

## A) PRODUCTION VERIFICATION CHECKLIST (10 minuti max)

### Passi da eseguire da browser (iPhone/Desktop):

#### 1. Test `/api/status` endpoint
```
URL: https://[your-production-domain]/api/status
```

**Cosa guardare:**
- **Status code:** Deve essere `200`
- **Content-Type header:** Deve essere `application/json`
- **Contenuto JSON:** Deve avere queste chiavi:
  ```json
  {
    "ok": true,
    "current_value": <numero>,
    "above_threshold": <boolean>,
    "threshold": <numero>,
    "last_update": "<timestamp ISO>",
    "total_points": <numero>
  }
  ```

**Come capire se è HTML/JSON/errore:**
- Se vedi `<!DOCTYPE html>` o `<html>` → **Stai ricevendo HTML** (probabilmente redirect a login o errore 500)
- Se vedi `{` all'inizio → **JSON corretto**
- Se status code è 401 → **Non autenticato** (redirect a login)
- Se status code è 500 → **Errore server**

**Azione:**
- ✅ Se `/api/status` funziona e restituisce JSON con `ok: true` → Endpoint status OK
- ❌ Se restituisce HTML o 401 → Problema autenticazione
- ❌ Se restituisce 500 → Problema server/CSV path

---

#### 2. Test `/api/curva` endpoint (default limit)
```
URL: https://[your-production-domain]/api/curva
```

**Cosa guardare:**
- **Status code:** Deve essere `200` (anche se ok:false)
- **Content-Type header:** Deve essere `application/json`
- **JSON structure:** Deve avere almeno la chiave `"ok"`

**Possibili risposte valide:**

**Successo (ok: true):**
```json
{
  "ok": true,
  "data": [
    {"timestamp": "2026-02-03T10:00:00.000000Z", "value": 1.23},
    ...
  ],
  "last_ts": "2026-02-03T10:00:00.000000Z",
  "rows": 2016,
  "csv_mtime_utc": "2026-02-03T10:00:00.000000+00:00",
  "source": "file",
  "updated_at": "...",
  "detected_today": true,
  "is_stale": false
}
```

**Errore (ok: false) - Dati insufficienti:**
```json
{
  "ok": false,
  "error": "Insufficient valid data",
  "reason": "missing_timestamp" | "empty_data" | "insufficient_valid_data",
  "rows": 0
}
```

**Come capire cosa stai ricevendo:**
- Se vedi `{` all'inizio → JSON
- Se vedi `<!DOCTYPE` → HTML (redirect/errore)
- Se browser scarica un file → Problema content-type
- Se vedi "unauthorized" o 401 → Non autenticato

**Azione:**
- ✅ Se JSON con `ok: true` e `data` array non vuoto → Endpoint OK
- ⚠️ Se JSON con `ok: false` → Dati insufficienti ma endpoint funziona (vedi sezione D per diagnosi)
- ❌ Se HTML o 401 → Problema autenticazione/routing
- ❌ Se 500 → Errore server (vedi sezione D)

---

#### 3. Test `/api/curva` con limit=50
```
URL: https://[your-production-domain]/api/curva?limit=50
```

**Cosa guardare:**
- Stesso schema di risposta del punto 2
- Se `ok: true`, il campo `"rows"` deve essere circa 50 (o meno se dati insufficienti)

**Azione:**
- ✅ Se funziona come punto 2 → OK
- ❌ Se diverso dal punto 2 → Problema con gestione parametri

---

#### 4. Test `/api/curva` con limit=2016 (default dashboard)
```
URL: https://[your-production-domain]/api/curva?limit=2016
```

**Cosa guardare:**
- Stesso schema di risposta
- Se `ok: true`, il campo `"rows"` deve essere circa 2016

**Azione:**
- ✅ Se funziona → OK
- ❌ Se `ok: false` con reason="empty_after_limit" → CSV troppo piccolo
- ❌ Se timeout → Dataset troppo grande per limite richiesto

---

#### 5. Verifica autenticazione
```
Prima fai logout completo, poi prova:
URL: https://[your-production-domain]/api/curva
```

**Cosa guardare:**
- **Status code:** Deve essere `401 Unauthorized`
- **Content-Type:** Deve essere `application/json` (NON HTML)
- **JSON:**
  ```json
  {
    "ok": false,
    "error": "unauthorized"
  }
  ```

**Azione:**
- ✅ Se ricevi JSON 401 con `{"ok": false, "error": "unauthorized"}` → Fix PR #500 è attivo
- ❌ Se ricevi HTML redirect → Fix PR #500 NON è attivo (vecchia versione in produzione)
- ❌ Se ricevi 200 senza autenticazione → Bug di sicurezza grave

---

#### 6. Check browser console (DevTools)

**Azione:**
1. Apri la dashboard
2. Apri DevTools (F12)
3. Vai su tab "Network"
4. Ricarica pagina
5. Filtra per `/api/curva`

**Cosa guardare:**
- **Request Status:** 200, 401, 500, o altro?
- **Response Type:** `application/json` o `text/html`?
- **Response Preview:** JSON valido o HTML?
- **Request Headers:** Include `Accept: application/json`?
- **Response Headers:** Include `Content-Type: application/json`?

**Azione:**
- Se vedi request a `/api/curva` con status 200 ma response HTML → **CAUSA #5 (route shadowing)**
- Se vedi request con status 401 → **CAUSA #1 (problema autenticazione/sessione)**
- Se vedi request con status 500 → **CAUSA #3 (CSV path/parsing/permessi)**
- Se vedi request con status 200 e JSON `ok:false` → **CAUSA #2 (data insufficiente)**

---

## B) EXPECTED PAYLOAD SCHEMA

### `/api/curva` - Success Response (ok: true)

```json
{
  "ok": true,
  "data": [
    {
      "timestamp": "2026-02-03T10:00:00.000000Z",
      "value": 1.234
    },
    ...more records...
  ],
  "last_ts": "2026-02-03T14:30:00.000000Z",
  "rows": 2016,
  "csv_mtime_utc": "2026-02-03T14:30:00.000000+00:00",
  "source": "file",
  "updated_at": "2026-02-03T14:30:00+00:00",
  "detected_today": true,
  "is_stale": false
}
```

**Chiavi richieste da dashboard.js:**
- `ok` (boolean) - **OBBLIGATORIA**
- `data` (array) - **OBBLIGATORIA se ok:true**, array di oggetti con `timestamp` e `value`
- `last_ts` (string ISO) - Usata per mostrare ultimo aggiornamento
- `rows` (number) - Numero di record restituiti

**Chiavi opzionali ma utili:**
- `updated_at`, `detected_today`, `is_stale` - Info temporali
- `csv_mtime_utc` - Timestamp modifica file CSV
- `source` - "file" o "fallback"
- `warning` - Se c'è stato un problema non fatale
- `csv_path_used` - Solo per admin/debug

---

### `/api/curva` - Error Response (ok: false)

```json
{
  "ok": false,
  "error": "Insufficient valid data",
  "reason": "missing_timestamp" | "empty_data" | "insufficient_valid_data" | "empty_after_limit",
  "rows": 0
}
```

**Chiavi richieste da dashboard.js:**
- `ok` (boolean) - **OBBLIGATORIA**
- `error` (string) - Messaggio di errore
- `reason` (string) - Codice errore tecnico

---

### `/api/curva` - Unauthorized Response (401)

```json
{
  "ok": false,
  "error": "unauthorized"
}
```

**Status code:** 401  
**Content-Type:** `application/json`

**Fix applicato in PR #500:** Forza risposta JSON 401 invece di redirect HTML.

---

### `/api/curva` - Server Error Response (500)

```json
{
  "ok": false,
  "error": "detailed error message from exception"
}
```

**Status code:** 500  
**Content-Type:** `application/json`

---

### `/api/status` - Success Response

```json
{
  "ok": true,
  "current_value": 1.234,
  "above_threshold": false,
  "threshold": 2.0,
  "last_update": "2026-02-03T14:30:00.000000Z",
  "updated_at": "2026-02-03T14:30:00+00:00",
  "detected_today": true,
  "is_stale": false,
  "total_points": 2016
}
```

**Chiavi richieste da dashboard.js:**
- `ok` (boolean)
- `current_value` (number)
- `above_threshold` (boolean)
- `last_update` (string ISO)

---

## C) HOW TO CONFIRM DEPLOYED COMMIT

### Metodo 1: Controllare comportamento 401 (CHEAP, no code change)

**Test:**
1. Fai logout completo
2. Apri DevTools → Network tab
3. Vai a `https://[domain]/api/curva`
4. Guarda Response Headers e Response Body

**Se vedi:**
- ✅ **Status 401** + **Content-Type: application/json** + **Body: `{"ok": false, "error": "unauthorized"}`** → **FIX PR #500 ATTIVO**
- ❌ **Status 302** o redirect HTML → **Vecchia versione** (pre-PR #500)

**Codice di riferimento (app/routes/api.py, linee 115-119):**
```python
@api_bp.get("/api/curva")
def get_curva():
    """Return curva.csv data as JSON with no-cache headers"""
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
```

---

### Metodo 2: Controllare log structure in CSV stats (CHEAP, no code change)

**Se hai accesso ai log di produzione**, cerca questa riga:

```
[API] curva csv stats path=... raw_rows=... parsed_rows=... rows_after_dropna=...
```

**Se vedi questa riga nei log:**
- ✅ **Presente** → Fix PR #500 attivo (linee 153-159 in api.py)
- ❌ **Assente** → Vecchia versione

**Codice di riferimento (app/routes/api.py, linee 153-159):**
```python
current_app.logger.warning(
    "[API] curva csv stats path=%s raw_rows=%s parsed_rows=%s rows_after_dropna=%s",
    csv_path,
    stats.get("raw_rows"),
    stats.get("parsed_rows"),
    stats.get("rows_after_dropna"),
)
```

---

### Metodo 3: Controllare header X-Csv-Path-Used (CHEAP, per admin users)

**Se sei autenticato come admin**, la risposta `/api/curva` include:

**Response Headers:**
```
X-Csv-Path-Used: /data/curva_colored.csv
X-Csv-Last-Ts: 2026-02-03T14:30:00.000000Z
```

**Se vedi questi header:**
- ✅ **Presenti** → Fix PR #500 attivo (linee 276-277 in api.py)
- ❌ **Assenti** → Vecchia versione

**Codice di riferimento (app/routes/api.py, linee 276-277):**
```python
if include_csv_path:
    response.headers["X-Csv-Path-Used"] = str(csv_path)
    response.headers["X-Csv-Last-Ts"] = payload.get("last_ts") or ""
```

---

### Metodo 4: Aggiunta minimale per versioning (SE NECESSARIO)

**Se i metodi 1-3 non bastano**, aggiungi questo endpoint una tantum:

**File:** `app/routes/api.py`

```python
@api_bp.get("/api/version")
def get_version():
    """Return deployment version info"""
    return jsonify({
        "ok": True,
        "commit": os.getenv("RENDER_GIT_COMMIT", "unknown")[:8],
        "deployed_at": os.getenv("RENDER_DEPLOYED_AT", "unknown"),
        "instance_id": os.getenv("RENDER_INSTANCE_ID", "unknown"),
    })
```

**Poi testa:**
```
https://[domain]/api/version
```

**Nota:** Render.com espone automaticamente queste variabili d'ambiente. Nessun setup extra richiesto.

---

### Metodo 5: Controllare presenza funzione `_prepare_tremor_dataframe`

**Nel codice sorgente produzione**, cerca in `app/routes/api.py`:

```python
def _prepare_tremor_dataframe(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, str | None, dict]:
```

**Se questa funzione esiste:**
- ✅ **Presente** → Fix PR #500 attivo
- ❌ **Assente** → Vecchia versione

**Codice di riferimento (app/routes/api.py, linee 81-111)**

---

## D) IF/THEN DECISION TREE

### Se `/api/curva` restituisce 401

**Significa:**
- Utente non autenticato o sessione scaduta
- Dashboard ha perso il cookie di sessione
- Cookie di sessione non viene inviato con le richieste fetch

**Possibili cause:**
1. Utente ha fatto logout in un'altra tab
2. Sessione Flask scaduta (default: 31 giorni)
3. Cookie SameSite/Secure incompatibile con dominio
4. Browser blocca cookie di terze parti
5. CORS issue (se frontend e backend su domini diversi)

**Prossimi passi:**
1. Fai login da browser
2. Apri DevTools → Application → Cookies
3. Verifica presenza cookie `session`
4. Riprova `/api/curva`
5. Se ancora 401 → Controlla `fetchDashboardJson` in dashboard.js (linea 528-537) include `credentials: 'include'`

**Codice di riferimento:**
- `app/routes/api.py` linee 117-119 (check autenticazione)
- `app/static/js/dashboard.js` linee 528-537 (fetch con credentials)

---

### Se `/api/curva` restituisce 200 ma ok: false

**Significa:**
- Endpoint funziona correttamente
- File CSV esiste ma dati insufficienti/invalidi
- Parsing CSV ha problemi

**Controlla campo `"reason"` nella risposta:**

#### reason: "missing_timestamp"
**Problema:** CSV non ha colonna `timestamp`

**File:** `app/routes/api.py` linee 89-90

**Azione:**
- Controlla formato CSV in `/data/curva_colored.csv`
- CSV deve avere header: `timestamp,value`

---

#### reason: "empty_data"
**Problema:** CSV vuoto o tutti i timestamp invalidi

**File:** `app/routes/api.py` linee 108-109

**Azione:**
- Controlla CSV ha righe con dati
- Controlla formato timestamp è parseable da pandas
- Guarda log per `[API] curva invalid timestamps samples=...`

---

#### reason: "insufficient_valid_data"
**Problema:** Meno di 10 righe valide dopo parsing

**File:** `app/routes/api.py` linee 185-200

**Azione:**
- CSV troppo piccolo o molti dati corrotti
- Guarda log per `[API] curva dataset insufficient... rows=X`
- Se rows < 10, CSV ha dati insufficienti
- Verifica processo di ingestione dati

---

#### reason: "empty_after_limit"
**Problema:** Dopo `df.tail(limit)`, dataset vuoto

**File:** `app/routes/api.py` linee 225-240

**Azione:**
- CSV esiste ma limit richiesto è maggiore di righe disponibili
- O problema con ordinamento timestamp
- Verifica CSV ha almeno `limit` righe

---

### Se `/api/curva` restituisce 500

**Significa:**
- Exception non gestita nel codice
- CSV path non accessibile
- Permessi file insufficienti
- pandas.read_csv fallisce

**Controlla campo `"error"` nella risposta:**

#### error: "FileNotFoundError" o "No such file"
**Problema:** CSV path non esiste

**File:** `app/routes/api.py` linee 120 (get_curva_csv_path)

**Azione:**
- Controlla env var `CURVA_CSV_PATH` o `CSV_PATH`
- Default path: `/data/curva_colored.csv`
- Verifica directory `/data` esiste
- Verifica permessi lettura

---

#### error: "PermissionError"
**Problema:** CSV esiste ma no permessi lettura

**Azione:**
- Verifica permessi file: `chmod 644 /data/curva_colored.csv`
- Verifica owner processo Flask può leggere file

---

#### error: "ParserError" o parsing-related
**Problema:** CSV malformato

**Azione:**
- Apri CSV e verifica formato
- Deve essere UTF-8
- Nessuna riga con numero colonne diverso da header
- Nessun carattere speciale non escaped

---

### Se `/api/curva` restituisce 200 ma JSON con chiavi diverse

**Significa:**
- Server restituisce JSON valido ma schema diverso da atteso
- Dashboard.js si aspetta `data` ma riceve altro nome
- Mismatch versione API vs frontend

**Possibile causa:**
- **CAUSA #4:** Mismatch schema JSON tra server e dashboard.js

**Azione:**
1. Confronta JSON ricevuto con schema in sezione B
2. Controlla `app/routes/api.py` linee 252-269 (costruzione payload)
3. Controlla `app/static/js/dashboard.js` linee 603-624 (parsing response)

**Fix:**
- Se server restituisce chiave diversa → Update server per usare chiave corretta
- Se dashboard si aspetta chiave diversa → Update dashboard.js

---

### Se `/api/curva` restituisce HTML invece di JSON

**Significa:**
- Request colpisce route diversa da quella patchata
- Flask restituisce pagina errore HTML
- Redirect a login page (pre-PR #500)

**Possibile causa:**
- **CAUSA #5:** Route shadowing o blueprint conflict

**Azione:**
1. Controlla `app/__init__.py` per ordine registrazione blueprint
2. Verifica nessun'altra route con pattern `/api/curva`
3. Usa comando:
   ```bash
   flask routes | grep curva
   ```
   Output atteso:
   ```
   /api/curva  GET  api.get_curva
   ```

**Se vedi più righe con `/api/curva`:**
- ✅ Route shadowing confermato
- Fix: Rimuovi route duplicata o cambia ordine blueprint

**File di riferimento:**
- `app/__init__.py` linee 35-54 (registrazione blueprint)
- `app/routes/api.py` linea 114 (definizione route)

---

## E) MOST LIKELY ROOT CAUSE

### **CAUSA PIÙ PROBABILE: #1 - Deploy non serve ultima versione**

**Probabilità:** 60%

**Motivazione:**
1. `/api/status` funziona → Server è UP e database accessibile
2. Dashboard mostra errore identico pre e post-fix → Comportamento non cambiato
3. PR #500 appena mergiato → Deploy potrebbe non essere completato

**Indicatori:**
- Test 401 senza login restituisce HTML redirect invece di JSON (vedi sezione C, Metodo 1)
- Log non mostrano nuova riga `[API] curva csv stats` (vedi sezione C, Metodo 2)
- Header `X-Csv-Path-Used` assente per admin users (vedi sezione C, Metodo 3)

**Codice di riferimento:**
- `app/routes/api.py` linee 115-119: Check autenticazione con JSON 401
  ```python
  user = get_current_user()
  if not user:
      return jsonify({"ok": False, "error": "unauthorized"}), 401
  ```

**Possibili sotto-cause:**
- Build cache: Render usa vecchi file cached
- Branch sbagliato: Deploy da branch diverso da quello con PR #500
- Deploy in pending: Render non ha ancora completato deploy
- Environment variable: `RENDER_GIT_COMMIT` non aggiornato

**Come verificare:**
1. Vai su Render dashboard
2. Controlla "Latest Deploy" timestamp
3. Confronta con timestamp merge PR #500
4. Se deploy è precedente al merge → Deploy non aggiornato

**Come risolvere:**
1. Trigger manual deploy da Render dashboard
2. Clear build cache se disponibile
3. Verifica branch deployed è quello corretto
4. Aspetta completamento deploy (3-5 minuti)
5. Riprova test in sezione A

---

### CAUSA ALTERNATIVA #2: /api/curva risponde ok:false per dati insufficienti

**Probabilità:** 25%

**Motivazione:**
1. Deploy è aggiornato MA CSV ha problemi reali
2. `/api/status` funziona perché usa funzione diversa per parsing
3. `/api/curva` ha logica più strict con nuovo fix

**Indicatori:**
- Test manuale `/api/curva` restituisce JSON con `ok: false`
- Campo `reason` presente: "insufficient_valid_data", "empty_data", etc.
- Log mostra: `[API] curva dataset insufficient... rows=X` con X < 10

**Codice di riferimento:**
- `app/routes/api.py` linee 81-111: Funzione `_prepare_tremor_dataframe`
  ```python
  def _prepare_tremor_dataframe(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, str | None, dict]:
      # ... parsing e validazione ...
      if df.empty:
          return df, "empty_data", stats
  ```

- `app/routes/api.py` linee 185-200: Check minimum 10 rows
  ```python
  if len(df) < 10:
      current_app.logger.warning(...)
      return jsonify({"ok": False, "error": "Insufficient valid data", ...}), 200
  ```

**Possibili sotto-cause:**
- CSV path sbagliato: `get_curva_csv_path()` restituisce file vuoto/vecchio
- CSV corrotto: Formato invalido, encoding sbagliato
- Timestamp parsing fail: Colonna timestamp con formato non standard
- Permission issue: Processo Flask non può leggere CSV

**Come verificare:**
1. Controlla response JSON ha campo `reason`
2. Controlla log per riga `[API] curva csv stats`
3. Vedi `parsed_rows` vs `raw_rows` vs `rows_after_dropna`
4. Se `parsed_rows` << `raw_rows` → Problema parsing timestamp
5. Se `rows_after_dropna` < 10 → Dati insufficienti

**Come risolvere:**
- Se CSV vuoto: Trigger `/api/force_update` per rigenerare
- Se parsing fail: Verifica formato timestamp in CSV
- Se permission: Fix permessi file `/data/curva_colored.csv`

---

### CAUSA ALTERNATIVA #3: Route shadowing / Blueprint conflict

**Probabilità:** 10%

**Motivazione:**
- Dashboard chiama `/api/curva` ma colpisce route diversa
- Fix PR #500 in route corretta ma request va altrove

**Indicatori:**
- Browser DevTools mostra request a `/api/curva` status 200 ma response HTML
- Non c'è JSON nella response
- Content-Type è `text/html` invece di `application/json`

**Codice di riferimento:**
- `app/__init__.py` linee 47-48: Registrazione blueprint api
  ```python
  from .routes.api import api_bp
  # ...
  app.register_blueprint(api_bp)
  ```

**Possibili sotto-cause:**
- Altro blueprint con route `/api/curva`
- Route precedente nel routing table ha priorità
- Typo nel path: dashboard chiama `/api/curva` ma route è `/api/curve`

**Come verificare:**
1. SSH in produzione (se possibile)
2. Esegui:
   ```bash
   flask routes | grep -i curva
   ```
3. Output atteso:
   ```
   /api/curva  GET  api.get_curva
   ```
4. Se vedi più righe o route diversa → Conflict confermato

**Come risolvere:**
- Rimuovi route duplicata
- Cambia ordine registrazione blueprint in `app/__init__.py`
- Verifica nessun typo in URL

---

### CAUSA ALTERNATIVA #4: Mismatch schema JSON

**Probabilità:** 5%

**Motivazione:**
- Server restituisce JSON corretto ma chiavi diverse
- Dashboard si aspetta `data` ma server restituisce `items`

**Indicatori:**
- Browser DevTools mostra JSON response valido
- Ma dashboard non rende il grafico
- Console JavaScript mostra errore tipo: "Cannot read property 'data' of undefined"

**Codice di riferimento:**
- Server (`app/routes/api.py` linee 252-269):
  ```python
  payload = {
      "ok": True,
      "data": data,  # <-- Chiave "data"
      "last_ts": to_iso_utc(last_ts),
      ...
  }
  ```

- Dashboard (`app/static/js/dashboard.js` linee 613-614):
  ```javascript
  if (data.ok && data.data) {  // <-- Si aspetta "data"
      this.plotData = data;
      this.renderPlot(data);
  }
  ```

**Come verificare:**
1. Apri DevTools → Network → `/api/curva`
2. Guarda Response JSON
3. Confronta chiavi con sezione B di questo documento
4. Se chiavi diverse → Mismatch confermato

**Come risolvere:**
- Update server per usare chiavi corrette (sezione B)
- Oppure update dashboard.js per leggere chiavi attuali

---

## RIEPILOGO AZIONI IMMEDIATE

1. **Prima cosa:** Verifica deployment con Metodo 1 sezione C (test 401)
   - Se 401 ritorna HTML → Deploy vecchio, trigger new deploy
   - Se 401 ritorna JSON → Deploy nuovo, procedi

2. **Se deploy è nuovo:** Test manuali sezione A
   - Punto 2: `/api/curva` default
   - Punto 6: Check DevTools Network tab

3. **Se vedi ok:false:** Segui decision tree sezione D per reason specifico

4. **Se vedi 500:** Check log per exception details

5. **Se vedi HTML:** Check route shadowing (sezione D + E causa #3)

---

## FILE DI RIFERIMENTO CRITICI

### Server-side:
- **`app/routes/api.py`** (linee 114-290): Endpoint `/api/curva` e `/api/status`
- **`app/services/tremor_summary.py`** (linee 36-68): Funzione `load_tremor_dataframe`
- **`app/utils/config.py`**: Funzione `get_curva_csv_path()` 

### Client-side:
- **`app/static/js/dashboard.js`** (linee 528-625): 
  - `fetchDashboardJson()` (528-555)
  - `loadData()` (603-625)
  - `handleDashboardError()` (586-601)

### Config/Deploy:
- **`app/__init__.py`** (linee 35-54): Registrazione blueprint
- **`app.py`** (linee 1-36): Bootstrap applicazione
- **`render.yaml`**: Config deploy Render

---

**Fine documento di debug**
