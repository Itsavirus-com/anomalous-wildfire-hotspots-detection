# Wildfire Detection System — Docs Index

Enterprise-grade wildfire anomaly detection system. Ingests NASA FIRMS hotspot data **for the whole world** (`region="world"`) and surfaces anomalies via H3 spatial aggregation + Isolation Forest. Indonesia is only used as the **initial map camera position**, not a data filter — see the root [`README.md`](../README.md) for the full Quick Start.

## Project Structure

```
anomalous-wildfire-hotspots-detection/
├── src/
│   └── wildfire_detection/     # Main application package
│       ├── regions.py          # DATA_REGION="world" + Indonesia map camera config
│       ├── api/                # FastAPI app + routers
│       ├── models/             # SQLAlchemy models
│       └── services/           # FIRMS ingestion client
├── scripts/                    # Standalone pipeline scripts
│   ├── fetch_daily.py          # Live FIRMS ingestion (world)
│   ├── daily_pipeline.py       # Orchestrates the full pipeline
│   ├── migrate_add_region.py   # One-shot migration for older DBs
│   ├── enrich_h3_metadata.py   # Reverse-geocode H3 cells
│   └── ...                     # aggregate/build_features/train/score/select_top_k
├── config/                     # database.py helper
├── tests/                      # Unit tests
├── docs/                       # Documentation (this folder)
├── data/, logs/, models/       # Runtime artifacts (gitignored)
├── .env.example                # Template for .env (project root)
├── requirements.txt
├── setup.py
└── README.md
```

## Quick Start

See the root [`README.md`](../README.md) for the up-to-date Quick Start (venv, `.env`, `create_tables_simple.py` + `migrate_add_region.py`, `fetch_daily.py` / `daily_pipeline.py`, and starting the API). The steps below are just a pointer, not the source of truth.

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt && pip install -e .
cp .env.example .env   # fill in DATABASE_URL, FIRMS_API_KEY
python scripts/create_tables_simple.py
python scripts/fetch_daily.py --days 1
python scripts/train_model.py
uvicorn wildfire_detection.api.main:app --reload
```

## Documentation

- [Complete System Flow](./Wildfire%20Detection%20Flow.md)
- [Backend Scripts Overview](./BACKEND_OVERVIEW.md)
- [API Documentation](./API_DOCUMENTATION.md)
- [Data Dictionary](./DATA_DICTIONARY.md)
- [Setup Guide](./SETUP_GUIDE.md)
- [FIRMS Ingestion Notes](./README_FIRMS.md)
- [Implementation Timeline](./IMPLEMENTATION_TIMELINE.md)
- [Requirements Explained](./REQUIREMENTS_EXPLAINED.md)

## Features

- ✅ NASA FIRMS data ingestion (global, single `region="world"` scope)
- ✅ H3 hexagonal spatial indexing
- ✅ ML-powered anomaly detection (Isolation Forest)
- ✅ Top-K ranking with spatial coherence
- ✅ H3 cell enrichment (reverse-geocoded place names)
- ✅ RESTful API with an Indonesia-centered initial map view
- ✅ Automated pipeline via cron (`daily_pipeline.py`)

## Tech Stack

- **Backend:** Python 3.10+, FastAPI
- **Database:** PostgreSQL + PostGIS
- **ML:** scikit-learn (Isolation Forest)
- **Spatial:** H3, GeoAlchemy2

## License

MIT
