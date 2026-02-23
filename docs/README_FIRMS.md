# NASA FIRMS Data Ingestion

This module fetches wildfire hotspot data from NASA FIRMS API for Indonesia and ingests it into the database.

## Files Created

- **`firms_ingestion.py`** - Main ingestion module with API client
- **`models.py`** - SQLAlchemy database models
- **`requirements.txt`** - Python dependencies
- **`test_firms_api.py`** - Test script to verify API connection

## NASA FIRMS API Details

**Your API Key:** `9ae1e0c7f5a6ae110169c38075aba8aa`

**Endpoint Format:**
```
https://firms.modaps.eosdis.nasa.gov/api/area/csv/{MAP_KEY}/{SOURCE}/{BBOX}/{DAYS}
```

**Indonesia Bounding Box:** `95,-11,141,6` (west, south, east, north)

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

Create `.env` file:
```env
DATABASE_URL=postgresql://user:password@localhost/wildfire_db
FIRMS_API_KEY=9ae1e0c7f5a6ae110169c38075aba8aa
```

## Usage

### Test API Connection

```bash
python test_firms_api.py
```

This will:
- Fetch last 5 days of VIIRS data
- Show data summary and statistics
- Test fetching from all satellites

### Run Data Ingestion

```python
from firms_ingestion import run_daily_ingestion
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Database connection
DATABASE_URL = "postgresql://user:password@localhost/wildfire_db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

# Run ingestion
try:
    count = run_daily_ingestion(
        map_key="9ae1e0c7f5a6ae110169c38075aba8aa",
        db_session=db,
        days=5,  # Fetch last 5 days
        fetch_all_satellites=True  # Fetch from all satellites
    )
    print(f"Inserted {count} hotspots")
finally:
    db.close()
```

### Schedule Daily Ingestion

**Option 1: Cron Job (Linux)**
```bash
# Run every day at 1 AM
0 1 * * * cd /path/to/project && python -c "from firms_ingestion import run_daily_ingestion; ..."
```

**Option 2: Windows Task Scheduler**
- Create task to run Python script daily

**Option 3: Apache Airflow DAG**
```python
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

def ingest_firms_data():
    from firms_ingestion import run_daily_ingestion
    # ... (database setup)
    run_daily_ingestion(map_key="...", db_session=db, days=1)

dag = DAG(
    'firms_daily_ingestion',
    default_args={'start_date': datetime(2026, 1, 1)},
    schedule_interval='0 1 * * *',  # Daily at 1 AM
    catchup=False
)

ingest_task = PythonOperator(
    task_id='ingest_firms',
    python_callable=ingest_firms_data,
    dag=dag
)
```

## Data Flow

```
NASA FIRMS API
    ↓
FIRMSClient.fetch_hotspots()
    ↓
Validate & Parse Data
    ↓
Calculate H3 Index
    ↓
FIRMSIngester.ingest_dataframe()
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
✅ **Configurable** - Adjustable date range and bounding box

## Database Schema

### raw_hotspots Table
```sql
CREATE TABLE raw_hotspots (
    id SERIAL PRIMARY KEY,
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
```

## Next Steps

After ingestion is working:
1. **Step 2:** Create spatial aggregation pipeline (`aggregate_daily_hotspots()`)
2. **Step 3:** Build feature engineering (`build_features_for_date()`)
3. **Step 4:** Train Isolation Forest model
4. **Step 5:** Implement top-K selection
5. **Step 6:** Build REST API
6. **Step 7:** Create dashboard UI

See `wildfire_detection_flow.md` for complete architecture documentation.

## Troubleshooting

**Issue:** API returns empty data
- Check if date range has data (FIRMS has ~3 month history)
- Verify bounding box coordinates
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
