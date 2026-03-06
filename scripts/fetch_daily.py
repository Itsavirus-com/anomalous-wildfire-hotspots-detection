"""
Fetch Daily Hotspot Data from NASA FIRMS
Pulls today's (or a specific date's) satellite fire detections
and inserts them into raw_hotspots table.

Satellites used (priority order):
    1. VIIRS_SNPP_NRT    — Suomi NPP, 375m resolution
    2. VIIRS_NOAA20_NRT  — NOAA-20, 375m resolution
    3. MODIS_NRT         — Terra & Aqua, 1km resolution

Usage:
    # Fetch yesterday (default — last complete satellite pass)
    python scripts/fetch_daily.py

    # Fetch specific date
    python scripts/fetch_daily.py --date 2026-02-20

    # Fetch last N days (backfill)
    python scripts/fetch_daily.py --days 3

    # Fetch specific satellite only
    python scripts/fetch_daily.py --satellite VIIRS_SNPP_NRT
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

# ─── Path setup ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
load_dotenv()

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
DATABASE_URL  = os.getenv("DATABASE_URL")
FIRMS_API_KEY = os.getenv("FIRMS_API_KEY")
H3_RESOLUTION = int(os.getenv("H3_RESOLUTION", 7))

if not DATABASE_URL:
    logger.error("DATABASE_URL not set in .env"); sys.exit(1)
if not FIRMS_API_KEY or "your_firms" in FIRMS_API_KEY:
    logger.error("FIRMS_API_KEY not set or still placeholder in .env"); sys.exit(1)

# Indonesia bounding box [west, south, east, north]
INDONESIA_BBOX = "95,-11,141,6"

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

SATELLITES = [
    "VIIRS_SNPP_NRT",   # Best resolution (375m), twice/day pass
    "VIIRS_NOAA20_NRT", # Same resolution, complementary orbit
    "MODIS_NRT",        # Older (1km) but extra coverage
]

# Confidence mapping — VIIRS uses l/n/h, MODIS uses integers
CONFIDENCE_MAP = {
    "l": 30,  # low
    "n": 60,  # nominal
    "h": 95,  # high
}


# ─── Fetch ────────────────────────────────────────────────────────────────────

def fetch_satellite(satellite: str, days: int) -> Optional[pd.DataFrame]:
    """
    Fetch CSV data from FIRMS for one satellite.
    Returns DataFrame or None on failure.
    """
    url = f"{FIRMS_BASE_URL}/{FIRMS_API_KEY}/{satellite}/{INDONESIA_BBOX}/{days}"
    logger.info(f"  Fetching {satellite} (last {days} day(s))...")

    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()

        # Empty response = no data for that period
        if not resp.text.strip() or resp.text.strip() == "":
            logger.info(f"    → No data returned for {satellite}")
            return None

        df = pd.read_csv(StringIO(resp.text))

        if df.empty:
            logger.info(f"    → 0 hotspots for {satellite}")
            return None

        df["source_satellite"] = satellite
        logger.info(f"    → {len(df):,} raw hotspots")
        return df

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            logger.error(f"    → 403 Forbidden — check your FIRMS_API_KEY")
        else:
            logger.warning(f"    → HTTP {e.response.status_code} for {satellite}")
        return None
    except Exception as e:
        logger.warning(f"    → Failed: {type(e).__name__}: {e}")
        return None


def fetch_all_satellites(days: int, satellites: list) -> pd.DataFrame:
    """Fetch from all satellites, combine and deduplicate."""
    frames = []
    for sat in satellites:
        df = fetch_satellite(sat, days)
        if df is not None:
            frames.append(df)

    if not frames:
        raise RuntimeError("No data returned from any satellite. Check API key and connectivity.")

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(
        subset=["latitude", "longitude", "acq_date", "acq_time"]
    )
    after = len(combined)
    if before != after:
        logger.info(f"  Deduplication: {before:,} → {after:,} records")

    return combined


# ─── Parse & Validate ─────────────────────────────────────────────────────────

def parse_confidence(raw) -> int:
    """
    Handle both VIIRS letter format (l/n/h) and MODIS integer format.
    Returns integer 0-100.
    """
    if pd.isna(raw):
        return 50
    if isinstance(raw, (int, float)):
        return int(raw)
    raw_str = str(raw).strip().lower()
    return CONFIDENCE_MAP.get(raw_str, 50)


def parse_acq_datetime(acq_date: str, acq_time) -> Optional[datetime]:
    """Parse acq_date (YYYY-MM-DD) + acq_time (HHMM int) into datetime."""
    try:
        time_str = str(int(acq_time)).zfill(4)
        return datetime.strptime(f"{acq_date} {time_str[:2]}:{time_str[2:]}", "%Y-%m-%d %H:%M")
    except Exception:
        return None


def to_h3(lat: float, lng: float, resolution: int) -> Optional[str]:
    """Convert lat/lng to H3 index (handles modern h3 API)."""
    try:
        return h3.latlng_to_cell(lat, lng, resolution)
    except Exception:
        return None


def validate_row(row: pd.Series) -> bool:
    """Basic validation: coordinates inside Indonesia bbox, valid FRP."""
    try:
        lat = float(row["latitude"])
        lng = float(row["longitude"])
        frp = float(row["frp"]) if not pd.isna(row.get("frp")) else -1

        if not (-11 <= lat <= 6):    return False
        if not (95 <= lng <= 141):   return False
        if frp < 0:                  return False
        return True
    except Exception:
        return False


# ─── Insert ───────────────────────────────────────────────────────────────────

def insert_hotspots(df: pd.DataFrame, target_date: Optional[date]) -> dict:
    """
    Parse and upsert hotspot records into raw_hotspots.
    Accepts records within ±1 day of target_date (FIRMS API returns
    a rolling 24h window, not a strict calendar boundary).

    Returns: {"inserted": int, "skipped": int}
    """
    engine = create_engine(DATABASE_URL)
    stats = {"inserted": 0, "skipped": 0}

    records = []
    for _, row in df.iterrows():
        if not validate_row(row):
            stats["skipped"] += 1
            continue

        acq_dt = parse_acq_datetime(row["acq_date"], row.get("acq_time", 0))
        if acq_dt is None:
            stats["skipped"] += 1
            continue

        # Accept records within ±1 day of target (handles rolling window)
        if target_date:
            delta = abs((acq_dt.date() - target_date).days)
            if delta > 1:
                stats["skipped"] += 1
                continue

        h3_idx = to_h3(float(row["latitude"]), float(row["longitude"]), H3_RESOLUTION)
        if h3_idx is None:
            stats["skipped"] += 1
            continue

        confidence = parse_confidence(row.get("confidence"))
        satellite  = row.get("source_satellite") or str(row.get("satellite", ""))

        records.append({
            "lat":          float(row["latitude"]),
            "lng":          float(row["longitude"]),
            "geom":         f"SRID=4326;POINT({row['longitude']} {row['latitude']})",
            "frp":          float(row["frp"]) if not pd.isna(row.get("frp")) else None,
            "confidence":   confidence,
            "satellite":    satellite[:50],
            "acq_datetime": acq_dt,
            "h3_index":     h3_idx,
            "ingested_at":  datetime.now(),
            "bright_ti4":   float(row["bright_ti4"]) if "bright_ti4" in row and not pd.isna(row["bright_ti4"]) else None,
            "bright_ti5":   float(row["bright_ti5"]) if "bright_ti5" in row and not pd.isna(row["bright_ti5"]) else None,
            "scan":         float(row["scan"])  if "scan"  in row and not pd.isna(row["scan"])  else None,
            "track":        float(row["track"]) if "track" in row and not pd.isna(row["track"]) else None,
            "instrument":   str(row["instrument"])[:20] if "instrument" in row and not pd.isna(row.get("instrument")) else None,
            "version":      str(row["version"])[:20]    if "version"    in row and not pd.isna(row.get("version"))    else None,
            "daynight":     str(row["daynight"])[:1]  if "daynight"  in row and not pd.isna(row.get("daynight"))  else None,
        })

    if not records:
        logger.warning("No valid records to insert after validation/filtering.")
        return stats

    logger.info(f"  {len(records):,} valid records ready to insert")

    # Batch upsert — ON CONFLICT DO NOTHING skips true duplicates
    BATCH = 500
    with engine.begin() as conn:
        for i in range(0, len(records), BATCH):
            batch = records[i: i + BATCH]
            conn.execute(text("""
                INSERT INTO raw_hotspots
                    (lat, lng, geom, frp, confidence, satellite, acq_datetime,
                     h3_index, ingested_at, bright_ti4, bright_ti5,
                     scan, track, instrument, version, daynight)
                VALUES
                    (:lat, :lng, ST_GeomFromEWKT(:geom), :frp, :confidence,
                     :satellite, :acq_datetime, :h3_index, :ingested_at,
                     :bright_ti4, :bright_ti5, :scan, :track,
                     :instrument, :version, :daynight)
                ON CONFLICT DO NOTHING
            """), batch)

            stats["inserted"] += len(batch)

    return stats


# ─── Main fetch function ───────────────────────────────────────────────────────

def fetch_daily(
    target_date: Optional[date] = None,
    days: int = 1,
    satellites: Optional[list] = None,
) -> int:
    """
    Fetch FIRMS hotspot data and insert into raw_hotspots.

    Args:
        target_date: Filter to a specific date (None = keep all returned data)
        days: How many days back to request from FIRMS API (1-10)
        satellites: List of satellites to query (None = all 3)

    Returns:
        Number of records inserted.
    """
    if target_date is None:
        target_date = date.today() - timedelta(days=1)
    if satellites is None:
        satellites = SATELLITES

    logger.info("=" * 55)
    logger.info("  🛰️  NASA FIRMS Live Data Fetch")
    logger.info("=" * 55)
    logger.info(f"  Target date : {target_date}")
    logger.info(f"  Days window : last {days} day(s)")
    logger.info(f"  Satellites  : {', '.join(satellites)}")

    # 1. Fetch raw CSVs
    logger.info("\n📡 Fetching satellite data...")
    df = fetch_all_satellites(days, satellites)
    logger.info(f"  Total raw records fetched: {len(df):,}")

    # 2. Insert into DB
    logger.info("\n💾 Inserting into database...")
    stats = insert_hotspots(df, target_date)

    logger.info(f"\n✅ Fetch complete!")
    logger.info(f"  Inserted : {stats['inserted']:,}")
    logger.info(f"  Skipped  : {stats['skipped']:,} (invalid / out of bounds)")

    # 3. Verify
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        count = conn.execute(text("""
            SELECT COUNT(*) FROM raw_hotspots
            WHERE DATE(acq_datetime) = :d
        """), {"d": target_date}).scalar()
    logger.info(f"  Total in DB for {target_date}: {count:,} hotspots")

    return stats["inserted"]


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch live hotspot data from NASA FIRMS API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch yesterday (default)
  python scripts/fetch_daily.py

  # Fetch specific date
  python scripts/fetch_daily.py --date 2026-02-20

  # Backfill last 3 days
  python scripts/fetch_daily.py --days 3

  # VIIRS only (skip MODIS)
  python scripts/fetch_daily.py --satellite VIIRS_SNPP_NRT VIIRS_NOAA20_NRT
        """
    )
    parser.add_argument("--date", type=str, default=None,
                        help="Target date YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--days", type=int, default=1,
                        help="How many days back to fetch from FIRMS (1-10, default: 1)")
    parser.add_argument("--satellite", nargs="+", default=None,
                        choices=SATELLITES,
                        help="Satellites to query (default: all 3)")
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    inserted = fetch_daily(
        target_date=target_date,
        days=args.days,
        satellites=args.satellite,
    )

    print(f"\n{'='*55}")
    print(f"[OK] {inserted:,} records inserted into raw_hotspots")
    print("Next step:")
    print("  python scripts/daily_pipeline.py")
    print("="*55)
