# RISPOSTA AL DEBUG GUIDATO

**Richiesta:** Debug guidato (solo analisi, NON cambiare codice) per "Errore nel caricamento dati"  
**Data:** 2026-02-03  
**Commit analizzati:** PR #500 "Fix robustness of /api/curva endpoint"

---

## A) PRODUCTION VERIFICATION CHECKLIST ✓

### Checklist da browser (iPhone/Desktop) - 10 minuti max

**Test 1: `/api/status`**
```
URL: https://[your-domain]/api/status
```
- Aspettati: status 200, JSON con `{"ok": true, "current_value": ..., "last_update": "..."}`
- Se HTML o 401 → problema autenticazione
- Se 500 → problema CSV path

---

**Test 2: `/api/curva` (default)**
```
URL: https://[your-domain]/api/curva
```
- Aspettati: status 200, JSON con `{"ok": true, "data": [...], "rows": 2016}`
- Se `ok: false` → guarda campo `"reason"` (vedi sezione D)
- Se HTML → redirect login (vecchia versione) o route shadowing
- Se 401 JSON → versione nuova attiva, ma sessione scaduta
- Se 500 → CSV non accessibile/parsing error

---

**Test 3: `/api/curva?limit=50`**
```
URL: https://[your-domain]/api/curva?limit=50
```
- Aspettati: stesso schema, ma `"rows": 50` circa
- Testa che parametro limit funzioni

---

**Test 4: `/api/curva?limit=2016`**
```
URL: https://[your-domain]/api/curva?limit=2016
```
- Aspettati: stesso schema, `"rows": 2016` circa
- Questo è il default che usa dashboard

---

**Test 5: Verifica autenticazione (CRITICO per diagnosi deploy)**
```
1. Fai logout completo
2. Apri: https://[your-domain]/api/curva
```
- ✅ **Se ricevi:** status 401 + JSON `{"ok": false, "error": "unauthorized"}` → **FIX PR #500 ATTIVO**
- ❌ **Se ricevi:** redirect HTML 302 → **VECCHIA VERSIONE** (deploy non aggiornato)

**Perché questo test è CRITICO:**
Il fix PR #500 ha cambiato il comportamento 401 da redirect HTML a JSON.
Se vedi ancora redirect HTML → produzione NON serve la versione nuova.

---

**Test 6: Browser DevTools (per debug avanzato)**
```
1. Apri dashboard autenticato
2. F12 → tab Network
3. Ricarica pagina
4. Filtra per "curva"
5. Clicca sulla richiesta /api/curva
```

**Cosa guardare:**
- **Status:** 200? 401? 500?
- **Response Headers → Content-Type:** `application/json` o `text/html`?
- **Response Preview:** vedi JSON o HTML?
- **Response → JSON tab:** guarda campo `ok`, `error`, `reason`

**Interpretazione:**
- Status 200 + JSON `ok:true` → Tutto OK, problema altrove
- Status 200 + JSON `ok:false` → Dati insufficienti (vedi reason)
- Status 401 → Sessione scaduta
- Status 500 → CSV path/parsing/permessi
- Status 200 + HTML → Route shadowing o errore Flask restituisce HTML

---

## B) EXPECTED PAYLOAD SCHEMA ✓

### `/api/curva` - Successo (ok: true)

```json
{
  "ok": true,
  "data": [
    {
      "timestamp": "2026-02-03T10:00:00.000000Z",
      "value": 1.234
    },
    {
      "timestamp": "2026-02-03T10:05:00.000000Z",
      "value": 1.456
    }
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

**Chiavi OBBLIGATORIE per dashboard.js:**
- `ok` (boolean)
- `data` (array di oggetti con `timestamp` e `value`) - solo se `ok: true`
- `last_ts` (string ISO timestamp)
- `rows` (number)

**Chiavi opzionali:**
- `updated_at`, `detected_today`, `is_stale` - info temporali
- `csv_mtime_utc` - timestamp modifica file
- `source` - "file" o "fallback"
- `warning` - problemi non fatali
- `csv_path_used` - solo per admin

---

### `/api/curva` - Errore (ok: false)

```json
{
  "ok": false,
  "error": "Insufficient valid data",
  "reason": "missing_timestamp",
  "rows": 0
}
```

**Possibili valori di `reason`:**
- `"missing_timestamp"` - CSV senza colonna timestamp
- `"empty_data"` - CSV vuoto o tutti timestamp invalidi
- `"insufficient_valid_data"` - Meno di 10 righe valide
- `"empty_after_limit"` - Dataset vuoto dopo tail(limit)

---

### `/api/curva` - Non autenticato (401)

```json
{
  "ok": false,
  "error": "unauthorized"
}
```

**Status code:** 401  
**Content-Type:** `application/json`

**NOTA IMPORTANTE:** Questo è il comportamento nuovo del fix PR #500.
Se invece ricevi redirect HTML → vecchia versione in produzione.

---

### `/api/curva` - Errore server (500)

```json
{
  "ok": false,
  "error": "FileNotFoundError: No such file or directory: '/data/curva_colored.csv'"
}
```

**Status code:** 500  
**Content-Type:** `application/json`

---

### `/api/status` - Successo

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

**Chiavi OBBLIGATORIE per dashboard.js:**
- `ok` (boolean)
- `current_value` (number)
- `above_threshold` (boolean)
- `last_update` (string ISO timestamp)

---

## C) HOW TO CONFIRM DEPLOYED COMMIT ✓

### Metodo 1: Test 401 behavior (CHEAP, no code change, RACCOMANDATO)

**Procedura:**
1. Fai logout completo
2. Apri DevTools → Network tab
3. Vai a `https://[domain]/api/curva`
4. Guarda Status Code e Content-Type

**Interpretazione:**
- ✅ Status 401 + JSON `{"ok": false, "error": "unauthorized"}` → **FIX PR #500 ATTIVO**
- ❌ Status 302 o HTML redirect → **VECCHIA VERSIONE**

**Perché funziona:**
Il fix PR #500 ha modificato il comportamento da redirect HTML a JSON 401.

**Codice di riferimento:**
File: `app/routes/api.py`, linee 115-119
```python
@api_bp.get("/api/curva")
def get_curva():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
```

---

### Metodo 2: Check log structure (CHEAP, no code change, serve accesso log)

**Se hai accesso ai log di produzione**, cerca questa riga:

```
[API] curva csv stats path=/data/curva_colored.csv raw_rows=2500 parsed_rows=2500 rows_after_dropna=2500
```

**Interpretazione:**
- ✅ Log presente → Fix PR #500 attivo
- ❌ Log assente → Vecchia versione

**Codice di riferimento:**
File: `app/routes/api.py`, linee 153-159
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

### Metodo 3: Check response headers (CHEAP, serve login come admin)

**Se sei autenticato come admin**, la risposta include:

**Response Headers:**
```
X-Csv-Path-Used: /data/curva_colored.csv
X-Csv-Last-Ts: 2026-02-03T14:30:00.000000Z
```

**Interpretazione:**
- ✅ Header presenti → Fix PR #500 attivo
- ❌ Header assenti → Vecchia versione

**Codice di riferimento:**
File: `app/routes/api.py`, linee 276-277
```python
if include_csv_path:
    response.headers["X-Csv-Path-Used"] = str(csv_path)
    response.headers["X-Csv-Last-Ts"] = payload.get("last_ts") or ""
```

---

### Metodo 4: Aggiunta endpoint /api/version (SE necessario, 1 modifica minimale)

**Se metodi 1-3 non bastano**, aggiungi questo endpoint:

**File:** `app/routes/api.py` (aggiungi alla fine prima della chiusura)

```python
@api_bp.get("/api/version")
def get_version():
    """Return deployment version info"""
    import os
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

**NOTA:** Render.com espone automaticamente queste env vars. Zero setup richiesto.

---

### Metodo 5: Check presenza funzione nel codice sorgente

**Nel file sorgente produzione**, cerca:

```python
def _prepare_tremor_dataframe(raw_df: pd.DataFrame) -> tuple[pd.DataFrame, str | None, dict]:
```

**Se funzione esiste:** Fix PR #500 attivo  
**Se assente:** Vecchia versione

**Codice di riferimento:**
File: `app/routes/api.py`, linee 81-111

---

## D) IF/THEN DECISION TREE ✓

### Se `/api/curva` restituisce 401

**Significa:**
- Utente non autenticato
- Sessione scaduta
- Cookie non inviato

**Possibili cause:**
1. Logout in altra tab
2. Sessione Flask scaduta (default: 31 giorni)
3. Cookie SameSite/Secure issue
4. Browser blocca cookie terze parti
5. CORS issue (se frontend/backend su domini diversi)

**Azione:**
1. Fai login
2. Verifica cookie `session` in DevTools → Application → Cookies
3. Riprova `/api/curva`
4. Se ancora 401 → controlla `fetchDashboardJson` include `credentials: 'include'` (file: `app/static/js/dashboard.js`, linee 528-537)

---

### Se `/api/curva` restituisce 200 ma ok: false

**Significa:**
- Endpoint funziona
- CSV ha problemi

**Controlla campo `"reason"`:**

#### reason: "missing_timestamp"
- CSV senza colonna timestamp
- Controlla formato: deve avere header `timestamp,value`
- File: `app/routes/api.py` linee 89-90

#### reason: "empty_data"
- CSV vuoto o tutti timestamp invalidi
- Guarda log per: `[API] curva invalid timestamps samples=...`
- File: `app/routes/api.py` linee 108-109

#### reason: "insufficient_valid_data"
- Meno di 10 righe valide dopo parsing
- Guarda log per: `[API] curva dataset insufficient... rows=X`
- CSV troppo piccolo o dati corrotti
- File: `app/routes/api.py` linee 185-200

#### reason: "empty_after_limit"
- Dopo `df.tail(limit)`, dataset vuoto
- CSV ha meno righe di `limit` richiesto
- File: `app/routes/api.py` linee 225-240

---

### Se `/api/curva` restituisce 500

**Significa:**
- Exception non gestita
- CSV path inaccessibile
- Permessi insufficienti
- pandas.read_csv fallisce

**Controlla campo `"error"`:**

#### error: "FileNotFoundError"
- CSV path non esiste
- Controlla env var: `CURVA_CSV_PATH` o `CSV_PATH`
- Default: `/data/curva_colored.csv`
- Verifica directory `/data` esiste

#### error: "PermissionError"
- CSV esiste ma no permessi lettura
- Fix: `chmod 644 /data/curva_colored.csv`

#### error: "ParserError"
- CSV malformato
- Verifica encoding UTF-8
- Nessuna riga con numero colonne diverso

---

### Se `/api/curva` restituisce 200 ma JSON con chiavi diverse

**Significa:**
- Schema JSON diverso da atteso
- Dashboard si aspetta `data`, server restituisce altra chiave

**Azione:**
1. Confronta JSON con sezione B
2. Controlla `app/routes/api.py` linee 252-269 (costruzione payload)
3. Controlla `app/static/js/dashboard.js` linee 603-624 (parsing response)

---

### Se `/api/curva` restituisce HTML invece di JSON

**Significa:**
- Request colpisce route diversa
- Flask restituisce pagina errore HTML
- Redirect a login (vecchia versione)

**Possibile causa:** Route shadowing

**Azione:**
1. Esegui (se hai SSH): `flask routes | grep curva`
2. Output atteso: `/api/curva  GET  api.get_curva`
3. Se più righe → route duplicata
4. Controlla `app/__init__.py` per ordine blueprint (linee 35-54)

---

## E) MOST LIKELY ROOT CAUSE ✓

### 🎯 CAUSA PIÙ PROBABILE: Deploy non serve ultima versione (60% probabilità)

**Evidenze:**
1. `/api/status` funziona → Server UP, database accessibile
2. Dashboard mostra errore identico pre/post-fix → Comportamento non cambiato
3. PR #500 appena mergiato → Deploy potrebbe non essere completato

**Test per confermare:**
- Test 401 senza login restituisce HTML redirect invece di JSON → DEPLOY VECCHIO
- Log non mostrano riga `[API] curva csv stats` → DEPLOY VECCHIO
- Header `X-Csv-Path-Used` assente per admin → DEPLOY VECCHIO

**Codice di riferimento:**
File: `app/routes/api.py`, linee 115-119
```python
user = get_current_user()
if not user:
    return jsonify({"ok": False, "error": "unauthorized"}), 401
```

**Possibili sotto-cause:**
- Build cache: Render usa file cached
- Branch sbagliato: Deploy da branch diverso
- Deploy pending: Render non ha completato deploy
- Env var: `RENDER_GIT_COMMIT` non aggiornato

**Come verificare:**
1. Vai su Render dashboard
2. Controlla "Latest Deploy" timestamp
3. Confronta con timestamp merge PR #500
4. Se deploy precedente a merge → Deploy non aggiornato

**Come risolvere:**
1. Trigger manual deploy da Render
2. Clear build cache se disponibile
3. Verifica branch corretto
4. Aspetta 3-5 minuti
5. Riprova test sezione A

---

### CAUSA ALTERNATIVA #2: /api/curva ok:false per dati insufficienti (25% probabilità)

**Evidenze:**
- Deploy aggiornato MA CSV ha problemi reali
- `/api/status` funziona (usa parsing diverso)
- `/api/curva` più strict con nuovo fix

**Test per confermare:**
- Test manuale restituisce JSON `ok: false`
- Campo `reason` presente
- Log: `[API] curva dataset insufficient... rows=X` con X < 10

**Codice di riferimento:**
File: `app/routes/api.py`, linee 81-111 (`_prepare_tremor_dataframe`)
File: `app/routes/api.py`, linee 185-200 (check minimum 10 rows)

**Possibili sotto-cause:**
- CSV path sbagliato
- CSV corrotto
- Timestamp parsing fail
- Permission issue

**Come risolvere:**
- CSV vuoto: trigger `/api/force_update`
- Parsing fail: verifica formato timestamp
- Permission: `chmod 644 /data/curva_colored.csv`

---

### CAUSA ALTERNATIVA #3: Route shadowing (10% probabilità)

**Evidenze:**
- Dashboard chiama `/api/curva` ma colpisce route diversa
- Browser DevTools mostra status 200 MA response HTML
- Content-Type è `text/html`

**Test per confermare:**
```bash
flask routes | grep curva
# Atteso: /api/curva  GET  api.get_curva
# Se più righe → conflict
```

**Codice di riferimento:**
File: `app/__init__.py`, linee 47-48 (registrazione blueprint)

---

### CAUSA ALTERNATIVA #4: Mismatch schema JSON (5% probabilità)

**Evidenze:**
- JSON valido MA chiavi diverse
- Dashboard non rende grafico
- Console JS: "Cannot read property 'data'"

**Test per confermare:**
- DevTools mostra JSON response valido
- Ma chiavi diverse da sezione B

**Codice di riferimento:**
- Server: `app/routes/api.py` linee 252-269
- Client: `app/static/js/dashboard.js` linee 613-614

---

## RIEPILOGO AZIONI IMMEDIATE

1. **PRIMA COSA:** Verifica deployment (sezione C, Metodo 1)
   - Test `/api/curva` senza auth
   - Se HTML redirect → DEPLOY VECCHIO → Trigger new deploy
   - Se JSON 401 → DEPLOY NUOVO → Procedi

2. **SE DEPLOY NUOVO:** Test manuali (sezione A)
   - Test 2: `/api/curva` default
   - Test 6: DevTools Network tab

3. **SE ok:false:** Decision tree (sezione D) per reason specifico

4. **SE 500:** Check log per exception details

5. **SE HTML:** Check route shadowing

---

## FILE CRITICI

### Server (Python):
- `app/routes/api.py` (linee 114-290) → Endpoint `/api/curva` e `/api/status`
- `app/services/tremor_summary.py` (linee 36-68) → Parsing CSV
- `app/utils/config.py` → `get_curva_csv_path()`

### Client (JavaScript):
- `app/static/js/dashboard.js` (linee 528-625) → fetch e loadData

### Config:
- `app/__init__.py` (linee 35-54) → Blueprint registration

---

**FINE ANALISI - NO CODE CHANGES (come richiesto)**
