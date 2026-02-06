# Architecture Comparison: Current vs. Proposed

## 🔴 CURRENT ARCHITECTURE (BROKEN)

### Data Flow
```
┌─────────────────────────────────────────────────────────────────┐
│                    RENDER PLATFORM (Cloud)                       │
├─────────────────────────┬───────────────────────────────────────┤
│  CRON SERVICE           │  WEB SERVICE                          │
│  (Container B)          │  (Container A)                        │
│  ┌─────────────────┐    │  ┌─────────────────┐                 │
│  │ Hourly Job      │    │  │ Flask App       │                 │
│  │                 │    │  │                 │                 │
│  │ 1. Download PNG │    │  │ 1. User Request │                 │
│  │ 2. Process data │    │  │ 2. Read CSV     │                 │
│  │ 3. Write CSV ❌ │    │  │ 3. Return data  │                 │
│  └────────┬────────┘    │  └────────▲────────┘                 │
│           │             │           │                           │
│           ▼             │           │                           │
│  ┌─────────────────┐    │  ┌─────────────────┐                 │
│  │ Ephemeral FS    │    │  │ Ephemeral FS    │                 │
│  │ /workspace/.../ │    │  │ /workspace/.../ │                 │
│  │ curva_colored.  │    │  │ curva_colored.  │                 │
│  │ csv             │    │  │ csv (OLD!)      │                 │
│  │ ✅ Written      │    │  │ ❌ Not updated  │                 │
│  │ ❌ Lost on      │    │  │ ❌ Stale data   │                 │
│  │    restart      │    │  │                 │                 │
│  └─────────────────┘    │  └─────────────────┘                 │
│           │             │           │                           │
│           ▼             │           │                           │
│    ❌ Container         │    ❌ Reads from                      │
│       restart           │       different                       │
│       → data lost       │       container                       │
└─────────────────────────┴───────────────────────────────────────┘

Problem: NO SHARED STORAGE BETWEEN CONTAINERS!
```

### Issues
1. ❌ Cron writes to Container B's ephemeral filesystem
2. ❌ Web reads from Container A's ephemeral filesystem  
3. ❌ Containers don't share filesystems
4. ❌ Data lost on container restart
5. ❌ Users get stale data from git repo (August 2025)

---

## ✅ PROPOSED ARCHITECTURE (DATABASE SOLUTION)

### Data Flow
```
┌─────────────────────────────────────────────────────────────────┐
│                    RENDER PLATFORM (Cloud)                       │
├─────────────────────────┬────────────────┬──────────────────────┤
│  CRON SERVICE           │  WEB SERVICE   │  WORKER SERVICE      │
│  (Container B)          │  (Container A) │  (Container C)       │
│  ┌─────────────────┐    │  ┌───────────┐ │  ┌────────────┐     │
│  │ Hourly Job      │    │  │ Flask App │ │  │ Scheduler  │     │
│  │                 │    │  │           │ │  │ Telegram   │     │
│  │ 1. Download PNG │    │  │ GET /api/ │ │  │ Alerts     │     │
│  │ 2. Process data │    │  │   curva   │ │  │            │     │
│  │ 3. Write DB ✅  │    │  │           │ │  │            │     │
│  └────────┬────────┘    │  └─────┬─────┘ │  └──────┬─────┘     │
│           │             │        │       │         │           │
│           ▼             │        ▼       │         ▼           │
└───────────┼─────────────┴────────┼───────┴─────────┼───────────┘
            │                      │                 │
            └──────────────┬───────┴─────────────────┘
                           │
                           ▼
            ┌──────────────────────────────────────────┐
            │     PostgreSQL Database (PERSISTENT)     │
            ├──────────────────────────────────────────┤
            │  tremor_data_points                      │
            │  ┌────────────────────────────────────┐  │
            │  │ id | timestamp | value | source   │  │
            │  │  1 | 2026-02-03 | 1.5  | ingv    │  │
            │  │  2 | 2026-02-03 | 1.7  | ingv    │  │
            │  │  3 | 2026-02-03 | 1.6  | ingv    │  │
            │  │ ... (last 14 days)                │  │
            │  └────────────────────────────────────┘  │
            │                                          │
            │  ✅ Shared across ALL containers        │
            │  ✅ Persistent (survives restarts)      │
            │  ✅ ACID guarantees                     │
            │  ✅ Fast indexed queries                │
            └──────────────────────────────────────────┘

Advantages:
✅ Single source of truth
✅ All containers access same database
✅ Data persists across deployments
✅ Production-grade reliability
```

### Benefits
1. ✅ Cron writes to PostgreSQL (shared, persistent)
2. ✅ Web reads from PostgreSQL (same database)
3. ✅ Worker reads from PostgreSQL (same database)
4. ✅ Data survives container restarts
5. ✅ Users always get fresh data
6. ✅ Historical data available
7. ✅ Fast queries with indexes

---

## 🔄 DATA PIPELINE COMPARISON

### CURRENT (CSV-based)
```
INGV PNG → Download → Process → CSV File (ephemeral) → Lost on restart
                                       ↓
                                  ❌ Web service never sees it
```

### PROPOSED (Database-based)
```
INGV PNG → Download → Process → CSV File (local backup)
                              ↓
                              → Database (persistent) ← ✅ Web service reads
                                       ↓
                              ✅ Shared across all services
                              ✅ Survives restarts
                              ✅ Historical queries
```

---

## 📊 COMPARISON TABLE

| Aspect | CSV (Current) | Database (Proposed) |
|--------|---------------|---------------------|
| **Storage** | Ephemeral filesystem | PostgreSQL |
| **Persistence** | ❌ Lost on restart | ✅ Permanent |
| **Sharing** | ❌ Per-container | ✅ All containers |
| **Reliability** | ❌ Low | ✅ High |
| **Performance** | ⚠️ File I/O | ✅ Indexed queries |
| **History** | ❌ Single snapshot | ✅ Full history |
| **Backup** | ❌ Manual | ✅ Automated |
| **Scalability** | ❌ Single file | ✅ ACID database |
| **Cost** | Free | Free (included) |
| **Effort** | 0 (current) | ~3 hours |

---

## 🎯 MIGRATION STRATEGY

### Phase 1: Add Database Layer (backward compatible)
```
Cron Job:
  1. Download PNG
  2. Process data
  3. Write to CSV (existing logic)
  4. Write to Database (NEW) ← Add this
  
Web Service:
  1. Try read from Database (NEW) ← Add this
  2. Fallback to CSV if DB empty
  3. Return data
```

### Phase 2: Switch Primary Source (after verification)
```
Cron Job:
  1. Download PNG
  2. Process data
  3. Write to Database (PRIMARY)
  4. Write to CSV (backup for dev)
  
Web Service:
  1. Read from Database (PRIMARY)
  2. Return data
  (CSV kept for local development)
```

---

## 🚀 IMPLEMENTATION STEPS

### Step 1: Database Setup
```bash
# Create migration
flask db revision -m "add_tremor_data_points"

# Edit migration file
# - Add CREATE TABLE
# - Add indexes
# - Add downgrade logic

# Apply migration
flask db upgrade
```

### Step 2: Update Cron Job
```python
# In scripts/csv_updater.py
def _write_to_database(rows, source):
    app = create_app()
    with app.app_context():
        for row in rows:
            db.session.merge(TremorDataPoint(
                timestamp=row['timestamp'],
                value=row['value'],
                source=source
            ))
        db.session.commit()
```

### Step 3: Update API
```python
# In app/routes/api.py
@api_bp.get("/api/curva")
def get_curva():
    # Query database instead of reading CSV
    points = TremorDataPoint.query.order_by(
        TremorDataPoint.timestamp.desc()
    ).limit(limit).all()
    
    return jsonify({"ok": True, "data": points})
```

### Step 4: Deploy & Verify
```bash
# Push to GitHub
git add .
git commit -m "Fix: Move tremor data to PostgreSQL"
git push origin main

# Render auto-deploys
# Wait for migration to run
# Wait for cron job (hourly)
# Verify data in database
```

---

## ✅ SUCCESS CRITERIA

After deployment, verify:

1. **Database has data:**
   ```sql
   SELECT COUNT(*), MAX(timestamp) FROM tremor_data_points;
   -- Expected: count > 0, timestamp = today
   ```

2. **API returns fresh data:**
   ```bash
   curl https://etnamonitor.it/api/curva
   # Expected: "last_ts": "2026-02-03T..."
   ```

3. **Homepage shows current data:**
   - Visit https://etnamonitor.it/
   - Graph should show data from today
   - No "stale data" warnings

4. **Cron job logs success:**
   ```
   [CSV] update source=white rows=288
   [DB] Wrote 288 tremor data points
   ```

---

**Conclusion:** Database solution is the ONLY reliable way to persist data across Render's ephemeral containers.
