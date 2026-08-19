# Production Installation Guide

> Wildfire Hotspot Anomaly Detection System  
> Full setup from a blank server to a running API.

---

## Prerequisites

| Requirement | Minimum Version | Notes |
|-------------|----------------|-------|
| Ubuntu / Debian | 22.04 LTS | Other Linux distros work — adjust package manager commands |
| Python | 3.10+ | 3.11 recommended |
| PostgreSQL | 14+ | Must have PostGIS extension |
| PostGIS | 3.x | Spatial queries on hotspot coordinates |
| Git | Any | For cloning the repo |

---

## 1. System Dependencies

```bash
sudo apt update && sudo apt install -y \
    python3.11 \
    python3.11-venv \
    python3-pip \
    postgresql \
    postgresql-contrib \
    postgis \
    postgresql-14-postgis-3 \
    libpq-dev \
    build-essential \
    git
```

> On PostgreSQL 15/16, replace `postgresql-14-postgis-3` with `postgresql-15-postgis-3` or `postgresql-16-postgis-3` as appropriate.

---

## 2. PostgreSQL Setup

### Start PostgreSQL

```bash
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

### Create database and user

```bash
sudo -u postgres psql << 'EOF'
CREATE USER wildfire_user WITH PASSWORD 'your_secure_password';
CREATE DATABASE wildfire_db OWNER wildfire_user;
\c wildfire_db
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
GRANT ALL PRIVILEGES ON DATABASE wildfire_db TO wildfire_user;
EOF
```

### Verify PostGIS

```bash
sudo -u postgres psql -d wildfire_db -c "SELECT PostGIS_Version();"
```

---

## 3. Project Setup

### Clone the repository

```bash
git clone https://github.com/Ilhammf15/anomalous-wildfire-hotspots-detection.git
cd anomalous-wildfire-hotspots-detection
```

### Create virtual environment

```bash
python3.11 -m venv venv
source venv/bin/activate
```

### Install the package and dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

> The `pip install -e .` step registers the `wildfire_detection` package so all scripts can find each other.

---

## 4. Environment Configuration

### Copy the example env file

```bash
cp .env.example .env
```

### Edit `.env` with your actual values

```bash
nano .env
```

Required values:

```env
DATABASE_URL=postgresql://wildfire_user:your_secure_password@localhost:5432/wildfire_db
FIRMS_API_KEY=your_nasa_firms_api_key
H3_RESOLUTION=7
ML_CONTAMINATION=0.1
ML_N_ESTIMATORS=100
TOP_K_ALERTS=20
API_HOST=0.0.0.0
API_PORT=8000
```

### Get a NASA FIRMS API key

1. Go to [https://firms.modaps.eosdis.nasa.gov/api/area/](https://firms.modaps.eosdis.nasa.gov/api/area/)
2. Register with a NASA Earthdata account (free)
3. Your API key appears on the page after login

---

## 5. Create Database Tables

```bash
python scripts/create_tables_simple.py
```

This creates all 6 tables (`raw_hotspots`, `cell_day_aggregates`, `cell_day_features`, `cell_day_scores`, `daily_alerts`, `h3_cell_metadata`) via the SQLAlchemy models — including the `region` column used to tag every row `world`.

> **Upgrading an existing database created before the world-scope change?** Run `python scripts/migrate_add_region.py` afterwards (or instead, on an already-populated DB). It's idempotent — it checks each column/index/constraint before creating it, so it's safe to re-run.

---

## 6. Load Historical Data (Optional Bootstrap)

The system ingests a single global (`region="world"`) dataset — there's no per-country archive to pick. `import_archive.py` is an optional one-time bootstrap so the ML model has enough history to train on without waiting for `fetch_daily.py`/cron to accumulate it live.

```bash
python scripts/import_archive.py
```

Expected: several hundred thousand rows inserted, tagged `region="world"`. This takes a few minutes depending on archive size. You can skip this step and rely on `scripts/fetch_daily.py` (step 7 below and the cron job in step 11) if you're fine waiting for live data to build up.

---

## 7. Run the Full Pipeline on Historical Data

This step optionally pulls the latest live data, then aggregates, trains the model, scores anomalies, and selects alerts — all at once for all historical dates.

```bash
# Step 0 (optional): pull the latest live world data on top of the archive
python scripts/fetch_daily.py --days 1

# Step 1: Aggregate raw hotspots into H3 cell-day records
python scripts/aggregate_daily.py

# Step 2: Build temporal and spatial features for ML
python scripts/build_features.py

# Step 3: Train the Isolation Forest model
python scripts/train_model.py

# Step 4: Score all cell-day records
python scripts/score_daily.py

# Step 5: Select top-K alerts per day with spatial coherence
python scripts/select_top_k.py
```

> After training, the model is saved to `models/isolation_forest_v1.0.pkl`.

---

## 8. Enrich H3 Cell Metadata (Optional but Recommended)

Reverse-geocodes each H3 cell index (worldwide) to a human-readable place name via Nominatim — province/regency/district for Indonesian cells, country/region-level names elsewhere.
This runs in the background and takes approximately 90 minutes for ~5,000 cells.

```bash
nohup python scripts/enrich_h3_metadata.py > logs/enrich_h3.log 2>&1 &
```

Check progress:

```bash
tail -f logs/enrich_h3.log
```

> The API works without this step — it falls back to raw coordinates and will geocode new cells automatically in the background as they are requested.

---

## 9. Start the API Server

### Development (with auto-reload)

```bash
uvicorn wildfire_detection.api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Production (with Gunicorn + Uvicorn workers)

```bash
pip install gunicorn

gunicorn wildfire_detection.api.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000 \
    --access-logfile logs/api_access.log \
    --error-logfile logs/api_error.log \
    --daemon
```

### Verify the API is running

```bash
curl http://localhost:8000/health
# Expected: {"status":"ok"}

curl http://localhost:8000/api/stats
# Expected: JSON with database counts and model info
```

Open Swagger UI at: `http://your-server-ip:8000/docs`

---

## 10. Systemd Service (Auto-restart on Reboot)

Create the service file:

```bash
sudo nano /etc/systemd/system/wildfire-api.service
```

Paste:

```ini
[Unit]
Description=Wildfire Detection API
After=network.target postgresql.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/path/to/anomalous-wildfire-hotspots-detection
ExecStart=/path/to/anomalous-wildfire-hotspots-detection/venv/bin/gunicorn \
    wildfire_detection.api.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8000
Restart=always
RestartSec=5
EnvironmentFile=/path/to/anomalous-wildfire-hotspots-detection/.env

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable wildfire-api
sudo systemctl start wildfire-api
sudo systemctl status wildfire-api
```

---

## 11. Daily Pipeline Scheduler (Cron)

This runs the full pipeline automatically every 6 hours to fetch new satellite data and update alerts.

```bash
crontab -e
```

Add:

```cron
# Fetch live FIRMS data and run full detection pipeline every 6 hours
0 0,6,12,18 * * * cd /path/to/anomalous-wildfire-hotspots-detection && \
    /path/to/venv/bin/python scripts/daily_pipeline.py \
    >> logs/cron_pipeline.log 2>&1
```

> Replace `/path/to/...` with your actual paths.  
> Logs will accumulate in `logs/cron_pipeline.log`. Consider adding `logrotate` for long-running servers.

---

## 12. Nginx Reverse Proxy (Recommended)

Expose the API on port 80/443 behind Nginx.

```bash
sudo apt install -y nginx

sudo nano /etc/nginx/sites-available/wildfire
```

Paste:

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }
}
```

Enable:

```bash
sudo ln -s /etc/nginx/sites-available/wildfire /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

For HTTPS, use Certbot:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

---

## Verification Checklist

Run these after installation to confirm everything is working:

```bash
# 1. Database tables exist, including the region column
psql $DATABASE_URL -c "\dt"
psql $DATABASE_URL -c "\d raw_hotspots" | grep region

# 2. Trained model exists
ls -lh models/isolation_forest_v1.0.pkl

# 3. API health
curl http://localhost:8000/health

# 4. Map config returns the Indonesia initial camera
curl "http://localhost:8000/api/map/config" | python3 -m json.tool

# 5. Alerts endpoint returns data (world scope, no region param needed)
curl "http://localhost:8000/api/alerts" | python3 -m json.tool | head -40

# 6. Pipeline dry run
python scripts/daily_pipeline.py --dry-run
```

---

## Directory Structure Reference

```
anomalous-wildfire-hotspots-detection/
    src/wildfire_detection/
        api/
            main.py              — FastAPI app entry point
            dependencies.py      — Database session
            schemas.py           — Pydantic response models
            routers/             — 5 router modules (alerts, map, cells, stats, pipeline)
        models/                  — SQLAlchemy table definitions (6 tables)
        services/
            firms_ingestion.py   — FIRMS API client and ingester
    scripts/
        fetch_daily.py           — Pull live FIRMS data
        daily_pipeline.py        — Full pipeline orchestrator
        import_archive.py        — Load historical CSV archive (optional bootstrap)
        migrate_add_region.py    — One-shot migration: add region column (idempotent)
        aggregate_daily.py       — Aggregate hotspots to H3 cells
        build_features.py        — Feature engineering
        train_model.py           — Train Isolation Forest
        score_daily.py           — Score anomalies
        select_top_k.py          — Select alerts with spatial coherence
        enrich_h3_metadata.py    — Geocode H3 cells to province/regency
    models/
        isolation_forest_v1.0.pkl — Trained model artifact
    logs/                        — Runtime logs (created automatically)
    .env                         — Local credentials (gitignored)
    .env.example                 — Template for .env
    requirements.txt
    setup.py
```

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'wildfire_detection'`**  
Run `pip install -e .` from the project root inside the virtual environment.

**`OperationalError: could not connect to server`**  
Check `DATABASE_URL` in `.env`. Verify PostgreSQL is running: `sudo systemctl status postgresql`.

**`400 Forbidden` from FIRMS API**  
Your `FIRMS_API_KEY` is invalid or expired. Regenerate at [https://firms.modaps.eosdis.nasa.gov/api/area/](https://firms.modaps.eosdis.nasa.gov/api/area/).

**`No alerts found` from `/api/alerts`**  
The pipeline has not been run yet. Complete steps 6 and 7 first.

**PostGIS extension missing**  
Connect to the database and run: `CREATE EXTENSION postgis;`
