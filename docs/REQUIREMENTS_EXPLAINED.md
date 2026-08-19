# Requirements Explanation

## What Each Dependency Does (Mapped to Document Architecture)

### 🌐 Core Web Framework
**Purpose:** Build the REST API backend (Step 6-7 in flow)

- **`fastapi`** - Modern Python web framework for building APIs
  - Used for: `/api/alerts`, `/api/map`, `/api/cells/{h3_index}`, `/api/stats`, `/api/pipeline/status` endpoints — see [`API_DOCUMENTATION.md`](./API_DOCUMENTATION.md)
  - Why: Fast, auto-generates API docs, async support
  
- **`uvicorn`** - ASGI server to run FastAPI
  - Used for: Running the web server
  - Why: Production-ready, handles async requests
  
- **`pydantic`** - Data validation
  - Used for: Validating API request/response models
  - Why: Type-safe, automatic validation

---

### 💾 Database
**Purpose:** Store and query hotspot data (Step 1-2 in flow)

- **`sqlalchemy`** - ORM (Object-Relational Mapping)
  - Used for: Database models (`RawHotspot`, `CellDayAggregate`, etc.)
  - Why: Python-friendly database operations, like Laravel's Eloquent
  
- **`psycopg2-binary`** - PostgreSQL driver
  - Used for: Connecting Python to PostgreSQL
  - Why: PostgreSQL is required for PostGIS spatial features
  
- **`geoalchemy2`** - Spatial database extension for SQLAlchemy
  - Used for: PostGIS geometry columns (`POINT`, `POLYGON`)
  - Why: Handle geospatial data (lat/lng, spatial queries)
  
- **`alembic`** - Database migration tooling (listed as a dependency, but not currently wired up)
  - Schema changes are actually applied with `scripts/create_tables_simple.py` (SQLAlchemy `Base.metadata.create_all`) and one-shot scripts like `scripts/migrate_add_region.py`
  - Why: Kept in requirements in case formal Alembic migrations are adopted later

---

### 🗺️ Geospatial
**Purpose:** Spatial indexing and aggregation (Step 2 in flow)

- **`h3`** - Uber's H3 hexagonal spatial indexing
  - Used for: Converting lat/lng to H3 cell IDs, worldwide (not limited to any one country)
  - Why: **Core to the document** - aggregation by H3 cells
  - Example: `h3.latlng_to_cell(-6.2088, 106.8456, 7)`

---

### 📊 Data Processing
**Purpose:** Data manipulation and feature engineering (Step 3 in flow)

- **`pandas`** - Data analysis library
  - Used for: Processing CSV from NASA FIRMS, feature engineering
  - Why: Easy data manipulation, like Excel but in code
  
- **`numpy`** - Numerical computing
  - Used for: Mathematical operations on arrays
  - Why: Required by pandas and scikit-learn

---

### 🤖 Machine Learning
**Purpose:** Anomaly detection (Step 4 in flow)

- **`scikit-learn`** - ML library
  - Used for: **Isolation Forest algorithm** (core to document)
  - Why: Implements the anomaly detection model
  - Example: `IsolationForest(contamination=0.1).fit(features)`
  
- **`joblib`** - Model persistence
  - Used for: Saving/loading trained ML models
  - Why: Don't retrain model every time

---

### 🌐 HTTP & API
**Purpose:** Fetch data from NASA FIRMS (Step 1 in flow)

- **`requests`** - HTTP client
  - Used for: Calling NASA FIRMS API
  - Why: Simple, reliable HTTP requests
  - Example: `requests.get('https://firms.modaps.eosdis.nasa.gov/...')`

---

### 🔧 Utilities
**Purpose:** Configuration management

- **`python-dotenv`** - Environment variables
  - Used for: Loading `.env` file (API keys, database URLs)
  - Why: Keep secrets out of code
  - Example: `DATABASE_URL=postgresql://...`

---

## Mapping to Document Architecture

| Document Step | Requirements Used |
|---------------|-------------------|
| **Step 1: Ingest Raw Data** | `requests`, `pandas`, `h3`, `sqlalchemy`, `psycopg2-binary` |
| **Step 2: Spatial Aggregation** | `sqlalchemy`, `h3`, `geoalchemy2` |
| **Step 3: Feature Engineering** | `pandas`, `numpy`, `sqlalchemy` |
| **Step 4: ML Scoring** | `scikit-learn`, `joblib`, `pandas` |
| **Step 5: Top-K Selection** | `sqlalchemy` |
| **Step 6-7: REST API** | `fastapi`, `uvicorn`, `pydantic`, `sqlalchemy` |
| **Step 8: Dashboard** | (Frontend - React, not Python) |

---

## What's NOT Needed (Removed from Requirements)

❌ **`shapely`** - Complex geometry operations
- Why removed: We only use simple POINT geometry
- PostGIS handles all spatial operations we need

❌ **`httpx`** - Alternative HTTP client
- Why removed: `requests` is sufficient

❌ **`python-multipart`** - File upload handling
- Why removed: We're not uploading files via API

❌ **`python-dateutil`** - Date parsing
- Why removed: Python's built-in `datetime` is enough

---

## Installation Status

✅ **Successfully installed!** All dependencies are now ready.

You can verify by running:
```bash
python -c "import h3, pandas, sklearn, sqlalchemy, fastapi; print('All imports successful!')"
```

---

## Next Steps

Now that dependencies are installed, you can:

1. **Test NASA FIRMS ingestion** - Already working! ✅
2. **Setup PostgreSQL database** - Need to install PostgreSQL + PostGIS
3. **Run database migrations** - Create tables
4. **Ingest real data** - Populate `raw_hotspots` table
5. **Build aggregation pipeline** - Step 2 in flow
6. **Train ML model** - Step 4 in flow

The Python environment is ready! 🚀
