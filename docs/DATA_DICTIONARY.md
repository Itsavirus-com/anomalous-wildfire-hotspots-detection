# NASA FIRMS Data Dictionary

## Data Fields from NASA FIRMS API

Based on the test results, NASA FIRMS provides the following fields for each hotspot:

### 📍 Location Data
- **`latitude`** - Hotspot latitude coordinate (-11 to 6 for Indonesia)
- **`longitude`** - Hotspot longitude coordinate (95 to 141 for Indonesia)

### 🔥 Fire Intensity Metrics
- **`frp`** - **Fire Radiative Power (MW)** - KEY METRIC
  - Range in test: 0.22 - 158.67 MW
  - Average: 4.84 MW
  - **This is the main metric for fire intensity**
  - Used in feature engineering for anomaly detection

### 🌡️ Temperature Data
- **`bright_ti4`** - Brightness temperature band I-4 (Kelvin)
- **`bright_ti5`** - Brightness temperature band I-5 (Kelvin)

### 📊 Detection Quality
- **`confidence`** - Detection confidence level:
  - `l` = low (20 hotspots in test)
  - `n` = nominal (677 hotspots in test)
  - `h` = high (6 hotspots in test)

### 📅 Temporal Data
- **`acq_date`** - Acquisition date (YYYY-MM-DD format)
  - Test range: 2026-02-05 to 2026-02-08
- **`acq_time`** - Acquisition time (HHMM format, UTC)
  - Example: 416 = 04:16 UTC

### 🛰️ Satellite Information
- **`satellite`** - Satellite identifier
  - `N` = Suomi NPP (VIIRS)
  - `J1` = NOAA-20 (VIIRS)
  - `T` = Terra (MODIS)
  - `A` = Aqua (MODIS)
- **`instrument`** - Sensor instrument
  - `VIIRS` - Visible Infrared Imaging Radiometer Suite (375m resolution)
  - `MODIS` - Moderate Resolution Imaging Spectroradiometer (1km resolution)
- **`version`** - Data version (e.g., "2.0NRT" = Near Real-Time)

### 📐 Pixel Size
- **`scan`** - Along-scan pixel size (km)
- **`track`** - Along-track pixel size (km)

### 🌓 Day/Night
- **`daynight`** - Detection time
  - `D` = Day
  - `N` = Night

---

## Key Fields for Anomaly Detection

Based on the document, these are the critical fields for ML:

### Primary Metrics (for aggregation)
1. **`frp`** - Fire Radiative Power (main intensity metric)
2. **`confidence`** - Detection quality filter
3. **`acq_date`** - For daily aggregation
4. **`latitude`, `longitude`** - For H3 spatial aggregation

### Derived Features (calculated during feature engineering)
- **Hotspot count per cell-day** - COUNT(*) GROUP BY h3_index, date
- **Total FRP per cell-day** - SUM(frp) GROUP BY h3_index, date
- **Max FRP per cell-day** - MAX(frp) GROUP BY h3_index, date
- **Average confidence** - AVG(confidence) GROUP BY h3_index, date

### Temporal Features
- **Delta vs previous day** - Compare with yesterday's metrics
- **Ratio vs 7-day average** - Compare with rolling 7-day average
- **Neighbor activity** - Count hotspots in surrounding H3 cells

---

## Data Quality Notes

From test results (703 hotspots over 5 days):

✅ **Good Coverage**
- Date range: 4 days of data
- Geographic spread across Indonesia
- Mix of confidence levels (mostly nominal)

⚠️ **Considerations**
- FRP range is wide (0.22 - 158.67 MW)
  - Low FRP might be false positives
  - High FRP indicates intense fires
- Most detections are "nominal" confidence (96%)
- All from VIIRS satellite 'N' (Suomi NPP)

🔍 **Recommended Filters**
- Minimum FRP threshold: 1.0 MW (filter out very weak signals)
- Confidence filter: Keep 'n' and 'h', optionally exclude 'l'
- Date range: FIRMS keeps ~3 months of NRT data

---

## Mapping to Database Schema

```python
# NASA FIRMS field → Database column
{
    'latitude': 'lat',
    'longitude': 'lng',
    'frp': 'frp',  # Fire Radiative Power
    'confidence': 'confidence',  # Convert l/n/h to 30/50/100
    'acq_date + acq_time': 'acq_datetime',  # Combine into timestamp
    'satellite': 'satellite',
    'h3.geo_to_h3(lat, lng, 7)': 'h3_index',  # Calculate H3 cell
    'POINT(lng, lat)': 'geom',  # PostGIS geometry
    
    # Additional fields
    'bright_ti4': 'bright_ti4',
    'bright_ti5': 'bright_ti5',
    'scan': 'scan',
    'track': 'track',
    'instrument': 'instrument',
    'version': 'version',
    'daynight': 'daynight'
}
```

---

## Example Aggregation Query

```sql
-- Daily aggregation by H3 cell (Step 2 in flow)
SELECT 
    h3_index,
    DATE(acq_datetime) as date,
    COUNT(*) as hotspot_count,
    SUM(frp) as total_frp,
    MAX(frp) as max_frp,
    AVG(confidence) as avg_confidence
FROM raw_hotspots
WHERE DATE(acq_datetime) = '2026-02-08'
  AND frp >= 1.0  -- Filter weak signals
  AND confidence IN (50, 100)  -- Only nominal and high confidence
GROUP BY h3_index, DATE(acq_datetime);
```

This produces the cell-day aggregates needed for ML feature engineering.
