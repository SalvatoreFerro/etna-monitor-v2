# 🔴 CRITICAL: Render CSV Update Failure - Complete Analysis

**Date:** 2026-02-03  
**Issue:** Production site https://etnamonitor.it/api/curva shows stale data from August 2025  
**Root Cause:** Render ephemeral filesystem + container isolation  
**Status:** DIAGNOSED - Implementation Required

---

## 🎯 EXECUTIVE SUMMARY

### The Problem
The CSV file `data/curva_colored.csv` is **NOT being updated on Render** because:

1. **Render uses ephemeral filesystems** - All files reset on container restart
2. **Services run in isolated containers** - Cron and Web services cannot share files
3. **Current config writes to ephemeral `/workspace/` path** - Changes are lost immediately

### The Impact
- ❌ Homepage shows outdated tremor data (August 2025)
- ❌ API endpoint `/api/curva` returns stale data
- ❌ Telegram alerts may not trigger correctly
- ❌ Users see incorrect seismic activity information

### The Solution
**Move from CSV files to PostgreSQL database** (already configured in Render)

---

## 🔍 ROOT CAUSE ANALYSIS

### Render Architecture Issue

```
┌─────────────────────────────────────────────────────────────────┐
│                         RENDER PLATFORM                          │
├─────────────────┬─────────────────┬─────────────────────────────┤
│  Web Service    │  Cron Service   │  Worker Service             │
│  Container A    │  Container B    │  Container C                │
│                 │                 │                              │
│  Filesystem A   │  Filesystem B   │  Filesystem C               │
│  (ephemeral)    │  (ephemeral)    │  (ephemeral)                │
│                 │                 │                              │
│  reads CSV ❌   │  writes CSV ❌  │                             │
│  sees old data  │  lost on restart│                             │
└─────────────────┴─────────────────┴─────────────────────────────┘
```

### Current Data Flow (BROKEN)

1. **Cron Job runs hourly** (`etnamonitor-csv-updater`)
   - Downloads PNG from INGV
   - Processes data successfully
   - Writes to `/workspace/etna-monitor-v2/data/curva_colored.csv`
   - ❌ **File written to Container B's ephemeral filesystem**
   - ❌ **Lost when container restarts (every deploy, every scale event)**

2. **Web Service serves requests**
   - User visits homepage or calls `/api/curva`
   - Reads from `/workspace/etna-monitor-v2/data/curva_colored.csv`
   - ❌ **Reading from Container A's filesystem, not Container B**
   - ❌ **File doesn't exist or contains stale data from git repo**

### Why This Happened

The configuration in `render.yaml` assumes a **shared persistent filesystem**:

```yaml
# render.yaml (lines 15, 65)
- key: CURVA_CSV_PATH
  value: /workspace/etna-monitor-v2/data/curva_colored.csv
```

**But Render does NOT provide shared persistent storage:**
- Render Free/Starter plans: No persistent disks
- Render Paid plans: Persistent disks are per-service only
- `/workspace/` directory: Part of Docker image, ephemeral

---

## 🛠️ RECOMMENDED SOLUTION: DATABASE STORAGE

### Why Database?
✅ PostgreSQL already configured in Render  
✅ Persistent storage shared across all containers  
✅ Production-grade reliability  
✅ Enables historical queries and analytics  
✅ Simple implementation (~3 hours)  

### Implementation Overview

#### 1. Create Database Table
```sql
CREATE TABLE tremor_data_points (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL UNIQUE,
    value NUMERIC NOT NULL,
    value_max NUMERIC,
    value_avg NUMERIC,
    source VARCHAR(50) NOT NULL DEFAULT 'ingv_white',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tremor_timestamp ON tremor_data_points(timestamp DESC);
CREATE INDEX idx_tremor_created_at ON tremor_data_points(created_at DESC);
```

#### 2. Modify Cron Job
**File:** `scripts/csv_updater.py`

Add function to write to database after CSV write:

```python
def _write_to_database(rows: list, source: str) -> None:
    """Write tremor data points to database."""
    from app import create_app
    from app.models import db
    from app.models.tremor_data import TremorDataPoint
    
    app = create_app()
    with app.app_context():
        # Bulk insert with UPSERT
        for row in rows:
            point = TremorDataPoint(
                timestamp=row['timestamp'],
                value=row['value'],
                value_max=row.get('value_max'),
                value_avg=row.get('value_avg'),
                source=source
            )
            db.session.merge(point)
        db.session.commit()
        log.info("[DB] Wrote %s tremor data points", len(rows))
```

#### 3. Modify API Endpoint
**File:** `app/routes/api.py`

Change `/api/curva` to read from database:

```python
@api_bp.get("/api/curva")
def get_curva():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    limit = request.args.get("limit", type=int, default=2016)
    
    # Query database instead of reading CSV
    points = (
        TremorDataPoint.query
        .order_by(TremorDataPoint.timestamp.desc())
        .limit(limit)
        .all()
    )
    
    if not points:
        return jsonify({"ok": False, "error": "No data"}), 200
    
    data = [
        {
            "timestamp": to_iso_utc(p.timestamp),
            "value": float(p.value),
        }
        for p in reversed(points)
    ]
    
    return jsonify({
        "ok": True,
        "data": data,
        "rows": len(data),
        "source": "database",
        "last_ts": to_iso_utc(points[0].timestamp),
    })
```

#### 4. Modify Homepage
**File:** `app/routes/main.py`

Update `load_curva_dataframe()` to query database:

```python
def load_curva_dataframe(limit: int = 2016) -> pd.DataFrame:
    """Load tremor data from database"""
    points = (
        TremorDataPoint.query
        .order_by(TremorDataPoint.timestamp.desc())
        .limit(limit)
        .all()
    )
    
    data = [
        {
            "timestamp": p.timestamp,
            "value": float(p.value),
        }
        for p in reversed(points)
    ]
    
    return pd.DataFrame(data)
```

---

## 📋 IMPLEMENTATION CHECKLIST

### Phase 1: Database Setup (30 min)
- [ ] Create migration file: `migrations/versions/20260203_add_tremor_data_points.py`
- [ ] Create model: `app/models/tremor_data.py`
- [ ] Add to `app/models/__init__.py`
- [ ] Run migration locally: `flask db upgrade`
- [ ] Test migration rollback: `flask db downgrade`

### Phase 2: Update Data Pipeline (60 min)
- [ ] Modify `scripts/csv_updater.py` - add `_write_to_database()`
- [ ] Call `_write_to_database()` after CSV write
- [ ] Test locally with `RUN_ONCE=1 python scripts/csv_updater.py`
- [ ] Verify data in database: `SELECT * FROM tremor_data_points LIMIT 10`

### Phase 3: Update API & Homepage (60 min)
- [ ] Modify `/api/curva` endpoint in `app/routes/api.py`
- [ ] Add fallback to CSV if database is empty
- [ ] Modify homepage in `app/routes/main.py`
- [ ] Test locally: `flask run`
- [ ] Verify homepage loads with database data
- [ ] Verify API returns database data

### Phase 4: Deploy & Verify (30 min)
- [ ] Commit changes
- [ ] Push to GitHub
- [ ] Wait for Render auto-deploy
- [ ] Check migration ran: Render logs
- [ ] Wait for cron job (runs every hour at :00)
- [ ] Verify database has new data
- [ ] Test API: `curl https://etnamonitor.it/api/curva`
- [ ] Check homepage shows fresh data

---

## 🚀 QUICK FIX (Temporary - 1 hour)

If you need an **immediate fix** before implementing the full database solution:

### Use Database as Simple Cache

1. **Create simple cache table:**
```sql
CREATE TABLE csv_cache (
    key VARCHAR(255) PRIMARY KEY,
    data JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

2. **Modify cron to write cache:**
```python
# In scripts/csv_updater.py, after CSV write:
with app.app_context():
    from sqlalchemy import text
    cache_data = json.dumps([
        {"timestamp": r["timestamp"], "value": r["value"]}
        for r in cleaned_rows
    ])
    db.session.execute(
        text("INSERT INTO csv_cache (key, data) VALUES (:k, :d) "
             "ON CONFLICT (key) DO UPDATE SET data = :d, updated_at = NOW()"),
        {"k": "curva_latest", "d": cache_data}
    )
    db.session.commit()
```

3. **Modify API to read cache:**
```python
# In app/routes/api.py, in get_curva():
from sqlalchemy import text
result = db.session.execute(
    text("SELECT data FROM csv_cache WHERE key = 'curva_latest'")
).fetchone()

if result:
    data = json.loads(result[0])
    return jsonify({"ok": True, "data": data, "source": "cache"})
```

**Pros:** Can be deployed in 1 hour  
**Cons:** Still need to implement full solution later

---

## 📊 VERIFICATION STEPS

After deployment:

### 1. Check Cron Job Logs
```
Render Dashboard → etnamonitor-csv-updater → Logs
```

Look for:
```
[CSV] update source=white rows=288
[DB] Wrote 288 tremor data points
```

### 2. Query Database
```sql
SELECT 
    COUNT(*) as total_points,
    MAX(timestamp) as latest_timestamp,
    MIN(timestamp) as earliest_timestamp,
    MAX(created_at) as last_update
FROM tremor_data_points;
```

Expected:
- `total_points`: > 0
- `latest_timestamp`: within last 2 hours
- `last_update`: within last 2 hours

### 3. Test API
```bash
curl -H "Authorization: Bearer TOKEN" https://etnamonitor.it/api/curva | jq .
```

Expected response:
```json
{
  "ok": true,
  "rows": 2016,
  "last_ts": "2026-02-03T15:00:00+00:00",
  "source": "database",
  "is_stale": false,
  "detected_today": true
}
```

### 4. Check Homepage
Visit https://etnamonitor.it/

- Graph should show recent data
- Last update timestamp should be today
- No stale data warnings

---

## 📁 FILES TO MODIFY

### New Files (3)
1. `migrations/versions/20260203_add_tremor_data_points.py` - Database migration
2. `app/models/tremor_data.py` - SQLAlchemy model
3. `RENDER_CSV_ISSUE_ANALYSIS.md` - This document

### Modified Files (4)
1. `scripts/csv_updater.py` - Add database write
2. `app/routes/api.py` - Read from database
3. `app/routes/main.py` - Read from database
4. `app/models/__init__.py` - Import new model

### Optional Cleanup
1. `render.yaml` - Remove obsolete `CURVA_CSV_PATH` env vars
2. `data/curva_colored.csv` - Keep for local development fallback

---

## ⚠️ ALTERNATIVE: S3 STORAGE

If you prefer **not** to use the database:

### Option C: Store CSV in S3/R2

**Pros:**
- Persistent storage
- Shared across containers
- S3 already configured

**Cons:**
- Adds latency (S3 API call on every request)
- Requires caching strategy
- More complex error handling

**Implementation:**
1. Modify `scripts/csv_updater.py` to upload CSV to S3
2. Modify `/api/curva` to download from S3 (with 60s cache)
3. Configure S3 bucket and credentials in render.yaml

**Effort:** ~4 hours (more complex than database)

---

## 📝 DECISION REQUIRED

**Choose implementation approach:**

- ⭐ **Option A: Database** (Recommended)
  - Effort: 3 hours
  - Reliability: HIGH
  - Future-proof: YES
  
- 🚀 **Quick Fix: Database Cache** (Temporary)
  - Effort: 1 hour
  - Reliability: MEDIUM
  - Must implement Option A later
  
- 📦 **Option C: S3 Storage**
  - Effort: 4 hours
  - Reliability: HIGH
  - Adds complexity

**Recommendation:** Implement **Option A (Database)** for production-grade reliability.

---

## 🆘 NEED HELP?

Reference documents:
- Render docs: https://render.com/docs/disks
- Flask-Migrate: https://flask-migrate.readthedocs.io/
- SQLAlchemy: https://docs.sqlalchemy.org/

Questions to resolve:
1. Approve Option A (Database) vs Option C (S3)?
2. Deploy quick fix first, then full solution?
3. Timeline for implementation?

---

**Status:** Awaiting decision and implementation approval.
