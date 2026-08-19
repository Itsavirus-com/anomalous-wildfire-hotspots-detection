# Wildfire Detection System - Scripts Overview

> [!NOTE]
> The system ingests a single global (`region="world"`) NASA FIRMS dataset — see [`README_FIRMS.md`](./README_FIRMS.md) and `src/wildfire_detection/regions.py`. Indonesia is only the initial map camera position, not a data filter. All tables below carry a `region` column.

## ✅ Scripts Already Created

### 1. `scripts/create_tables_simple.py`

**Purpose:** Database initialization and table creation

**What it does:**
- Connects to PostgreSQL database
- Creates all required tables using SQLAlchemy models
- Verifies PostGIS extension is installed
- Tests database connection

**When to run:**
- Once during initial setup
- After database reset/migration (upgrading an older DB? also run `scripts/migrate_add_region.py`)

**Input:** None (uses `DATABASE_URL` from `.env`)

**Output:** 
- Database tables created:
  - `raw_hotspots` - Raw NASA FIRMS data
  - `cell_day_aggregates` - Daily H3 cell aggregates
  - `cell_day_features` - ML features
  - `cell_day_scores` - Anomaly scores
  - `daily_alerts` - Top-K alerts
  - `h3_cell_metadata` - Reverse-geocoded display names per H3 cell (created by `enrich_h3_metadata.py` on first run)

**Example:**
```bash
python scripts/create_tables_simple.py
```

---

### 2. `scripts/fetch_daily.py`

**Purpose:** Live NASA FIRMS ingestion (primary, recurring data source)

**What it does:**
- Calls the FIRMS `/world` area endpoint for VIIRS SNPP, VIIRS NOAA-20, and MODIS
- Validates and deduplicates rows, computes H3 index
- Inserts into `raw_hotspots` tagged `region="world"`

**When to run:**
- Daily/recurring in production (invoked by `daily_pipeline.py` on cron — see [`INSTALLATION.md`](../INSTALLATION.md#11-daily-pipeline-scheduler-cron))
- Manually to pull the latest data on demand

**Input:**
- Environment: `DATABASE_URL`, `FIRMS_API_KEY`, `H3_RESOLUTION`
- Optional: `--days N` (how many recent days to fetch, default 1)

**Example:**
```bash
python scripts/fetch_daily.py --days 1
```

---

### 3. `scripts/import_archive.py` (optional, one-time bootstrap)

**Purpose:** Import historical NASA FIRMS archive data

**What it does:**
- Loads JSON file from NASA FIRMS Archive Download
- Parses each hotspot record (lat, lng, FRP, confidence, etc.)
- Calculates H3 index (resolution 7) for each point
- Maps JSON field names to database schema
- Inserts records into `raw_hotspots` (`region="world"`) in batches (1000 per commit)

**When to run:**
- Optionally, once during initial setup to backfill historical data before live ingestion (`fetch_daily.py`) has accumulated enough history
- Enables immediate ML training without waiting for the live feed to build up 90 days

**Input:** 
- JSON file: `data/fire_nrt_SV-C2_714486.json` (example archive used during development, 92 days of data)
- Environment: `DATABASE_URL`, `H3_RESOLUTION`

**Output:**
- Historical hotspot records inserted into `raw_hotspots`

**Key Features:**
- H3 spatial indexing (converts lat/lng → hexagon cell ID)
- Confidence mapping (l/n/h → 30/50/100)
- Field name translation (JSON → database schema)
- Error handling with skip counter

**Example:**
```bash
python scripts/import_archive.py
# Imports all records from data/fire_nrt_SV-C2_714486.json
```

---

### 4. `scripts/aggregate_daily.py`

**Purpose:** Spatial aggregation - group hotspots by H3 cell and date

**What it does:**
- Groups raw hotspot points by H3 cell ID and date
- Calculates aggregate statistics per cell-day:
  - `hotspot_count` - Total number of hotspots
  - `total_frp` - Sum of Fire Radiative Power
  - `max_frp` - Maximum FRP in cell
  - `avg_frp` - Average FRP
  - `min_frp` - Minimum FRP
  - Confidence distribution (high/nominal/low counts)
- Inserts into `cell_day_aggregates` table
- Uses UPSERT to handle re-runs (ON CONFLICT DO UPDATE)

**Why needed:**
- ML cannot work with 11,867 individual points (too granular, no spatial context)
- Aggregation reduces data to ~7,765 cell-day records
- Enables spatial analysis (cells as units, not points)
- More efficient for ML processing

**When to run:**
- **Initial setup:** Once to process all historical data
- **Production:** Daily after fetching new data from FIRMS API

**Input:**
- Source: `raw_hotspots` table
- Optional: `--date YYYY-MM-DD` (process specific date only)

**Output:**
- 7,765 cell-day aggregate records
- 5,143 unique H3 cells
- 92 unique dates

**Example:**
```bash
# Process all data
python scripts/aggregate_daily.py

# Process specific date (production use)
python scripts/aggregate_daily.py --date 2026-02-17
```

**Transformation Example:**
```
BEFORE (raw_hotspots):
- Point 1: lat=-0.5, lng=109.3, frp=5.2, date=2025-11-01
- Point 2: lat=-0.501, lng=109.301, frp=3.1, date=2025-11-01
- Point 3: lat=-0.499, lng=109.299, frp=7.5, date=2025-11-01

AFTER (cell_day_aggregates):
Cell 871f2b4a (2025-11-01):
  - hotspot_count: 3
  - total_frp: 15.8 MW
  - max_frp: 7.5 MW
  - avg_frp: 5.27 MW
```

---

### 5. `scripts/build_features.py`

**Purpose:** Feature engineering - add temporal and spatial context for ML

**What it does:**
- Reads `cell_day_aggregates` table
- Calculates **temporal features** for each cell-day:
  - `delta_count_vs_prev_day` - Change from yesterday
  - `ratio_vs_7d_avg` - Ratio compared to 7-day average
- Calculates **spatial features**:
  - `neighbor_activity` - Count of active neighboring cells (using H3 k-ring)
- Inserts into `cell_day_features` table

**Why needed:**
- Raw aggregates lack context (is 47 hotspots normal or unusual?)
- ML needs to understand patterns:
  - **Temporal:** "This cell usually has 12 hotspots, today it has 47 → anomaly!"
  - **Spatial:** "All 6 neighboring cells are also active → fire spreading!"
- Features enable Isolation Forest to detect anomalies

**When to run:**
- **Initial setup:** Once after aggregation
- **Production:** Daily after aggregation

**Input:**
- Source: `cell_day_aggregates` table
- Optional: `--date YYYY-MM-DD` (process specific date only)
- Environment: `H3_RESOLUTION`

**Output:**
- 7,765 feature records in `cell_day_features`
- Each record has 6 features ready for ML

**Feature Details:**

1. **delta_count_vs_prev_day:**
   - Calculation: `today_count - yesterday_count`
   - Example: 47 - 8 = +39 (spike!)
   - Detects sudden increases

2. **ratio_vs_7d_avg:**
   - Calculation: `today_count / avg(last_7_days)`
   - Example: 47 / 12 = 3.92x (4x normal!)
   - Detects deviation from baseline

3. **neighbor_activity:**
   - Calculation: Count of 6 adjacent H3 cells with hotspot_count > 0
   - Example: 6 (all neighbors active → fire spreading)
   - Detects spatial clustering

**Example:**
```bash
# Process all data
python scripts/build_features.py

# Process specific date (production use)
python scripts/build_features.py --date 2026-02-17
```

**Transformation Example:**
```
BEFORE (cell_day_aggregates):
Cell 871f2b4a (2025-11-05):
  - hotspot_count: 47
  - total_frp: 156 MW

AFTER (cell_day_features):
Cell 871f2b4a (2025-11-05):
  - hotspot_count: 47
  - total_frp: 156 MW
  - delta_count_vs_prev_day: +39  (yesterday: 8)
  - ratio_vs_7d_avg: 3.92x  (7-day avg: 12)
  - neighbor_activity: 6  (all neighbors active)
```

---

### 6. `scripts/train_model.py`

**Purpose:** Train Isolation Forest ML model on historical features

**What it does:**
- Loads 90 days of features from `cell_day_features`
- Trains Isolation Forest (unsupervised ML):
  - Learns "normal" patterns from historical data
  - No labeled data needed
  - Detects outliers/anomalies
- Saves trained model to `models/isolation_forest_v1.0.pkl`
- Includes model metadata (training date, version, samples used)

**Why needed:**
- ML model must learn baseline "normal" behavior before detecting anomalies
- Isolation Forest identifies cells that deviate from learned patterns

**When to run:**
- **Initial setup:** Once after feature engineering
- **Production:** Monthly for model retraining (adapt to seasonal changes)

**Input:**
- Source: `cell_day_features` table (90 days minimum)
- Features used: hotspot_count, total_frp, max_frp, delta_count_vs_prev_day, ratio_vs_7d_avg, neighbor_activity
- Environment: `ML_CONTAMINATION`, `ML_N_ESTIMATORS`

**Output:**
- Trained model file: `models/isolation_forest_v1.0.pkl`
- Model metadata: training date, version, sample count
- Training statistics: anomaly rate, score distribution

**ML Parameters:**
- `contamination=0.1` - Expect 10% of data to be anomalies
- `n_estimators=100` - Number of decision trees
- `random_state=42` - Reproducibility

**Example:**
```bash
python scripts/train_model.py
# Trains on last 90 days, saves to models/isolation_forest_v1.0.pkl
```

---

### 7. `scripts/score_daily.py`

**Purpose:** Score cells using trained ML model to detect anomalies

**What it does:**
- Loads trained model from `models/isolation_forest_v1.0.pkl`
- Loads features for target date from `cell_day_features`
- Calculates anomaly score for each cell (lower = more anomalous)
- Saves scores to `cell_day_scores` table

**Why needed:**
- Applies trained model to new data
- Identifies which cells are behaving abnormally
- Scores enable ranking and Top-K selection

**When to run:**
- **Initial setup:** Once to score all historical dates
- **Production:** Daily after feature engineering

**Input:**
- Model: `models/isolation_forest_v1.0.pkl`
- Features: `cell_day_features` table
- Optional: `--date YYYY-MM-DD` (score specific date)

**Output:**
- Anomaly scores in `cell_day_scores` table
- Score range: typically -0.5 to +0.5 (lower = more anomalous)
- Model version tracking

**Scoring Logic:**
- Isolation Forest `decision_function()` returns anomaly score
- Negative scores = anomalies
- Positive scores = normal
- Threshold typically around -0.2

**Example:**
```bash
# Score all dates
python scripts/score_daily.py

# Score specific date (production use)
python scripts/score_daily.py --date 2026-02-17
```

---

### 8. `scripts/select_top_k.py`

**Purpose:** Select top-K most anomalous cells with spatial coherence validation

**What it does:**
- Loads anomaly scores from `cell_day_scores`
- Validates spatial coherence:
  - Checks neighbor activity
  - Identifies anomaly clusters
  - Flags isolated anomalies for manual review
- Calculates hybrid score (ML score + spatial coherence)
- Selects top-K (default: 20) most anomalous cells
- Saves to `daily_alerts` table

**Why needed:**
- Prevent alert fatigue (only top anomalies)
- Ensure anomalies are geographically plausible (not random scatter)
- Prioritize clustered fires over isolated false positives

**When to run:**
- **Initial setup:** Once to generate alerts for historical dates
- **Production:** Daily after scoring

**Input:**
- Scores: `cell_day_scores` table
- Features: `cell_day_features` table (for neighbor_activity)
- Optional: `--date YYYY-MM-DD`, `--k 20` (number of alerts)
- Environment: `TOP_K_ALERTS`

**Output:**
- Top-K alerts in `daily_alerts` table
- Ranked by hybrid score
- Spatial coherence metadata
- Manual review flags for isolated anomalies

**Spatial Coherence Validation:**
- **High coherence:** 4+ active neighbors OR 3+ anomalous neighbors
- **Medium coherence:** 2-3 active neighbors OR 2 anomalous neighbors
- **Low coherence:** 1 active neighbor OR 1 anomalous neighbor
- **Isolated:** 0 neighbors (flagged for manual review)

**Example:**
```bash
# Select top 20 alerts for specific date
python scripts/select_top_k.py --date 2026-02-17 --k 20
```

---

### 9. `scripts/enrich_h3_metadata.py`

**Purpose:** Reverse-geocode H3 cells into human-readable place names

**What it does:**
- Finds H3 cells missing from `h3_cell_metadata` (or all cells with `--all`)
- Reverse-geocodes each cell's center point via Nominatim
- Upserts `display_name`, `geocode_source`, `enriched_at`, `updated_at` into `h3_cell_metadata`
- Self-migrating: adds any missing columns to older databases automatically

**When to run:**
- Automatically as the last step of `daily_pipeline.py`
- Manually with `--all` to backfill every existing cell

**Example:**
```bash
python scripts/enrich_h3_metadata.py       # only new cells
python scripts/enrich_h3_metadata.py --all # backfill everything
```

---

### 10. `scripts/daily_pipeline.py`

**Purpose:** Automated pipeline orchestration

**What it does:**
- Orchestrates the entire workflow:
  1. Fetch new data from NASA FIRMS API (`fetch_daily.py`)
  2. Aggregate new hotspots (`aggregate_daily.py`)
  3. Build features (`build_features.py`)
  4. Score anomalies (`score_daily.py`)
  5. Select top-K alerts (`select_top_k.py`)
  6. Enrich new H3 cells with place names (`enrich_h3_metadata.py`)
- Logs all operations
- Error handling and retry logic

**Why needed:**
- Automates the manual workflow into a single command
- Ensures consistent, repeatable execution
- Production-ready automation

**When to run:**
- **Production:** On a recurring cron schedule — see [`INSTALLATION.md`](../INSTALLATION.md#11-daily-pipeline-scheduler-cron) for the current schedule (every 6 hours)

**Input:**
- Environment: All config from `.env`
- NASA FIRMS API key

**Output:**
- New data in all tables
- Daily alerts generated
- Execution logs

**Example cron:**
```bash
# Example — see INSTALLATION.md for the exact entry in use
0 */6 * * * cd /app && /app/venv/bin/python scripts/daily_pipeline.py >> /var/log/wildfire-pipeline.log 2>&1
```

---

## 📊 Data Flow Summary

```
NASA FIRMS API (world)
    ↓ [fetch_daily.py]  (+ optional one-time [import_archive.py] backfill)
raw_hotspots table (region="world")
    ↓ [aggregate_daily.py]
cell_day_aggregates
    ↓ [build_features.py]
cell_day_features (with context)
    ↓ [train_model.py]
Trained ML Model (isolation_forest_v1.0.pkl)
    ↓ [score_daily.py]
cell_day_scores (anomaly scores)
    ↓ [select_top_k.py]
daily_alerts (Top-K anomalies)
    ↓ [enrich_h3_metadata.py]
h3_cell_metadata (place names)
    ↓ [API/Dashboard]
Visualization
```

---

## 🎯 Execution Order

### Initial Setup (One-time):
1. `create_tables_simple.py` - Create database schema
2. *(optional)* `import_archive.py` - Load historical archive data to bootstrap
3. `fetch_daily.py` - Pull live data
4. `aggregate_daily.py` - Aggregate all historical data
5. `build_features.py` - Calculate features for all dates
6. `train_model.py` - Train ML model on 90 days
7. `score_daily.py` - Score all historical dates
8. `select_top_k.py` - Generate alerts for all dates
9. `enrich_h3_metadata.py --all` - Backfill place names for all cells

### Recurring Production (via cron):
1. `daily_pipeline.py` (orchestrates all below)
   - `fetch_daily.py`
   - `aggregate_daily.py --date <date>`
   - `build_features.py --date <date>`
   - `score_daily.py --date <date>`
   - `select_top_k.py --date <date>`
   - `enrich_h3_metadata.py`

---

## 🔑 Key Concepts

**H3 Spatial Indexing:**
- Divides world into hexagonal cells
- Resolution 7 = ~23 km² per cell
- Enables spatial grouping and neighbor analysis

**Isolation Forest:**
- Unsupervised ML algorithm
- Detects anomalies by isolation (outliers easier to separate)
- No labeled training data needed

**Spatial Coherence:**
- Wildfires spread geographically → anomalies should cluster
- Isolated anomalies = likely false positives
- Validation ensures plausible fire patterns

**Top-K Selection:**
- Prevents alert fatigue (only most critical anomalies)
- Default K=20 (configurable)
- Ranked by hybrid score (ML + spatial coherence)
