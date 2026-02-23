# Wildfire Detection System

Enterprise-grade wildfire anomaly detection system for Indonesia using ML-powered spatial analysis.

## Project Structure

```
wildfire_detection/
├── src/
│   └── wildfire_detection/     # Main application package
│       ├── __init__.py
│       ├── api/                # FastAPI endpoints
│       ├── models/             # Database models
│       ├── services/           # Business logic
│       └── utils/              # Helper functions
├── scripts/                    # Standalone scripts
│   ├── import_archive.py
│   ├── train_model.py
│   └── daily_pipeline.py
├── config/                     # Configuration files
│   ├── .env.example
│   └── database.py
├── tests/                      # Unit tests
├── docs/                       # Documentation
├── data/                       # Data files (gitignored)
├── logs/                       # Log files (gitignored)
├── models/                     # Trained ML models (gitignored)
├── requirements.txt
├── setup.py
└── README.md
```

## Quick Start

### 1. Setup Environment

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Database

```bash
# Copy example config
cp config/.env.example .env

# Edit .env with your credentials
# DATABASE_URL=postgresql://user:password@localhost/wildfire_db
# FIRMS_API_KEY=your_nasa_firms_key
```

### 3. Import Archive Data

```bash
# Import 92 days of historical data
python scripts/import_archive.py
```

### 4. Train ML Model

```bash
# Train Isolation Forest
python scripts/train_model.py
```

### 5. Run API Server

```bash
# Start FastAPI server
uvicorn src.wildfire_detection.api.main:app --reload
```

## Documentation

- [Complete System Flow](docs/wildfire_detection_flow.md)
- [Implementation Timeline](docs/IMPLEMENTATION_TIMELINE.md)
- [Data Dictionary](docs/DATA_DICTIONARY.md)
- [Requirements Explained](docs/REQUIREMENTS_EXPLAINED.md)
- [Tech Lead Discussion](docs/TECH_LEAD_DISCUSSION.md)

## Features

- ✅ NASA FIRMS data ingestion
- ✅ H3 hexagonal spatial indexing
- ✅ ML-powered anomaly detection (Isolation Forest)
- ✅ Rule-based detection (fallback)
- ✅ Top-K ranking system
- ✅ Interactive dashboard
- ✅ RESTful API
- ✅ Daily automated pipeline

## Tech Stack

- **Backend:** Python 3.9+, FastAPI
- **Database:** PostgreSQL + PostGIS
- **ML:** scikit-learn (Isolation Forest)
- **Spatial:** H3, GeoAlchemy2
- **Frontend:** React + Leaflet.js

## License

MIT
