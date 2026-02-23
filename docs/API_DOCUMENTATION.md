# Wildfire Detection API - Endpoint Documentation

Base URL: `http://localhost:8000/api`

---

## 1. 🚨 Alerts Endpoints

### `GET /api/alerts`
Get top-K anomaly alerts for a specific date.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `date` | string | today | Date (YYYY-MM-DD) |
| `k` | int | 20 | Number of alerts |
| `coherence` | string | all | Filter: `high`, `medium`, `low`, `isolated` |

**Response:**
```json
{
  "date": "2026-02-17",
  "total_alerts": 20,
  "alerts": [
    {
      "rank": 1,
      "h3_index": "871f2b4a5ffffff",
      "anomaly_score": -0.4521,
      "hybrid_score": 0.4612,
      "spatial_coherence_level": "high",
      "needs_manual_review": false,
      "coherence_reasons": ["6/6 neighbors active", "3 anomalous neighbors"],
      "hotspot_count": 47,
      "total_frp": 156.3,
      "ratio_vs_7d_avg": 3.92,
      "center_lat": -0.512,
      "center_lng": 109.312
    }
  ]
}
```

---

### `GET /api/alerts/history`
Get alert history for a specific H3 cell.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `h3_index` | string | H3 cell ID |
| `days` | int | Last N days (default: 30) |

**Response:**
```json
{
  "h3_index": "871f2b4a5ffffff",
  "alerts": [
    { "date": "2026-02-17", "rank": 1, "hybrid_score": 0.46 },
    { "date": "2026-02-10", "rank": 5, "hybrid_score": 0.31 }
  ]
}
```

---

## 2. 🗺️ Map Endpoints

### `GET /api/map`
Get all scored cells for a date (for map rendering).
Used by the frontend to render all H3 hexagons with colors.

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `date` | string | today | Date (YYYY-MM-DD) |
| `min_score` | float | none | Filter by min anomaly score |

**Response:**
```json
{
  "date": "2026-02-17",
  "total_cells": 312,
  "cells": [
    {
      "h3_index": "871f2b4a5ffffff",
      "anomaly_score": -0.4521,
      "is_anomaly": true,
      "hotspot_count": 47,
      "total_frp": 156.3,
      "center_lat": -0.512,
      "center_lng": 109.312
    }
  ]
}
```

---

### `GET /api/map/dates`
Get list of available dates that have map data.

**Response:**
```json
{
  "dates": ["2025-11-01", "2025-11-02", "...", "2026-01-31"],
  "total": 92,
  "earliest": "2025-11-01",
  "latest": "2026-01-31"
}
```

---

## 3. 🔍 Cell Endpoints

### `GET /api/cells/{h3_index}`
Get full details for a specific H3 cell.

**Path Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `h3_index` | string | H3 cell ID (e.g. `871f2b4a5ffffff`) |

**Query Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `date` | string | latest | Specific date to show |

**Response:**
```json
{
  "h3_index": "871f2b4a5ffffff",
  "center_lat": -0.512,
  "center_lng": 109.312,
  "date": "2026-02-17",
  "aggregate": {
    "hotspot_count": 47,
    "total_frp": 156.3,
    "max_frp": 42.1,
    "avg_frp": 3.3
  },
  "features": {
    "delta_count_vs_prev_day": 39,
    "ratio_vs_7d_avg": 3.92,
    "neighbor_activity": 6
  },
  "score": {
    "anomaly_score": -0.4521,
    "is_anomaly": true,
    "model_version": "v1.0"
  },
  "alert": {
    "rank": 1,
    "hybrid_score": 0.4612,
    "spatial_coherence_level": "high",
    "needs_manual_review": false
  }
}
```

---

### `GET /api/cells/{h3_index}/timeseries`
Get 30-day hotspot time series for a cell (for chart).

**Response:**
```json
{
  "h3_index": "871f2b4a5ffffff",
  "timeseries": [
    { "date": "2026-01-18", "hotspot_count": 8, "total_frp": 22.1, "is_anomaly": false },
    { "date": "2026-01-19", "hotspot_count": 6, "total_frp": 18.4, "is_anomaly": false },
    { "date": "2026-02-17", "hotspot_count": 47, "total_frp": 156.3, "is_anomaly": true }
  ]
}
```

---

### `GET /api/cells/{h3_index}/neighbors`
Get activity of neighboring cells for a specific date.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `date` | string | Date (YYYY-MM-DD) |

**Response:**
```json
{
  "h3_index": "871f2b4a5ffffff",
  "date": "2026-02-17",
  "neighbors": [
    {
      "h3_index": "871f2b4a1ffffff",
      "hotspot_count": 23,
      "is_anomaly": true,
      "anomaly_score": -0.31
    }
  ],
  "active_neighbor_count": 6,
  "anomalous_neighbor_count": 3
}
```

---

## 4. 📊 Stats Endpoints

### `GET /api/stats`
Overall system statistics.

**Response:**
```json
{
  "database": {
    "total_hotspots": 11867,
    "total_cell_days": 7765,
    "date_range": {
      "start": "2025-11-01",
      "end": "2026-01-31"
    },
    "unique_cells": 5143
  },
  "model": {
    "version": "v1.0",
    "trained_at": "2026-02-18T12:56:12",
    "training_samples": 5291,
    "contamination": 0.1
  },
  "alerts": {
    "total": 649,
    "by_coherence": {
      "high": 120,
      "medium": 280,
      "low": 190,
      "isolated": 59
    },
    "needs_review": 59
  }
}
```

---

### `GET /api/stats/daily`
Daily statistics across date range.

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `start` | string | Start date |
| `end` | string | End date |

**Response:**
```json
{
  "daily": [
    {
      "date": "2026-02-17",
      "total_hotspots": 423,
      "active_cells": 89,
      "anomalies_detected": 12,
      "top_alert_score": 0.46
    }
  ]
}
```

---

## 5. ⚙️ Pipeline Endpoints

### `POST /api/pipeline/score`
Trigger re-scoring for a specific date (admin use).

**Request Body:**
```json
{
  "date": "2026-02-17"
}
```

**Response:**
```json
{
  "status": "success",
  "scored": 89,
  "date": "2026-02-17"
}
```

---

### `GET /api/pipeline/status`
Check pipeline health and last run time.

**Response:**
```json
{
  "status": "healthy",
  "last_import": "2026-02-23T01:00:00",
  "last_scoring": "2026-02-23T01:05:00",
  "latest_data_date": "2026-02-22",
  "model_version": "v1.0"
}
```

---

## 📦 Summary Table

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/alerts` | Daily top-K alerts |
| GET | `/api/alerts/history` | Cell alert history |
| GET | `/api/map` | All cells for map rendering |
| GET | `/api/map/dates` | Available dates |
| GET | `/api/cells/{h3_index}` | Single cell full detail |
| GET | `/api/cells/{h3_index}/timeseries` | 30-day chart data |
| GET | `/api/cells/{h3_index}/neighbors` | Neighbor activity |
| GET | `/api/stats` | System overview |
| GET | `/api/stats/daily` | Daily breakdown |
| POST | `/api/pipeline/score` | Trigger re-score |
| GET | `/api/pipeline/status` | Pipeline health |

---

## 🔧 Tech Stack
- **Framework:** FastAPI
- **ORM:** SQLAlchemy
- **Docs:** Auto-generated at `/docs` (Swagger UI)
- **Port:** 8000
