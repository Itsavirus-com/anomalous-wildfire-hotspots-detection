# Wildfire Hotspot Anomaly Detection

Detects anomalous wildfire activity worldwide using NASA FIRMS satellite data, H3 spatial aggregation, and Isolation Forest ML.

## How It Works

```
NASA FIRMS (world) → H3 Aggregation → Feature Engineering → Isolation Forest → Top-K Alerts → API
```

1. **Ingest** — Pull global hotspot points from NASA FIRMS `/world`
2. **Aggregate** — Group points into H3 hexagonal cells (~23 km²) by day
3. **Features** — Add temporal (delta, 7d ratio) and spatial (neighbor activity) context
4. **Train** — Isolation Forest learns "normal" patterns from historical data
5. **Score** — Flag cells that deviate significantly from normal
6. **Alert** — Select top-20 most anomalous cells per day with spatial coherence validation
7. **Enrich** — Reverse-geocode new H3 cells to province/regency/district via Nominatim

There is **one data configuration: world**. Region-specific ingest/switching has been removed — every row is tagged `region=world`, and the model, aggregates, and alerts all operate on the same global dataset.

## Map First Load

For the UI, center the camera on Indonesia at first load using the map bootstrap config (this is a **camera position only** — it does not filter the underlying world data):

```bash
curl http://localhost:8000/api/map/config
# or use the `initial_view` field on GET /api/map
```

```json
{
  "data_scope": "world",
  "initial_view": {
    "center_lat": -2.5,
    "center_lng": 118.0,
    "zoom": 5,
    "bbox": { "west": 95, "south": -11, "east": 141, "north": 6 },
    "label": "Indonesia"
  }
}
```

## Quick Start

### 1. Prerequisites

- Python 3.9+
- PostgreSQL 14+ with the PostGIS extension

### 2. Setup

```bash
git clone git@github.com:Itsavirus-com/anomalous-wildfire-hotspots-detection.git
cd anomalous-wildfire-hotspots-detection

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt
pip install -e .
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env with your actual values:
# - DATABASE_URL (PostgreSQL connection)
# - FIRMS_API_KEY (free at https://firms.modaps.eosdis.nasa.gov/api/area/)
```

### 4. Initialize the database

```bash
python scripts/create_tables_simple.py

# Upgrading an existing (pre-world) database? Backfill the region column:
python scripts/migrate_add_region.py
```

`migrate_add_region.py` is safe to re-run — it checks each column/index/constraint before creating it.

### 5. Run the pipeline

The easiest way is the orchestrator, which runs fetch → aggregate → features → score → alerts → enrich in one command:

```bash
python scripts/daily_pipeline.py --days 1
```

Or run each step manually:

```bash
python scripts/fetch_daily.py --days 1        # Pull live FIRMS hotspots (world)
python scripts/aggregate_daily.py             # H3 spatial aggregation
python scripts/build_features.py              # Temporal + spatial features
python scripts/train_model.py                 # Train Isolation Forest (first run only)
python scripts/score_daily.py                 # Score anomalies
python scripts/select_top_k.py                # Select top-K alerts
python scripts/enrich_h3_metadata.py           # Reverse-geocode new H3 cells (optional, rate-limited)
```

> `enrich_h3_metadata.py` calls Nominatim at ~1 request/second, so enriching a large batch of new cells can take a while. Skip it with `--skip enrich` on the orchestrator if you just need fresh alerts quickly.

### 6. Start the API

```bash
uvicorn wildfire_detection.api.main:app --reload
# API docs: http://localhost:8000/docs
```

### 7. Keep data fresh

Nothing refreshes data automatically by itself — the API only reads what's already in the database. Schedule `daily_pipeline.py` (e.g. via cron) to pull new FIRMS data periodically. See [`INSTALLATION.md`](./INSTALLATION.md) for a production cron example (every 6 hours).

## API Endpoints

| Endpoint | Description |
| --- | --- |
| `GET /api/map/config` | Bootstrap config — `data_scope: "world"` + Indonesia `initial_view` |
| `GET /api/map` | Scored H3 cells for a date + `initial_view` |
| `GET /api/map/dates` | Available scored dates |
| `GET /api/alerts` | Top-K anomaly alerts for a date |
| `GET /api/alerts/history` | Alert history for a given H3 cell |
| `GET /api/cells/{h3_index}` | Full detail for one H3 cell |
| `GET /api/cells/{h3_index}/timeseries` | Time series for one H3 cell |
| `GET /api/cells/{h3_index}/neighbors` | Neighboring cell activity |
| `GET /api/stats` | Database + model + alert stats |
| `GET /api/stats/daily` | Daily rollup stats |
| `GET /api/pipeline/status` | Latest data date, row counts, model version |
| `POST /api/pipeline/score` | Trigger re-scoring for a date |

## Project Structure

```
anomalous-wildfire-hotspots-detection/
├── src/wildfire_detection/
│   ├── regions.py               # Single world data-scope config + Indonesia map camera
│   ├── api/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── schemas.py           # Pydantic response models
│   │   ├── dependencies.py      # DB session dependency
│   │   └── routers/             # alerts, map, cells, stats, pipeline
│   ├── models/                  # SQLAlchemy models (region-tagged tables)
│   └── services/                # FIRMS ingestion service
├── scripts/                      # Pipeline scripts
│   ├── create_tables_simple.py  # Create DB tables
│   ├── migrate_add_region.py    # One-shot migration: add region column (idempotent)
│   ├── fetch_daily.py           # Fetch FIRMS hotspots (world)
│   ├── aggregate_daily.py       # H3 spatial aggregation
│   ├── build_features.py        # Feature engineering
│   ├── train_model.py           # Train Isolation Forest
│   ├── score_daily.py           # Score anomalies
│   ├── select_top_k.py          # Select top-K alerts
│   ├── enrich_h3_metadata.py    # Reverse-geocode H3 cells (self-migrates its table)
│   └── daily_pipeline.py        # Orchestrates all of the above
├── data/                          # Raw data files (gitignored)
├── models/                        # Trained ML models (gitignored)
├── logs/                          # Pipeline run logs (gitignored)
├── docs/                          # Extended documentation
├── config/                        # Configuration templates
├── tests/                         # Unit tests
├── .env.example                   # Copy to .env
├── requirements.txt               # Python dependencies
└── setup.py                       # Package configuration
```

## Key Configuration (`.env`)

| Variable           | Description                       | Default |
| ------------------ | --------------------------------- | ------- |
| `DATABASE_URL`     | PostgreSQL connection string      | —       |
| `FIRMS_API_KEY`    | NASA FIRMS API key (free)         | —       |
| `ML_CONTAMINATION` | Expected anomaly fraction (0–0.5) | `0.1`   |
| `ML_N_ESTIMATORS`  | Isolation Forest tree count       | `100`   |
| `TOP_K_ALERTS`     | Alerts per day                    | `20`    |
| `H3_RESOLUTION`    | H3 cell size (7 = ~23 km²)        | `7`     |
| `API_HOST`         | API bind host                     | `0.0.0.0` |
| `API_PORT`         | API bind port                     | `8000`  |

## Tech Stack

| Component        | Technology                    |
| ---------------- | ----------------------------- |
| API              | FastAPI + Uvicorn             |
| Database         | PostgreSQL + PostGIS          |
| Spatial indexing | H3 (Uber)                     |
| ML               | scikit-learn Isolation Forest |
| ORM              | SQLAlchemy                    |
| Geocoding        | Nominatim (OpenStreetMap)     |

Check `GET /api/stats` for live database, model, and alert counts.

## License

MIT
