# 🔴 PRODUCTION ISSUE: Stale Data (August 2025)

**Site:** https://etnamonitor.it/api/curva  
**Issue:** Returns stale data from August 2025  
**Root Cause:** Render's ephemeral filesystem + container isolation  
**Impact:** Users see incorrect seismic data  

---

## THE PROBLEM IN 3 POINTS

1. **Cron job writes CSV to ephemeral filesystem** → Lost on restart
2. **Web and cron run in different containers** → Cannot share files  
3. **No persistent storage configured** → Data doesn't persist

## THE SOLUTION

**Use PostgreSQL database instead of CSV files**

Why database?
- ✅ Already configured in Render
- ✅ Shared across all containers  
- ✅ Persistent storage
- ✅ Production-grade
- ✅ Takes ~3 hours to implement

## WHAT NEEDS TO HAPPEN

### Quick Overview
1. Create `tremor_data_points` table in PostgreSQL
2. Modify cron job to write to database (+ CSV for backward compat)
3. Modify `/api/curva` to read from database
4. Modify homepage to read from database
5. Deploy and verify

### Files to Modify
- **NEW:** `migrations/versions/20260203_add_tremor_data_points.py`
- **NEW:** `app/models/tremor_data.py`
- **MODIFY:** `scripts/csv_updater.py` (add DB write)
- **MODIFY:** `app/routes/api.py` (read from DB)
- **MODIFY:** `app/routes/main.py` (read from DB)

### Timeline
- Database setup: 30 min
- Update cron pipeline: 60 min  
- Update API/homepage: 60 min
- Deploy & verify: 30 min
- **Total: ~3 hours**

---

## ALTERNATIVE: Quick Fix (1 hour)

Use database as JSON cache:
1. Create `csv_cache` table with JSONB column
2. Cron writes full dataset as JSON
3. API reads from cache

**Pros:** Fast to implement  
**Cons:** Still need proper solution later

---

## WHY CSV FILES DON'T WORK ON RENDER

Render architecture:
```
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│ Web Container │  │ Cron Container│  │Worker Container│
│  Filesystem A │  │  Filesystem B │  │  Filesystem C  │
│  (ephemeral)  │  │  (ephemeral)  │  │  (ephemeral)   │
└───────────────┘  └───────────────┘  └───────────────┘
```

- Each service has its OWN ephemeral filesystem
- Files are NOT shared between containers
- Filesystems reset on every deploy/restart
- `/workspace/` is part of Docker image, not persistent storage

**Result:** Cron writes CSV → Web never sees it → Users get stale data

---

## NEXT STEPS

1. **Decision:** Approve database solution (Option A)
2. **Implement:** Follow checklist in `RENDER_CSV_ISSUE_ANALYSIS.md`
3. **Deploy:** Push to GitHub → Render auto-deploys
4. **Verify:** Check logs, query DB, test API

---

**Full analysis:** See `RENDER_CSV_ISSUE_ANALYSIS.md`  
**Questions?** Ask before starting implementation
