# DIAGNOSI RAPIDA - Bug Dashboard EtnaMonitor

## 🔴 SINTOMO
Dashboard utente: il KPI "Tremore" mostra valore (es. 1.98 mV), ma:
- **TREND**: resta "--"
- **ULTIMO AGGIORNAMENTO**: resta "-"  
- **Preview grafico**: mostra "Errore nel caricamento dati"

## 🎯 CAUSA PRINCIPALE (80% probabilità)

**`/api/curva` ritorna HTML redirect invece di JSON**

### Perché succede questo?
Due chiamate API separate nella dashboard:
1. ✅ `/api/status` → popola KPI tremore → **FUNZIONA**
2. ✗ `/api/curva` → popola trend, update, grafico → **FALLISCE**

Quando `/api/curva` fallisce (redirect HTML, sessione scaduta, CORS), il frontend non riesce a parsare la risposta come JSON.

## 🔍 VERIFICA IMMEDIATA (30 secondi)

### Opzione 1: Browser DevTools
```
1. Apri dashboard autenticato
2. F12 → Network tab
3. Ricarica pagina
4. Trova richiesta: /api/curva
5. Controlla:
   - Status: 200 o 302?
   - Content-Type: application/json o text/html?
   - Response Preview: JSON o HTML?
```

**Se vedi HTML → causa confermata**

### Opzione 2: Curl rapido
```bash
curl -v https://etnamonitor.com/api/curva?limit=10 \
  -H "Accept: application/json" \
  | head -50
```

**Se output inizia con `<!DOCTYPE html>` → causa confermata**

## 📋 CONTRATTI API (aspettati)

### `/api/curva` (dovrebbe ritornare)
```json
{
  "ok": true,
  "data": [
    {"timestamp": "2026-02-03T12:00:00Z", "value": 1.98},
    {"timestamp": "2026-02-03T11:00:00Z", "value": 1.85}
  ],
  "last_ts": "2026-02-03T12:00:00Z",
  "rows": 2,
  "updated_at": "2026-02-03T12:10:00Z"
}
```

### `/api/status` (già funzionante)
```json
{
  "ok": true,
  "current_value": 1.98,
  "last_update": "2026-02-03T12:00:00Z",
  "threshold": 2.0
}
```

## 🔧 CAUSE ALTERNATIVE

### Causa #2: CSV timestamp corrotti (15%)
**Test rapido**:
```bash
head -5 /path/to/curva.csv
```
Verifica formato timestamp: deve essere `2026-02-03T12:00:00Z`

**Sintomo**: `/api/curva` ritorna `{"ok": false, "reason": "empty_data"}`

### Causa #3: Conflitto blueprints (5%)
Due `/api/status` registrati:
- `app/routes/api.py`
- `app/routes/status.py`

Poco probabile perché payload compatibili.

## 🚀 AZIONI IMMEDIATE

### Per sviluppatore:
1. Verifica response `/api/curva` (DevTools o curl)
2. Se HTML redirect:
   - Check middleware sessione
   - Verifica route non richiede auth impropriamente
   - Controlla nginx/proxy config
3. Se JSON con `ok: false`:
   - Verifica formato timestamp CSV
   - Controlla logs Flask: `grep "curva dataset unavailable" /var/log/app.log`

### Per utente finale:
- **Workaround temporaneo**: ricarica pagina dopo login
- Il KPI tremore attuale resta affidabile (usa `/api/status`)

## 📄 DETTAGLI COMPLETI

Report diagnostico completo con 12 check manuali: `DASHBOARD_DIAGNOSTIC_REPORT.md`

---

**Data analisi**: 2026-02-03  
**Task**: SOLO DIAGNOSI (nessuna modifica codice)
