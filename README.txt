# Etna Monitor - Versione Locale

## Come usare

1. Installa le dipendenze:
   pip install flask numpy pandas matplotlib opencv-python requests

2. Esegui `etna.py` per scaricare e processare il grafico.

3. Esegui `app.py` per avviare il sito web:
   python app.py

4. Visita: http://127.0.0.1:5000

## Struttura:
- `grafici/` → contiene l'ultima immagine PNG
- `log/log.csv` → contiene i dati delle ultime 48h
- `static/plot.png` → grafico generato
