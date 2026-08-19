# Setup Guide - Wildfire Detection System

## Step 1: Install PostgreSQL + PostGIS

### Windows Installation

#### Option 1: PostGIS Bundle Installer (Recommended)

1. **Download PostGIS Bundle**
   - Visit: https://postgis.net/windows_downloads/
   - Download: `postgis-bundle-pg14-3.3.2x64.zip` (or latest version)
   - Extract to a temporary folder

2. **Run PostGIS Installer**
   ```
   Double-click: postgis-bundle-pg14-3.3.2x64\postgisgui\postgis_install.exe
   ```
   - Select PostgreSQL installation directory (usually `C:\Program Files\PostgreSQL\14`)
   - Click Install

3. **Verify Installation**
   ```sql
   psql -U postgres
   \dx  -- List extensions
   ```
   You should see `postgis` available.

#### Option 2: Stack Builder (Alternative)

1. **Open Stack Builder**
   - Start Menu → PostgreSQL 14 → Application Stack Builder
   
2. **Select PostGIS**
   - Categories → Spatial Extensions
   - Check "PostGIS 3.x Bundle for PostgreSQL 14"
   - Click Next → Download & Install

3. **Complete Installation**
   - Follow wizard prompts
   - Restart PostgreSQL service if needed

#### Option 3: Use Docker (Easiest)

```bash
# Pull PostGIS image
docker pull postgis/postgis:14-3.3

# Run container
docker run --name wildfire-db -e POSTGRES_PASSWORD=yourpassword -p 5432:5432 -d postgis/postgis:14-3.3

# Connect
psql -h localhost -U postgres
```

---

## Step 2: Create Database & Enable PostGIS

```sql
-- Connect to PostgreSQL
psql -U postgres

-- Create database
CREATE DATABASE wildfire_db;

-- Connect to new database
\c wildfire_db

-- Enable PostGIS extension
CREATE EXTENSION postgis;

-- Verify PostGIS is installed
SELECT PostGIS_Version();

-- You should see something like: "3.3 USE_GEOS=1 USE_PROJ=1..."
```

---

## Step 3: Setup Python Environment

```bash
# Navigate to project
cd c:\project\wildfire_detection

# Create virtual environment
python -m venv venv

# Activate
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

---

## Step 4: Configure Environment

```bash
# Copy template
cp .env.example .env

# Edit .env with your credentials
notepad .env
```

Update these values:
```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/wildfire_db
FIRMS_API_KEY=your_firms_api_key_here
```

Get a free FIRMS key at https://firms.modaps.eosdis.nasa.gov/api/area/ — never commit a real key to this file or git history.

---

## Step 5: Create Database Tables

```bash
python scripts/create_tables_simple.py

# Upgrading an existing (pre-world) database? Backfill the region column:
python scripts/migrate_add_region.py
```

---

## Step 6: Load Data

The system ingests a single global (`region="world"`) NASA FIRMS dataset — there's no per-country ingest to configure.

```bash
# Optional: bootstrap with historical archive data
python scripts/import_archive.py

# Pull live hotspots for the last N day(s)
python scripts/fetch_daily.py --days 1

# Or run the full pipeline (fetch → aggregate → features → score → alerts → enrich)
python scripts/daily_pipeline.py --days 1
```

---

## Troubleshooting

### PostGIS Extension Error

**Error:** `could not open extension control file "postgis.control"`

**Solution:**
1. PostGIS is not installed
2. Follow Option 1 or Option 2 above to install PostGIS
3. Restart PostgreSQL service:
   ```
   Services → PostgreSQL 14 → Restart
   ```

### Connection Refused

**Error:** `connection to server at "localhost" failed`

**Solution:**
1. Check PostgreSQL is running:
   ```
   Services → PostgreSQL 14 → Status: Running
   ```
2. Check port 5432 is not blocked by firewall

### Password Authentication Failed

**Solution:**
Update `.env` with correct password:
```env
DATABASE_URL=postgresql://postgres:YOUR_ACTUAL_PASSWORD@localhost:5432/wildfire_db
```

---

## Next Steps

Once PostGIS is installed and the database is created:

1. ✅ Create database tables (`create_tables_simple.py` + `migrate_add_region.py` if upgrading)
2. ✅ Ingest world FIRMS data (`fetch_daily.py` or `daily_pipeline.py`)
3. ✅ Build features (`build_features.py`)
4. ✅ Train ML model (`train_model.py`)
5. ✅ Score + select alerts (`score_daily.py`, `select_top_k.py`)
6. ✅ Start the API (`uvicorn wildfire_detection.api.main:app --reload`)

Continue to: root [`README.md`](../README.md) Quick Start, or [`INSTALLATION.md`](../INSTALLATION.md) for a full production setup (systemd + cron).
