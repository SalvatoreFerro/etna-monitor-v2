# 🔴 Production Issue Documentation Index

**Issue:** Stale data on https://etnamonitor.it/api/curva (August 2025)  
**Date:** 2026-02-03  
**Status:** Diagnosed - Awaiting Implementation

---

## 📚 DOCUMENTATION STRUCTURE

This directory contains a complete analysis of the production issue and recommended solution.

### Quick Start
1. **Start here:** [EXECUTIVE_SUMMARY.md](./EXECUTIVE_SUMMARY.md) - 5 minute read
2. **Visual overview:** [ARCHITECTURE_COMPARISON.md](./ARCHITECTURE_COMPARISON.md) - 10 minute read
3. **Full analysis:** [RENDER_CSV_ISSUE_ANALYSIS.md](./RENDER_CSV_ISSUE_ANALYSIS.md) - 20 minute read

---

## 📖 DOCUMENT GUIDE

### 1. EXECUTIVE_SUMMARY.md
**Purpose:** Quick overview for decision makers  
**Time to read:** 5 minutes  
**Contents:**
- Problem statement (3 bullet points)
- Recommended solution
- What needs to happen
- Timeline estimate
- Why CSV files don't work on Render

**Read this if:** You need to make a decision quickly

---

### 2. ARCHITECTURE_COMPARISON.md
**Purpose:** Visual comparison of current vs. proposed architecture  
**Time to read:** 10 minutes  
**Contents:**
- Current architecture diagram (broken)
- Proposed architecture diagram (database solution)
- Data pipeline comparison
- Side-by-side comparison table
- Migration strategy
- Implementation steps
- Success criteria

**Read this if:** You want to understand the technical architecture

---

### 3. RENDER_CSV_ISSUE_ANALYSIS.md
**Purpose:** Complete technical analysis and implementation guide  
**Time to read:** 20 minutes  
**Contents:**
- ROOT CAUSE ANALYSIS
  - Render's ephemeral filesystem
  - Container isolation
  - Current configuration problems
- SOLUTION OPTIONS
  - Option A: Database (recommended)
  - Option B: Shared persistent disk (not available)
  - Option C: S3 storage (complex)
  - Option D: API-based (not suitable)
- IMPLEMENTATION PLAN
  - Step-by-step instructions
  - Code samples
  - Migration file templates
- VERIFICATION STEPS
- FILES TO MODIFY

**Read this if:** You're implementing the solution

---

## 🎯 THE PROBLEM (TL;DR)

### What's Happening
Production site returns **stale tremor data from August 2025** instead of current data.

### Root Cause
Render uses **ephemeral filesystems** and **isolated containers**:
- Cron job writes CSV to Container B's filesystem
- Web service reads CSV from Container A's filesystem
- Containers don't share filesystems
- Data is lost on every restart

### The Fix
**Use PostgreSQL database** instead of CSV files:
- Database is persistent and shared across all containers
- All services read from the same database
- Data survives restarts and deployments
- Production-grade reliability

---

## 🛠️ IMPLEMENTATION OVERVIEW

### Effort Estimate
- **Total time:** ~3 hours
- **Complexity:** Medium
- **Risk:** Low (backward compatible)

### What Changes
1. **NEW:** Database table `tremor_data_points`
2. **NEW:** SQLAlchemy model `TremorDataPoint`
3. **MODIFY:** Cron job to write to database
4. **MODIFY:** API endpoint to read from database
5. **MODIFY:** Homepage to read from database

### What Stays the Same
- CSV files kept for local development
- Cron job schedule (hourly)
- API response format
- Homepage display

---

## 📋 QUICK CHECKLIST

Before starting implementation:
- [ ] Read EXECUTIVE_SUMMARY.md
- [ ] Understand ARCHITECTURE_COMPARISON.md
- [ ] Review RENDER_CSV_ISSUE_ANALYSIS.md
- [ ] Approve solution (Option A: Database)
- [ ] Check database access in Render
- [ ] Backup current data if needed

During implementation:
- [ ] Create database migration
- [ ] Create SQLAlchemy model
- [ ] Update cron job (add DB write)
- [ ] Update API endpoint (read from DB)
- [ ] Update homepage (read from DB)
- [ ] Test locally
- [ ] Deploy to Render
- [ ] Monitor logs

After deployment:
- [ ] Verify database has data
- [ ] Test API returns fresh data
- [ ] Check homepage shows current data
- [ ] Monitor for 24 hours

---

## 🚨 CRITICAL INFORMATION

### Why This Can't Wait
- ❌ Users see incorrect seismic information
- ❌ Telegram alerts may not trigger
- ❌ Homepage shows outdated graph (6 months old)
- ❌ API responses are unreliable

### Why CSV Files Won't Work
Render architecture **fundamentally prevents** CSV file sharing:
- Each service has its own ephemeral filesystem
- Filesystems are NOT shared between services
- Files reset on every deploy/restart
- No persistent disk sharing on any Render plan

### Why Database is the Only Solution
- PostgreSQL is already configured in Render
- Database is persistent and shared
- All containers access the same database
- Industry-standard solution for shared state
- Zero additional cost

---

## 📞 QUESTIONS?

### Before Implementation
- **Q:** Can we use S3 instead of database?
  - **A:** Yes, but it's more complex and adds latency. See Option C in detailed analysis.
  
- **Q:** Can we use shared persistent disk?
  - **A:** No, Render doesn't support shared disks between services.
  
- **Q:** Will this break existing functionality?
  - **A:** No, the implementation is backward compatible with CSV fallback.

### During Implementation
- **Q:** Where should I create the migration file?
  - **A:** See RENDER_CSV_ISSUE_ANALYSIS.md, Step 1
  
- **Q:** What if the database is empty?
  - **A:** API will fallback to CSV file (for smooth transition)

### After Deployment
- **Q:** How do I verify it's working?
  - **A:** See "Verification Steps" in RENDER_CSV_ISSUE_ANALYSIS.md
  
- **Q:** What if something goes wrong?
  - **A:** CSV fallback is still active, rollback migration if needed

---

## 📁 RELATED FILES

### Analysis Documents (this repo)
- `EXECUTIVE_SUMMARY.md` - Quick overview
- `ARCHITECTURE_COMPARISON.md` - Visual diagrams
- `RENDER_CSV_ISSUE_ANALYSIS.md` - Complete analysis
- `DIAGNOSIS_INDEX.md` - This file

### Existing Documentation
- `DIAGNOSIS_AND_FIX.md` - Previous partial fix attempt
- `README_RENDER.md` - Render deployment guide
- `RENDER_DEPLOYMENT.md` - Render configuration notes

### Code Files to Modify
- `migrations/versions/20260203_add_tremor_data_points.py` (NEW)
- `app/models/tremor_data.py` (NEW)
- `scripts/csv_updater.py` (MODIFY)
- `app/routes/api.py` (MODIFY)
- `app/routes/main.py` (MODIFY)

---

## ✅ NEXT STEPS

1. **Read the documentation**
   - [ ] EXECUTIVE_SUMMARY.md (5 min)
   - [ ] ARCHITECTURE_COMPARISON.md (10 min)
   - [ ] RENDER_CSV_ISSUE_ANALYSIS.md (20 min)

2. **Make decision**
   - [ ] Approve Option A (Database)
   - [ ] Or choose Option C (S3)
   - [ ] Set timeline for implementation

3. **Start implementation**
   - [ ] Follow checklist in RENDER_CSV_ISSUE_ANALYSIS.md
   - [ ] Test locally before deploying
   - [ ] Deploy to Render

4. **Verify and monitor**
   - [ ] Check database has data
   - [ ] Test API endpoint
   - [ ] Monitor for 24 hours

---

**Status:** Documentation complete. Ready for implementation.  
**Recommendation:** Proceed with Option A (PostgreSQL database).  
**Estimated completion:** 3 hours + testing
