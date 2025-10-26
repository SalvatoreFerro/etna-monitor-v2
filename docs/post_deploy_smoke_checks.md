# Post-deploy smoke checklist

Esegui queste query direttamente sul database Postgres (ad es. via `psql`) subito dopo il deploy per confermare che lo schema e i flussi OAuth siano corretti.

## 1. Schema utenti

```sql
SELECT column_name,
       data_type,
       column_default,
       is_nullable
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND table_name = 'users'
   AND column_name IN ('free_alert_consumed', 'alert_count_30d', 'plan_type', 'is_admin');
```

Conferma che:
- `free_alert_consumed` e `alert_count_30d` siano `integer`, `NOT NULL`, `DEFAULT 0`.
- `plan_type` sia `character varying` (20) `NOT NULL DEFAULT 'free'`.
- `is_admin` sia `boolean NOT NULL DEFAULT false`.

## 2. Coercizione valori legacy

```sql
SELECT free_alert_consumed, alert_count_30d
  FROM users
 WHERE free_alert_consumed NOT BETWEEN 0 AND 100
    OR alert_count_30d NOT BETWEEN 0 AND 500;
```

Il risultato deve essere vuoto; in caso contrario, investigare gli utenti con valori anomali.

## 3. Nuova registrazione Google (DB vuoto)

Dopo un login Google appena effettuato:

```sql
SELECT email,
       plan_type,
       free_alert_consumed,
       alert_count_30d,
       subscription_status,
       created_at AT TIME ZONE 'UTC' AS created_at_utc
  FROM users
 ORDER BY created_at DESC
 LIMIT 1;
```

Dovresti vedere `plan_type = 'free'`, entrambi i contatori a `0` e `subscription_status = 'free'`.

## 4. Collegamento Google ad utente esistente

Dopo aver fatto login con Google per un utente già presente (registrato via email/password):

```sql
SELECT email,
       google_id,
       is_admin,
       plan_type,
       free_alert_consumed
  FROM users
 WHERE email = lower('indirizzo@email.esistente');
```

Conferma che `google_id` ora è valorizzato, `is_admin` non è cambiato e i contatori restano numerici.

## 5. Verifica sponsor/partners opzionali

```sql
SELECT COUNT(*) FROM partners;
SELECT COUNT(*) FROM sponsor_banners;
```

Devono restituire `0` su ambienti senza dati senza generare errori.
