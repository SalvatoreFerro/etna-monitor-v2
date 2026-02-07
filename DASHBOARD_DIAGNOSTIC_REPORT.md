# REPORT DIAGNOSTICO: Bug Dashboard EtnaMonitor - KPI Tremore

**Data analisi**: 2026-02-03  
**Componente**: Dashboard utente (`/dashboard/`)  
**Sintomo**: KPI "Tremore" si popola (es. 1.98 mV), ma TREND resta "--", ULTIMO AGGIORNAMENTO resta "-", e Preview grafico mostra "Errore nel caricamento dati"

---

## A) MAPPA DATI DASHBOARD

Tabella completa dei dati visualizzati nella dashboard con mapping frontend-backend:

| UI Elemento | File JS | Funzione | Endpoint chiamato | Payload atteso (chiavi) | Fonte dati lato server (CSV/DB) | Note |
|-------------|---------|----------|-------------------|-------------------------|----------------------------------|------|
| **Tremore attuale** (`#current-value`) | `app/static/js/dashboard.js` | `updateStatus()` (riga 973) | `/api/status` | `{ok, current_value, last_update, threshold}` | `curva.csv` via `get_curva_csv_path()` | Popolato da `/api/status` |
| **Ultimo aggiornamento** (`#last-updated`) | `app/static/js/dashboard.js` | `updateStats()` (riga 924) | `/api/curva` | `{ok, data[], last_ts, updated_at, is_stale}` | `curva.csv` via `get_curva_csv_path()` | Popolato da `/api/curva` |
| **Trend** (`#trend-status`) | `app/static/js/dashboard.js` | `updateStats()` (riga 940-970) | `/api/curva` | `{ok, data[{value}]}` | `curva.csv` via `get_curva_csv_path()` | Calcolato in frontend da array data |
| **Grafico preview** (`#tremor-plot`) | `app/static/js/dashboard.js` | `renderPlot()` (riga 677) | `/api/curva?limit=2016` | `{ok, data[{timestamp, value}]}` | `curva.csv` via `get_curva_csv_path()` | Plotly.js rendering |
| **Soglia attiva** (`#active-threshold`) | `app/static/js/dashboard.js` | `updateActiveThresholdDisplay()` (riga 411) | N/A (server-rendered) | N/A | `data-threshold` attribute da template | Valore iniziale da Jinja2 |
| **Stato indicator** (`#status-indicator`) | `app/static/js/dashboard.js` | `updateStatus()` (riga 982-1007) | `/api/status` | `{ok, current_value, above_threshold}` | `curva.csv` via `get_curva_csv_path()` | Status classes dinamici |
| **Campioni disponibili** (`#data-points`) | `app/static/js/dashboard.js` | `updateStats()` (riga 936) | `/api/curva` | `{ok, data[], rows}` | `curva.csv` via `get_curva_csv_path()` | Conta array data.length |

---

## B) CONTRATTI API

### 1. `/api/curva` (GET)
**File**: `app/routes/api.py`, funzione `get_curva()` (riga 100)

**Auth richiesto**: NO (pubblico, ma mostra path solo ad admin/owner)

**Parametri query**:
- `limit` (int, opzionale): numero di righe da restituire (default: 2016, min: 1, max: 4032)
- `range` (string, opzionale): alias per limit ("24h"=288, "3d"=864, "7d"=2016, "14d"=4032)

**Response JSON (success)**:
```json
{
  "ok": true,
  "data": [
    {"timestamp": "2026-02-03T12:00:00Z", "value": 1.98, "value_avg": 1.95, ...},
    ...
  ],
  "last_ts": "2026-02-03T13:00:00Z",
  "rows": 2016,
  "csv_mtime_utc": "2026-02-03T13:10:00Z",
  "source": "file",
  "updated_at": "2026-02-03T13:10:00Z",
  "detected_today": "2026-02-03",
  "is_stale": false
}
```

**Response JSON (error - dataset vuoto)**:
```json
{
  "ok": false,
  "reason": "missing_timestamp" | "empty_data",
  "rows": 0
}
```

**Response JSON (error - exception)**:
```json
{
  "ok": false,
  "error": "message di errore"
}
```
**HTTP Status codes**:
- 200: success (anche con ok: false per dati mancanti)
- 400: invalid_limit
- 500: exception durante lettura CSV

**Edge cases**:
1. **CSV mancante o vuoto**: tenta auto-generazione da INGV_COLORED_URL (riga 116-130)
2. **Colonna timestamp mancante**: ritorna `{ok: false, reason: "missing_timestamp"}`
3. **DataFrame vuoto dopo parsing**: ritorna `{ok: false, reason: "empty_data"}`
4. **Cache headers**: `Cache-Control: no-store, no-cache` (riga 209-211)

---

### 2. `/api/status` (GET)
**File**: `app/routes/api.py`, funzione `get_status()` (riga 229)

**Auth richiesto**: NO (pubblico)

**Parametri query**:
- `track` (string, opzionale): nome evento da loggare
- `location` (string, opzionale): location per tracking

**Response JSON (success)**:
```json
{
  "ok": true,
  "current_value": 1.98,
  "above_threshold": false,
  "threshold": 2.0,
  "last_update": "2026-02-03T13:00:00Z",
  "updated_at": "2026-02-03T13:00:00Z",
  "detected_today": "2026-02-03",
  "is_stale": false,
  "total_points": 2016
}
```

**Response JSON (error - dataset mancante)**:
```json
{
  "ok": false,
  "reason": "missing_timestamp" | "empty_data",
  "current_value": null,
  "above_threshold": false,
  "threshold": 2.0,
  "last_update": null,
  "total_points": 0
}
```

**Response JSON (exception)**:
```json
{
  "ok": false,
  "error": "message"
}
```

**HTTP Status codes**:
- 200: success (anche con ok: false)
- 500: exception

**Edge cases**:
1. **CSV non esiste**: ritorna current_value=0.0, last_update=null con ok: true (riga 285-292)
2. **CSV vuoto dopo parsing**: ritorna ok: false con reason
3. **Threshold**: letto da env `ALERT_THRESHOLD_DEFAULT` (default: 2.0)

---

### 3. **ENDPOINT ALTERNATIVO**: `/api/status` (route duplicata)
**File**: `app/routes/status.py`, funzione `get_status()` (riga 12)

⚠️ **ATTENZIONE**: Esiste un SECONDO endpoint `/api/status` definito in un blueprint diverso!

**Response JSON (extended)**:
```json
{
  "ok": true,
  "timestamp": 1738591980.0,
  "uptime_s": 3600,
  "csv_path": "/path/to/curva.csv",
  "threshold": 2.0,
  "build_sha": "abc12345",
  "render_region": "frankfurt",
  "last_ts": "2026-02-03T13:00:00Z",
  "rows": 2016,
  "current_value": 1.98,
  "above_threshold": false,
  "data_age_minutes": 15,
  "updated_at": "2026-02-03T13:00:00Z",
  "detected_today": "2026-02-03",
  "is_stale": false
}
```

**Differenze chiave**:
- Campo `last_update` vs `last_ts` 
- Include metadati diagnostici (uptime_s, csv_path, build_sha)
- Threshold da env `DEFAULT_THRESHOLD` invece di `ALERT_THRESHOLD_DEFAULT`

---

## C) DIAGNOSI

### Perché il KPI tremore può popolarsi mentre preview/trend no?

Il flusso di caricamento dati nella dashboard è **asincrono e separato**:

**1. KPI Tremore attuale (`#current-value`)**
- Popolato da: `loadStatus()` → `/api/status` → `updateStatus()` (riga 523-575)
- Dipendenze: solo `data.current_value`
- Successo se: CSV esiste e contiene almeno 1 valore valido

**2. Trend (`#trend-status`)**
- Popolato da: `loadData()` → `/api/curva` → `updateStats()` → calcolo trend (riga 940-970)
- Dipendenze: `data.data[]` array con almeno 2 valori
- Successo se: `/api/curva` ritorna `{ok: true, data: [...]}` con array popolato
- **Calcolo**: confronta `values[length-1]` vs `values[length-2]` per delta

**3. Ultimo aggiornamento (`#last-updated`)**
- Popolato da: `loadData()` → `/api/curva` → `updateStats()` (riga 929-933)
- Dipendenze: `data.updated_at` o `data.last_ts`
- Successo se: `/api/curva` ritorna campo `updated_at` o `last_ts` valido

**4. Preview grafico (`#tremor-plot`)**
- Popolato da: `loadData()` → `/api/curva` → `renderPlot()` (riga 677)
- Dipendenze: `data.data[]` array con oggetti `{timestamp, value}`
- Successo se: `/api/curva` ritorna `{ok: true, data: [...]}` con array valido
- **Fallisce se**: `data.ok === false` o array vuoto (mostra `showNoDataMessage()`)

### Mismatch tipici identificati:

#### 1. **Chiamate API disgiunte**
```javascript
// riga 523-525: carica dati e status in parallelo ma indipendenti
async loadInitialData() {
    await this.loadData();      // → /api/curva
    await this.loadStatus();    // → /api/status
}
```
Se `/api/curva` fallisce ma `/api/status` ha successo → KPI ok, trend/preview falliti ✅ MATCH

#### 2. **Condizioni diverse per "ok"**
- `/api/status`: può ritornare `ok: true` con `current_value: 0.0` anche se CSV non esiste (riga 285)
- `/api/curva`: ritorna `ok: false` se dataset vuoto (riga 144-151)

#### 3. **Parsing timestamp inconsistente**
`_prepare_tremor_dataframe()` (api.py riga 81-98):
```python
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
df = df.dropna(subset=["timestamp"])
if df.empty:
    return df, "empty_data"
```
Se timestamp non parsabile → DataFrame vuoto → `/api/curva` ritorna `ok: false`
Ma `/api/status` può comunque leggere `value` dall'ultima riga ignorando timestamp invalidi

#### 4. **Redirect HTML al posto di JSON**
Se sessione scaduta o CORS issue:
- Fetch potrebbe ricevere HTML redirect 302 → `/auth/login`
- `response.json()` parse error
- Catch block non gestisce caso specifico (riga 550)
- **Sintomo**: console log "Error loading data" ma nessun messaggio specifico

#### 5. **Cache/Cookie credentials**
```javascript
// riga 531-535
const response = await fetch(`/api/curva?limit=${limit}`, {
    credentials: 'same-origin',  // ← invia cookie solo se same-origin
    cache: 'no-store',
    headers: { 'Accept': 'application/json' }
});
```
Se cookie sessione mancante e API richiede auth (anche se pubbliche):
- Flask potrebbe fare redirect HTML
- Frontend interpreta come errore

#### 6. **Content-Type mismatch**
Se server ritorna HTML invece di JSON:
- `response.ok` può essere `true` (200)
- `await response.json()` lancia exception
- Catch generico (riga 550) → toast "Errore nel caricamento dati"

---

## D) CHECKLIST DI VERIFICA MANUALE

### Check 1: Verificare endpoint API da browser autenticato
```bash
# Apri browser, fai login su dashboard, poi:
https://etnamonitor.com/api/curva?limit=10
https://etnamonitor.com/api/status

# Aspettative:
- Content-Type: application/json
- Status: 200
- Body: JSON valido con ok: true
```

### Check 2: Test endpoint da curl (no auth)
```bash
curl -v https://etnamonitor.com/api/curva?limit=10 \
  -H "Accept: application/json"

# Verificare:
- Status code (200 = ok, 302 = redirect, 401/403 = auth)
- Content-Type header (deve essere application/json)
- Body JSON o HTML redirect?
```

### Check 3: Verificare presenza CSV su server
```bash
# Se hai accesso SSH:
ls -lh /path/to/curva.csv
head -20 /path/to/curva.csv

# Verificare:
- File esiste?
- Dimensione > 0 byte?
- Colonne: timestamp, value
- Timestamp formato ISO 8601 valido?
```

### Check 4: Test parsing timestamp
```python
# Script diagnostico:
import pandas as pd
df = pd.read_csv('/path/to/curva.csv')
print(f"Colonne: {df.columns.tolist()}")
df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
df = df.dropna(subset=['timestamp'])
print(f"Righe valide dopo parsing: {len(df)}")
print(f"Ultima riga: {df.tail(1).to_dict('records')}")
```

### Check 5: Console browser con Network tab aperto
```javascript
// Apri DevTools → Network → Preserve log
// Ricarica dashboard e filtra per "api"

// Verifica per /api/curva e /api/status:
- Status code
- Response headers (Content-Type)
- Response preview (JSON o HTML?)
- Timing (timeout > 30s?)
```

### Check 6: Verificare logs Flask lato server
```bash
# Cerca errori durante chiamate API:
grep -i "error\|exception\|failed" /var/log/app.log | grep -E "api/curva|api/status"

# Pattern tipici:
- "Failed to read curva.csv"
- "curva dataset unavailable reason=..."
- "Status endpoint failed"
```

### Check 7: Test con user non autenticato vs autenticato
```bash
# Incognito window (no cookies):
curl https://etnamonitor.com/api/curva?limit=10

# Con cookie sessione:
curl https://etnamonitor.com/api/curva?limit=10 \
  -H "Cookie: session=xyz..."

# Confronta:
- Stesso response?
- Redirect solo per non autenticato?
```

### Check 8: Verificare conflitto blueprints per /api/status
```python
# Nel codice Flask, verifica quale blueprint registrato per primo:
# app/routes/__init__.py

# Se sia api.py che status.py registrano /api/status:
# → quale viene chiamato? (dipende da ordine registrazione)
```

### Check 9: Test payload minimo per renderPlot
```javascript
// Console browser nella dashboard:
const testData = {
  ok: true,
  data: [
    {timestamp: "2026-02-03T10:00:00Z", value: 1.5},
    {timestamp: "2026-02-03T11:00:00Z", value: 1.8},
    {timestamp: "2026-02-03T12:00:00Z", value: 1.98}
  ],
  last_ts: "2026-02-03T12:00:00Z",
  rows: 3
};

// Prova rendering manuale:
window.dashboard.renderPlot(testData);
window.dashboard.updateStats(testData);

// Se funziona → problema è lato server/API
// Se non funziona → problema è lato frontend/JS
```

### Check 10: Verificare variabili ambiente server
```bash
# Controlla configurazione:
echo $INGV_COLORED_URL
echo $ALERT_THRESHOLD_DEFAULT
echo $DEFAULT_THRESHOLD

# Verificare:
- INGV_COLORED_URL è impostato? (per auto-generazione CSV)
- Threshold coerente tra api.py e status.py?
```

### Check 11: Test scenario CORS/preflight
```bash
# Simula richiesta cross-origin:
curl -v https://etnamonitor.com/api/curva \
  -H "Origin: https://example.com" \
  -H "Accept: application/json"

# Verificare:
- Access-Control-Allow-Origin header?
- Status 200 o 403/500?
```

### Check 12: Monitoring real-time durante load dashboard
```bash
# Terminal 1: tail logs Flask
tail -f /var/log/app.log | grep -i "api"

# Terminal 2: apri dashboard in browser

# Verificare:
- Quante chiamate API logggate? (deve essere 2: /curva e /status)
- Errori CSV read?
- Exception stack traces?
```

---

## E) TOP 3 CAUSE PROBABILI + PROVE

### CAUSA #1: `/api/curva` ritorna HTML redirect invece di JSON (PROBABILITÀ: 80%)

#### Sintomo atteso:
- KPI tremore si popola (da `/api/status` che funziona)
- Trend, ultimo update, preview grafico falliscono (da `/api/curva` che fallisce)
- Console browser: `SyntaxError: Unexpected token '<'` quando parse JSON
- Network tab: `/api/curva` status 200 ma Content-Type: text/html

#### Dove si genera nel codice:
Flask redirect automatico se:
1. Route protetta con `@login_required` (non è il caso, api.py riga 100 è pubblica)
2. Middleware di sessione scaduta
3. WSGI/proxy reverse (es. nginx) fa rewrite errato

#### Come provarlo:
```bash
# 1. Test curl diretto:
curl -v https://etnamonitor.com/api/curva?limit=10 \
  -H "Accept: application/json" \
  | head -50

# Se vedi HTML con <html> o redirect → CONFERMA CAUSA

# 2. Browser DevTools → Network:
# Apri dashboard, trova richiesta /api/curva
# Controlla Response Headers:
#   Content-Type: text/html  ← PROBLEMA
#   Content-Type: application/json  ← OK

# 3. Console browser:
fetch('/api/curva?limit=10')
  .then(r => r.text())
  .then(t => console.log(t.substring(0, 200)))
# Se inizia con <!DOCTYPE html> → CONFERMA
```

#### Fix suggerito (per sviluppatore):
Verificare middleware/route configuration. Assicurare che `/api/*` routes non passino per login redirect.

---

### CAUSA #2: CSV timestamp corrotti, `/api/curva` ritorna `{ok: false, reason: "empty_data"}` (PROBABILITÀ: 15%)

#### Sintomo atteso:
- `/api/status` ha successo: legge ultimo valore ignorando timestamp
- `/api/curva` fallisce: parsing timestamp invalido → DataFrame vuoto
- Frontend: `data.ok === false` → `showNoDataMessage()` chiamato
- Console log: "Dashboard API returned no data" (riga 547)

#### Dove si genera nel codice:
`app/routes/api.py`, funzione `_prepare_tremor_dataframe()` (riga 81-98):
```python
df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
df = df.dropna(subset=["timestamp"])
if df.empty:
    return df, "empty_data"  # ← ritorna ok: false
```

Se CSV ha timestamp non ISO 8601 validi (es. "N/A", epoch senza UTC, formato custom):
- `errors="coerce"` → NaT
- `dropna()` → righe eliminate
- DataFrame vuoto → reason: "empty_data"

#### Come provarlo:
```bash
# 1. Controlla CSV raw:
head -20 /path/to/curva.csv
# Cerca timestamp strani: "2026-02-03 13:00:00" senza 'Z', "1738591980", "N/A"

# 2. Test parsing Python:
python3 << EOF
import pandas as pd
df = pd.read_csv('/path/to/curva.csv')
print("Prime 5 righe:\n", df.head())
df['ts_parsed'] = pd.to_datetime(df['timestamp'], utc=True, errors='coerce')
print("NaT count:", df['ts_parsed'].isna().sum())
print("Valid count:", df['ts_parsed'].notna().sum())
EOF

# 3. Check risposta API:
curl https://etnamonitor.com/api/curva?limit=10 | jq '.ok, .reason'
# Se vedi: false, "empty_data" → CONFERMA CAUSA
```

#### Fix suggerito:
Normalizzare timestamp in CSV generation pipeline. Assicurare formato ISO 8601 con UTC: `2026-02-03T13:00:00Z`

---

### CAUSA #3: Route `/api/status` duplicata, conflitto tra blueprints (PROBABILITÀ: 5%)

#### Sintomo atteso:
- `/api/status` chiamato ritorna payload diverso da atteso
- Campo `last_update` vs `last_ts` inconsistente
- Frontend: `updateStatus()` trova `data.current_value` ma `updateStats()` non trova `data.updated_at`

#### Dove si genera nel codice:
**Due definizioni di `/api/status`**:
1. `app/routes/api.py` (riga 229): ritorna `{current_value, last_update, ...}`
2. `app/routes/status.py` (riga 12): ritorna `{current_value, last_ts, ...}` con extended diagnostics

Flask registra blueprints in ordine. Se `status_bp` registrato dopo `api_bp`:
- `/api/status` può puntare a `status.py` invece di `api.py`
- Payload keys diverse: `last_update` vs `last_ts`
- Frontend `dashboard.js` riga 568 cerca `data.ok` → trova
- Frontend `dashboard.js` riga 929 cerca `data.updated_at` o `data.last_ts` → trova `last_ts` ✓
- **Quindi questa causa è MENO probabile** perché campi sono compatibili

#### Come provarlo:
```bash
# 1. Verifica quale endpoint risponde:
curl https://etnamonitor.com/api/status | jq 'keys'
# Se vedi: ["ok", "timestamp", "uptime_s", "build_sha", ...] → status.py
# Se vedi: ["ok", "current_value", "above_threshold", ...] → api.py

# 2. Check registrazione blueprints:
grep -r "register_blueprint.*status" app/

# 3. Flask routes debug:
flask routes | grep "/api/status"
# Deve mostrare quale funzione serve quella route
```

#### Fix suggerito:
Rinominare uno dei due endpoint o rimuovere duplicato. Consolidare in single source of truth.

---

## CAUSA PIÙ PROBABILE (TOP 1):

**Causa #1: `/api/curva` ritorna HTML redirect (302) invece di JSON**

### Evidenze a supporto:
1. ✅ KPI si popola → `/api/status` funziona (chiamata separata)
2. ✅ Trend/update/preview falliscono → tutti dipendono da `/api/curva`
3. ✅ Fetch credentials: 'same-origin' (riga 532) → se cookie mancante, può triggerare redirect
4. ✅ Catch generico (riga 550) → non distingue tra JSON parse error e network error
5. ✅ Sintomo classico: "Errore nel caricamento dati" ma nessun dettaglio tecnico

### Test definitivo:
```bash
# Browser DevTools → Dashboard → Network tab
# Trova richiesta /api/curva
# Verifica:
- Status: 200 o 302?
- Content-Type: application/json o text/html?
- Response Preview: JSON valido o HTML page?

# Se HTML → causa confermata
# Se JSON con ok: false → causa #2 più probabile
# Se JSON con ok: true ma data vuoto → bug frontend
```

---

## CONCLUSIONI

Il bug è causato da un **flusso asincrono separato** tra due endpoint API:
- `/api/status` (popola KPI tremore) → SUCCESSO
- `/api/curva` (popola trend/update/preview) → FALLIMENTO

La causa più probabile è che `/api/curva` ritorni un **redirect HTML** invece di JSON, oppure che il CSV abbia **timestamp corrotti** che causano DataFrame vuoto dopo parsing.

La verifica più rapida è aprire DevTools Network tab e ispezionare la risposta di `/api/curva` durante il load della dashboard.

---

**Fine report diagnostico**  
**Nessuna modifica al codice effettuata come richiesto**
