# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Enrich H3 Cell Metadata
Reverse-geocodes all unique H3 cells to Indonesian administrative regions
using Nominatim (OpenStreetMap) — free, no API key required.
"""

import os
import sys
import time
from pathlib import Path
from datetime import datetime

import h3
import requests
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import logging

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_DELAY = 1.1   # seconds between requests (Nominatim policy: max 1 req/sec)
USER_AGENT = "wildfire-detection-system/1.0"


def reverse_geocode(lat: float, lng: float) -> dict:
    """
    Reverse geocode lat/lng to Indonesian region using Nominatim.
    Returns dict with province, regency, district, display_name.
    Returns None on failure.
    """
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={
                "lat": lat,
                "lon": lng,
                "format": "json",
                "zoom": 10,
                "addressdetails": 1,
                "accept-language": "id",   # Indonesian names
            },
            headers={"User-Agent": USER_AGENT},
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            return None

        addr = data.get("address", {})

        # Indonesian admin hierarchy:
        # state = provinsi, county = kabupaten, municipality/city = kecamatan
        province = addr.get("state") or addr.get("region")
        regency = (
            addr.get("county") or
            addr.get("city") or
            addr.get("town") or
            addr.get("village")
        )
        district = (
            addr.get("municipality") or
            addr.get("suburb") or
            addr.get("neighbourhood")
        )

        return {
            "province": province,
            "regency": regency,
            "district": district,
            "display_name": data.get("display_name"),
        }

    except Exception as e:
        logger.warning(f"Geocode failed for ({lat:.4f}, {lng:.4f}): {e}")
        return None


def enrich_h3_metadata(force_refresh: bool = False):
    """
    Reverse-geocode all unique H3 cells and store in h3_cell_metadata.

    Args:
        force_refresh: If True, re-geocode cells that already have metadata.
    """
    engine = create_engine(DATABASE_URL)

    # Ensure table exists
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS h3_cell_metadata (
                h3_index        VARCHAR(15) PRIMARY KEY,
                center_lat      FLOAT NOT NULL,
                center_lng      FLOAT NOT NULL,
                province        VARCHAR(100),
                regency         VARCHAR(150),
                district        VARCHAR(150),
                display_name    VARCHAR(500),
                enriched_at     TIMESTAMP DEFAULT NOW(),
                geocode_source  VARCHAR(20) DEFAULT 'nominatim'
            )
        """))
        logger.info("h3_cell_metadata table ready")

    # Get all unique H3 cells from the pipeline
    with engine.connect() as conn:
        if force_refresh:
            result = conn.execute(text(
                "SELECT DISTINCT h3_index FROM cell_day_aggregates ORDER BY h3_index"
            ))
        else:
            # Only cells not yet enriched
            result = conn.execute(text("""
                SELECT DISTINCT a.h3_index
                FROM cell_day_aggregates a
                LEFT JOIN h3_cell_metadata m ON a.h3_index = m.h3_index
                WHERE m.h3_index IS NULL
                ORDER BY a.h3_index
            """))

        cells = [row.h3_index for row in result]

    total = len(cells)
    if total == 0:
        logger.info("✅ All cells already enriched! Nothing to do.")
        return

    logger.info(f"Found {total:,} cells to enrich")
    logger.info(f"Estimated time: ~{total * NOMINATIM_DELAY / 60:.1f} minutes")
    logger.info("(Nominatim rate limit: 1 request/second)\n")

    success = 0
    failed = 0
    unknown = 0

    for i, h3_index in enumerate(cells, 1):
        # Get center coordinates of the hex cell
        lat, lng = h3.cell_to_latlng(h3_index)

        # Reverse geocode
        region = reverse_geocode(lat, lng)

        if region is None:
            geocode_source = "failed"
            province = regency = district = display_name = None
            failed += 1
        elif region.get("province") is None:
            geocode_source = "unknown"
            province = regency = district = None
            display_name = region.get("display_name")
            unknown += 1
        else:
            geocode_source = "nominatim"
            province = region["province"]
            regency = region["regency"]
            district = region["district"]
            display_name = region["display_name"]
            success += 1

        # Upsert into DB
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO h3_cell_metadata
                    (h3_index, center_lat, center_lng, province, regency,
                     district, display_name, enriched_at, geocode_source)
                VALUES
                    (:h3_index, :lat, :lng, :province, :regency,
                     :district, :display_name, :enriched_at, :geocode_source)
                ON CONFLICT (h3_index) DO UPDATE SET
                    province       = EXCLUDED.province,
                    regency        = EXCLUDED.regency,
                    district       = EXCLUDED.district,
                    display_name   = EXCLUDED.display_name,
                    enriched_at    = EXCLUDED.enriched_at,
                    geocode_source = EXCLUDED.geocode_source
            """), {
                "h3_index": h3_index,
                "lat": lat,
                "lng": lng,
                "province": province,
                "regency": regency,
                "district": district,
                "display_name": display_name,
                "enriched_at": datetime.now(),
                "geocode_source": geocode_source,
            })

        # Progress log every 50 cells
        if i % 50 == 0 or i == total:
            pct = i / total * 100
            logger.info(f"  [{i:,}/{total:,}] {pct:.0f}% | ✅ {success} ok | ❓ {unknown} unknown | ❌ {failed} failed")
            if province:
                logger.info(f"    Last: {h3_index[:10]}... → {province} / {regency}")

        # Respect Nominatim rate limit
        time.sleep(NOMINATIM_DELAY)

    logger.info(f"\n✅ Enrichment complete!")
    logger.info(f"  Successful: {success:,} cells")
    logger.info(f"  Unknown region (ocean/border): {unknown:,} cells")
    logger.info(f"  Failed (timeout/error): {failed:,} cells")

    # Show province breakdown
    with engine.connect() as conn:
        provinces = conn.execute(text("""
            SELECT province, COUNT(*) as cnt
            FROM h3_cell_metadata
            WHERE province IS NOT NULL
            GROUP BY province
            ORDER BY cnt DESC
            LIMIT 10
        """)).fetchall()

        logger.info(f"\nTop provinces by cell count:")
        for row in provinces:
            logger.info(f"  {row.province}: {row.cnt:,} cells")

    return success


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Enrich H3 cells with Indonesian region names')
    parser.add_argument('--force', action='store_true', help='Re-geocode all cells (including already enriched)')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("🗺️  H3 Cell Metadata Enrichment (Nominatim)")
    logger.info("=" * 60)

    count = enrich_h3_metadata(force_refresh=args.force)

    print("\n" + "=" * 60)
    print(f"✅ Done! {count:,} cells enriched with province/regency data")
    print("Next step: build FastAPI")
    print("=" * 60)
