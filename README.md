# EtnaMonitor 3.x – Sprint 1

**Obiettivo:** base solida per agent che completi il progetto.

## Funzioni previste
- Ingestion PNG INGV → estrazione curva → CSV
- Grafico Plotly con asse Y log (10⁻¹, 10⁰, 10¹) + soglia rossa
- Account Free/Premium, collegamento chat_id Telegram, log eventi
- Bot Telegram: invio alert **solo** Premium quando media ultimi X punti > soglia utente
- Admin panel con toggle Premium e gestione utenti

## Avvio locale
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make dev  # http://127.0.0.1:5000
```

### Configurazione Google OAuth
1. Vai su [Google Cloud Console](https://console.cloud.google.com/) e crea un progetto oppure selezionane uno esistente.
2. Abilita la schermata di consenso OAuth (tipo "App interna" per sviluppo) e aggiungi almeno l'indirizzo email dell'amministratore per ricevere notifiche.
3. Crea credenziali di tipo **ID client OAuth 2.0** → **Applicazione web** e configura gli URI autorizzati:
   - Origine JavaScript: `http://127.0.0.1:5000`
   - URI di reindirizzamento: `http://127.0.0.1:5000/auth/callback`
4. Copia **Client ID** e **Client secret** nelle variabili d'ambiente `.env`:
   ```env
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   ADMIN_EMAIL=admin@example.com  # usato per bootstrap degli utenti admin
   ```
5. Riavvia il server di sviluppo per applicare le credenziali. In produzione ricordati di aggiungere anche i domini/redirect definitivi nella console Google.

## Test
```bash
make test
```

## Accettazione (per gli Agents)
- Tutti i test `tests/` verdi in CI.
- PR incrementali e descritti, senza segreti in chiaro.

## TODO per l'Agent
- Implementare estrazione curva reale (HSV) in `ingestion/extract_curve.py`.
- Integrare grafico Plotly in `dashboard.html` con dati reali.
- Aggiungere persistenza utenti (hash password, niente admin hardcoded).
- Integrare Telegram reale in `alerts/notifier.py`.
- Autorizzazione Admin + UI/UX rifinita dark.
