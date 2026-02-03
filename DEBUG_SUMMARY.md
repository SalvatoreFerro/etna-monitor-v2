# DEBUG SUMMARY - Quick Reference

**Per la guida completa:** Vedi `DEBUG_GUIDE.md`

---

## QUICK DIAGNOSTIC (2 minuti)

### Test 1: Verifica versione deployment
```bash
# Da browser NON autenticato:
curl -i https://[domain]/api/curva
```

**Risultato atteso (versione nuova):**
```
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{"ok": false, "error": "unauthorized"}
```

**Se ottieni redirect HTML (302) → DEPLOY VECCHIO** ⚠️

---

### Test 2: Verifica funzionamento endpoint (autenticato)
```bash
# Da browser autenticato o con cookie:
curl -i https://[domain]/api/curva?limit=50
```

**Risultato atteso (OK):**
```json
{
  "ok": true,
  "data": [...],
  "rows": 50,
  ...
}
```

**Risultato atteso (Dati insufficienti):**
```json
{
  "ok": false,
  "error": "Insufficient valid data",
  "reason": "insufficient_valid_data",
  "rows": 0
}
```

---

## CAUSA PIÙ PROBABILE (60% probabilità)

### ❌ Deploy non aggiornato - Produzione serve vecchia versione

**Evidenza:**
- Test 1 restituisce redirect HTML invece di JSON 401
- Header `X-Csv-Path-Used` assente per admin
- Log non mostrano riga `[API] curva csv stats`

**Soluzione:**
1. Vai su Render dashboard
2. Trigger manual deploy
3. Aspetta 3-5 minuti
4. Riprova test 1 e 2

---

## CAUSE ALTERNATIVE

### ⚠️ CSV ha dati insufficienti (25% probabilità)

**Evidenza:**
- Test 2 restituisce `ok: false` con `reason: "insufficient_valid_data"`
- Log mostra `rows < 10`

**Soluzione:**
```bash
# Trigger force update
curl -X POST https://[domain]/api/force_update
```

---

### ⚠️ Route shadowing (10% probabilità)

**Evidenza:**
- Test 2 restituisce HTML invece di JSON
- Content-Type è `text/html`

**Diagnosi:**
```bash
flask routes | grep curva
# Deve mostrare solo: /api/curva  GET  api.get_curva
```

---

### ⚠️ Mismatch schema JSON (5% probabilità)

**Evidenza:**
- Test 2 restituisce JSON valido MA dashboard non rende
- Console JS mostra errore "Cannot read property 'data'"

**Diagnosi:**
Controlla chiavi JSON response vs sezione B in `DEBUG_GUIDE.md`

---

## FILE CRITICI DA VERIFICARE

### Server (Python):
- `app/routes/api.py` → linee 114-290 (endpoint `/api/curva`)
- `app/services/tremor_summary.py` → linee 36-68 (parsing CSV)

### Client (JavaScript):
- `app/static/js/dashboard.js` → linee 603-625 (loadData)
- `app/static/js/dashboard.js` → linee 528-555 (fetchDashboardJson)

---

## LOG PATTERNS DA CERCARE

### ✅ Versione nuova attiva:
```
[API] curva csv stats path=/data/curva_colored.csv raw_rows=2500 parsed_rows=2500 rows_after_dropna=2500
```

### ❌ Dati insufficienti:
```
[API] curva dataset insufficient reason=insufficient_valid_data path=/data/curva_colored.csv rows=5
```

### ❌ Errore parsing timestamp:
```
[API] curva invalid timestamps samples=['2026-02-03 14:30:00', ...]
```

### ❌ CSV non trovato:
```
[API] Failed to read curva.csv
FileNotFoundError: [Errno 2] No such file or directory: '/data/curva_colored.csv'
```

---

## CONTACT INFO

**Codice sorgente:** `app/routes/api.py` (get_curva, linee 114-290)  
**Dashboard JS:** `app/static/js/dashboard.js` (loadData, linee 603-625)  
**Commit fix:** PR #500 "Fix robustness of /api/curva endpoint"

**Per dettagli completi:** Vedi `DEBUG_GUIDE.md` (811 righe, 5 sezioni A-E)
