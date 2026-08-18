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

## Map first load

There is **one data configuration: world**.

For the UI, center the camera on Indonesia at first load using:

```bash
curl http://localhost:8000/api/map/config
# or use initial_view from GET /api/map
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

```bash
python scripts/fetch_daily.py --days 1
python scripts/train_model.py
python scripts/daily_pipeline.py --skip fetch

curl http://localhost:8000/api/alerts
curl http://localhost:8000/api/map
```

## Quick Start

### 1. Prerequisites

- Python 3.9+
- PostgreSQL with PostGIS extension

### 2. Setup

```bash
git clone https://github.com/yourusername/wildfire-detection.git
cd wildfire-detection

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

### 4. Initialize database

```bash
python scripts/create_tables_simple.py
python scripts/migrate_add_region.py   # if upgrading an existing DB
```

### 5. Run initial pipeline (live world data)

```bash
python scripts/fetch_daily.py --days 1

# Build ML pipeline
python scripts/aggregate_daily.py
python scripts/build_features.py
python scripts/train_model.py
python scripts/score_daily.py
python scripts/select_top_k.py
```

### 6. Start API

```bash
uvicorn wildfire_detection.api.main:app --reload
# API docs: http://localhost:8000/docs
```

## Project Structure

```
wildfire-detection/
├── src/wildfire_detection/     # Python package (src layout)
│   ├── api/                    # FastAPI endpoints
│   ├── models/                 # SQLAlchemy database models
│   ├── services/               # Business logic (FIRMS ingestion etc.)
│   └── utils/                  # Helper utilities
├── scripts/                    # Pipeline scripts (run in order)
│   ├── create_tables_simple.py # Step 0: Create DB tables
│   ├── import_archive.py       # Step 1: Import historical data
│   ├── aggregate_daily.py      # Step 2: H3 spatial aggregation
│   ├── build_features.py       # Step 3: Feature engineering
│   ├── train_model.py          # Step 4: Train Isolation Forest
│   ├── score_daily.py          # Step 5: Score anomalies
│   └── select_top_k.py         # Step 6: Select top-K alerts
├── data/                       # Raw data files (gitignored)
├── models/                     # Trained ML models (gitignored)
├── docs/                       # Documentation
│   ├── wildfire_detection_flow.md  # Full system flow
│   └── SETUP_GUIDE.md          # Detailed setup instructions
├── config/                     # Configuration templates
├── tests/                      # Unit tests
├── .env.example                # Copy to .env
├── requirements.txt            # Python dependencies
└── setup.py                    # Package configuration
```

## Key Configuration (`.env`)

| Variable           | Description                       | Default |
| ------------------ | --------------------------------- | ------- |
| `DATABASE_URL`     | PostgreSQL connection string      | —       |
| `FIRMS_API_KEY`    | NASA FIRMS API key (free)         | —       |
| `ML_CONTAMINATION` | Expected anomaly fraction (0–0.5) | `0.1`   |
| `TOP_K_ALERTS`     | Alerts per day                    | `20`    |
| `H3_RESOLUTION`    | H3 cell size (7 = ~23 km²)        | `7`     |

## Tech Stack

| Component        | Technology                    |
| ---------------- | ----------------------------- |
| API              | FastAPI + Uvicorn             |
| Database         | PostgreSQL + PostGIS          |
| Spatial indexing | H3 (Uber)                     |
| ML               | scikit-learn Isolation Forest |
| ORM              | SQLAlchemy                    |

## Data Pipeline Stats (Indonesia, Nov 2025 – Jan 2026)

- 11,867 raw hotspot records
- 7,765 cell-day aggregates
- 752 anomalies detected (9.7%)
- 649 daily alerts selected

## License

MIT
