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
cp config/.env.example .env

# Edit .env with your credentials
notepad .env
```

Update these values:
```env
DATABASE_URL=postgresql://postgres:yourpassword@localhost:5432/wildfire_db
FIRMS_API_KEY=9ae1e0c7f5a6ae110169c38075aba8aa
```

---

## Step 5: Create Database Tables

```bash
# Run Alembic migrations (we'll create these next)
alembic upgrade head
```

---

## Step 6: Import Archive Data

```bash
# Import 92 days of historical data
python scripts/import_archive.py
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

Once PostGIS is installed and database is created:

1. ✅ Create database models
2. ✅ Setup Alembic migrations
3. ✅ Import archive data
4. ✅ Build features
5. ✅ Train ML model

Continue to: [Database Models Setup](./DATABASE_SETUP.md)
