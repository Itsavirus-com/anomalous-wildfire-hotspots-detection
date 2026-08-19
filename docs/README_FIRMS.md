# NASA FIRMS Data Ingestion

This module fetches wildfire hotspot data from the NASA FIRMS API for the **whole world** and ingests it into the database. Every ingested row is tagged `region="world"` — there is a single global data scope, no per-country filtering.

Indonesia is only used as the **first-load map camera position** (see `src/wildfire_detection/regions.py` and `GET /api/map/config`) — it does not limit which hotspots are fetched or stored.

## Files

- **`src/wildfire_detection/services/firms_ingestion.py`** - `FIRMSClient` / `FIRMSIngester` used by the API's background ingestion helpers
- **`scripts/fetch_daily.py`** - Standalone CLI script used by `daily_pipeline.py` / cron to pull live FIRMS data
- **`src/wildfire_detection/regions.py`** - Single `DATA_REGION="world"` config + Indonesia map camera constants
- **`tests/test_firms_api.py`** - Smoke test for the world-only config and FIRMS ingestion helpers

## NASA FIRMS API Details

**API Key:** set `FIRMS_API_KEY` in your `.env` (get a free key at https://firms.modaps.eosdis.nasa.gov/api/area/). Never commit real keys to docs or git history.

**Endpoint Format:**
```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{AREA}/{DAYS}
```

`{AREA}` is always `world` (see `firms_area_path()` in `regions.py`) — there is no bounding box filter.

**Available Satellites:**
- `VIIRS_SNPP_NRT` - Suomi NPP (375m resolution)
- `VIIRS_NOAA20_NRT` - NOAA-20 (375m resolution)
- `MODIS_NRT` - Terra & Aqua (1km resolution)

**Data Fields:**
- `latitude`, `longitude` - Hotspot coordinates
- `frp` - Fire Radiative Power (MW)
- `confidence` - Detection confidence (l/n/h = low/nominal/high)
- `acq_date`, `acq_time` - Acquisition date and time
- `satellite`, `instrument` - Satellite and instrument name
- `bright_ti4`, `bright_ti5` - Brightness temperature
- `scan`, `track` - Pixel size
- `daynight` - Day or night detection

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Setup PostgreSQL Database

```sql
-- Create database
CREATE DATABASE wildfire_db;

-- Enable PostGIS extension
CREATE EXTENSION postgis;

-- Create tables (run models.py with Alembic or manually)
```

### 3. Configure Database Connection

```bash
cp .env.example .env
```

```env
DATABASE_URL=postgresql://user:password@localhost/wildfire_db
FIRMS_API_KEY=your_firms_api_key_here
```

## Usage

### Fetch live world data

```bash
python scripts/fetch_daily.py --days 1
```

This fetches the last N day(s) from VIIRS SNPP, VIIRS NOAA-20, and MODIS for the `/world` area, validates/deduplicates rows, and inserts them into `raw_hotspots` tagged `region="world"`.

### Run the full pipeline

```bash
python scripts/daily_pipeline.py --days 1
```

Runs fetch → aggregate → features → score → alerts → enrich in one command. See the root [`README.md`](../README.md) for all steps and flags.

### Schedule recurring ingestion

Production runs `daily_pipeline.py` on a cron schedule — see [`INSTALLATION.md`](../INSTALLATION.md#11-daily-pipeline-scheduler-cron) for the current cron entry (every 6 hours). The `.github/workflows/deploy.yml` GitHub Action only restarts the API on deploy; it does **not** run the pipeline.

## Data Flow

```
NASA FIRMS API (/world)
    ↓
fetch_satellite() / FIRMSClient.fetch_hotspots()
    ↓
Validate & parse data (coords, FRP, confidence, acq datetime)
    ↓
Calculate H3 index
    ↓
insert_hotspots() / FIRMSIngester.ingest_dataframe()  — tags region="world"
    ↓
PostgreSQL (raw_hotspots table)
```

## Features

✅ **Multi-Satellite Support** - Fetch from VIIRS and MODIS
✅ **Data Validation** - Validates coordinates, FRP, confidence
✅ **H3 Spatial Indexing** - Pre-computes H3 hexagon IDs
✅ **PostGIS Integration** - Stores geometry for spatial queries
✅ **Duplicate Detection** - Removes duplicate hotspots
✅ **Error Handling** - Robust error handling and logging
✅ **Configurable** - Adjustable date range and satellite selection

## Database Schema

### raw_hotspots Table
```sql
CREATE TABLE raw_hotspots (
    id SERIAL PRIMARY KEY,
    region VARCHAR(32) NOT NULL DEFAULT 'world',
    lat DECIMAL(10, 7) NOT NULL,
    lng DECIMAL(10, 7) NOT NULL,
    geom GEOMETRY(Point, 4326),
    frp DECIMAL(8, 2),
    confidence INTEGER,
    satellite VARCHAR(50),
    acq_datetime TIMESTAMP NOT NULL,
    h3_index VARCHAR(15) NOT NULL,
    ingested_at TIMESTAMP DEFAULT NOW(),
    bright_ti4 DECIMAL(6, 2),
    bright_ti5 DECIMAL(6, 2),
    scan DECIMAL(4, 2),
    track DECIMAL(4, 2),
    instrument VARCHAR(20),
    version VARCHAR(20),
    daynight VARCHAR(1)
);

CREATE INDEX idx_raw_h3_date ON raw_hotspots(h3_index, DATE(acq_datetime));
CREATE INDEX idx_raw_datetime ON raw_hotspots(acq_datetime);
CREATE INDEX ix_raw_hotspots_region_date ON raw_hotspots(region, acq_datetime);
```

If you're upgrading a database created before the `region` column existed, run `python scripts/migrate_add_region.py` (idempotent).

## Next Steps

The full pipeline already exists — see the root [`README.md`](../README.md) Quick Start and [`Wildfire Detection Flow.md`](./Wildfire%20Detection%20Flow.md) for the complete architecture:

1. `scripts/aggregate_daily.py` — H3 spatial aggregation
2. `scripts/build_features.py` — feature engineering
3. `scripts/train_model.py` — train Isolation Forest
4. `scripts/score_daily.py` + `scripts/select_top_k.py` — score + top-K alerts
5. `scripts/enrich_h3_metadata.py` — reverse-geocode H3 cells
6. FastAPI app under `src/wildfire_detection/api/`

## Troubleshooting

**Issue:** API returns empty data
- Check if date range has data (FIRMS has ~3 month history)
- Check API key is valid

**Issue:** Database connection fails
- Verify PostgreSQL is running
- Check DATABASE_URL is correct
- Ensure PostGIS extension is installed

**Issue:** H3 import error
- Install h3: `pip install h3`
- On Windows, may need Visual C++ Build Tools

## Resources

- [NASA FIRMS Documentation](https://firms.modaps.eosdis.nasa.gov/api/)
- [H3 Documentation](https://h3geo.org/)
- [PostGIS Documentation](https://postgis.net/)
