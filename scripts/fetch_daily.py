# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Fetch Daily Hotspot Data from NASA FIRMS (global /world).
"""

import os
import sys
import argparse
from io import StringIO
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional

import h3
import requests
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import logging

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
load_dotenv()

from wildfire_detection.regions import DATA_REGION, firms_area_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
FIRMS_API_KEY = os.getenv("FIRMS_API_KEY")
H3_RESOLUTION = int(os.getenv("H3_RESOLUTION", 7))
if not 0 <= H3_RESOLUTION <= 15:
    logger.error("H3_RESOLUTION must be 0-15 (got %s). Typical value is 7.", H3_RESOLUTION)
    sys.exit(1)

if not DATABASE_URL:
    logger.error("DATABASE_URL not set in .env"); sys.exit(1)
if not FIRMS_API_KEY or "your_firms" in FIRMS_API_KEY:
    logger.error("FIRMS_API_KEY not set or still placeholder in .env"); sys.exit(1)

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
SATELLITES = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT"]
CONFIDENCE_MAP = {"l": 30, "n": 60, "h": 95}


def fetch_satellite(satellite: str, days: int) -> Optional[pd.DataFrame]:
    area = firms_area_path()
    url = f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/{satellite}/{area}/{days}"
    logger.info(f"  Fetching {satellite} (world, last {days} day(s))...")
    try:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        if not resp.text.strip():
            return None
        df = pd.read_csv(StringIO(resp.text))
        if df.empty:
            return None
        df["source_satellite"] = satellite
        logger.info(f"    → {len(df):,} raw hotspots")
        return df
    except Exception as e:
        logger.warning(f"    → Failed: {type(e).__name__}: {e}")
        return None


def fetch_all_satellites(days: int, satellites: list) -> pd.DataFrame:
    frames = [df for sat in satellites if (df := fetch_satellite(sat, days)) is not None]
    if not frames:
        raise RuntimeError("No data returned from any satellite.")
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop_duplicates(subset=["latitude", "longitude", "acq_date", "acq_time"])


def parse_confidence(raw) -> int:
    if pd.isna(raw):
        return 50
    if isinstance(raw, (int, float)):
        return int(raw)
    return CONFIDENCE_MAP.get(str(raw).strip().lower(), 50)


def parse_acq_datetime(acq_date: str, acq_time) -> Optional[datetime]:
    try:
        time_str = str(int(acq_time)).zfill(4)
        return datetime.strptime(f"{acq_date} {time_str[:2]}:{time_str[2:]}", "%Y-%m-%d %H:%M")
    except Exception:
        return None


def insert_hotspots(df: pd.DataFrame, target_date: Optional[date]) -> dict:
    engine = create_engine(DATABASE_URL)
    stats = {"inserted": 0, "skipped": 0}
    records = []
    for _, row in df.iterrows():
        try:
            lat, lng = float(row["latitude"]), float(row["longitude"])
            frp = float(row["frp"]) if not pd.isna(row.get("frp")) else -1
            if frp < 0 or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                stats["skipped"] += 1
                continue
        except Exception:
            stats["skipped"] += 1
            continue
        acq_dt = parse_acq_datetime(row["acq_date"], row.get("acq_time", 0))
        if acq_dt is None:
            stats["skipped"] += 1
            continue
        # FIRMS "last N days" is a rolling window, not a calendar day.
        # Only apply the ±1 day filter when the caller passed an explicit --date.
        if target_date and abs((acq_dt.date() - target_date).days) > 1:
            stats["skipped"] += 1
            continue
        try:
            h3_idx = h3.latlng_to_cell(lat, lng, H3_RESOLUTION)
        except Exception:
            stats["skipped"] += 1
            continue
        satellite = row.get("source_satellite") or str(row.get("satellite", ""))
        records.append({
            "region": DATA_REGION,
            "lat": lat, "lng": lng,
            "geom": f"SRID=4326;POINT({lng} {lat})",
            "frp": float(row["frp"]) if not pd.isna(row.get("frp")) else None,
            "confidence": parse_confidence(row.get("confidence")),
            "satellite": satellite[:50],
            "acq_datetime": acq_dt,
            "h3_index": h3_idx,
            "ingested_at": datetime.now(),
            "bright_ti4": float(row["bright_ti4"]) if "bright_ti4" in row and not pd.isna(row["bright_ti4"]) else None,
            "bright_ti5": float(row["bright_ti5"]) if "bright_ti5" in row and not pd.isna(row["bright_ti5"]) else None,
            "scan": float(row["scan"]) if "scan" in row and not pd.isna(row["scan"]) else None,
            "track": float(row["track"]) if "track" in row and not pd.isna(row["track"]) else None,
            "instrument": str(row["instrument"])[:20] if "instrument" in row and not pd.isna(row.get("instrument")) else None,
            "version": str(row["version"])[:20] if "version" in row and not pd.isna(row.get("version")) else None,
            "daynight": str(row["daynight"])[:1] if "daynight" in row and not pd.isna(row.get("daynight")) else None,
        })

    if not records:
        logger.warning("No valid records to insert.")
        return stats

    logger.info(f"  {len(records):,} valid records ready to insert")
    with engine.begin() as conn:
        for i in range(0, len(records), 500):
            batch = records[i:i + 500]
            conn.execute(text("""
                INSERT INTO raw_hotspots
                    (region, lat, lng, geom, frp, confidence, satellite, acq_datetime,
                     h3_index, ingested_at, bright_ti4, bright_ti5,
                     scan, track, instrument, version, daynight)
                VALUES
                    (:region, :lat, :lng, ST_GeomFromEWKT(:geom), :frp, :confidence,
                     :satellite, :acq_datetime, :h3_index, :ingested_at,
                     :bright_ti4, :bright_ti5, :scan, :track,
                     :instrument, :version, :daynight)
                ON CONFLICT DO NOTHING
            """), batch)
            stats["inserted"] += len(batch)
    return stats


def fetch_daily(target_date: Optional[date] = None, days: int = 1, satellites: Optional[list] = None) -> int:
    if satellites is None:
        satellites = SATELLITES

    logger.info("NASA FIRMS global fetch (world)")
    logger.info(f"  Target date : {target_date or 'all dates in FIRMS window'}")
    logger.info(f"  Days window : last {days} day(s)")

    df = fetch_all_satellites(days, satellites)
    logger.info(f"  Total raw records fetched: {len(df):,}")
    stats = insert_hotspots(df, target_date)
    logger.info(f"  Inserted : {stats['inserted']:,}  Skipped: {stats['skipped']:,}")
    return stats["inserted"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch global FIRMS hotspot data")
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--satellite", nargs="+", default=None, choices=SATELLITES)
    args = parser.parse_args()
    target_date = datetime.strptime(args.date, "%Y-%m-%d").date() if args.date else None
    inserted = fetch_daily(target_date=target_date, days=args.days, satellites=args.satellite)
    print(f"\n[OK] {inserted:,} records inserted (world)")
    print("Next: python scripts/daily_pipeline.py --skip fetch")
