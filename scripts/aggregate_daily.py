# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Daily Aggregation Script
Groups raw hotspots by region + H3 cell + date
"""

import os
import sys
from pathlib import Path
from datetime import datetime, date
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from wildfire_detection.regions import DATA_REGION

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)


def aggregate_daily(target_date: date = None):
    region_id = DATA_REGION
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        if target_date:
            logger.info(f"Aggregating data for {target_date} ({region_id})...")
            date_filter = "AND DATE(acq_datetime) = :target_date"
            params = {"target_date": target_date, "region": region_id}
        else:
            logger.info(f"Aggregating all data ({region_id})...")
            date_filter = ""
            params = {"region": region_id}

        query = f"""
        INSERT INTO cell_day_aggregates (
            region,
            h3_index,
            date,
            hotspot_count,
            total_frp,
            max_frp,
            avg_frp,
            min_frp,
            high_confidence_count,
            nominal_confidence_count,
            low_confidence_count
        )
        SELECT
            region,
            h3_index,
            DATE(acq_datetime) as date,
            COUNT(*) as hotspot_count,
            SUM(frp) as total_frp,
            MAX(frp) as max_frp,
            AVG(frp) as avg_frp,
            MIN(frp) as min_frp,
            SUM(CASE WHEN confidence >= 80 THEN 1 ELSE 0 END) as high_confidence_count,
            SUM(CASE WHEN confidence >= 40 AND confidence < 80 THEN 1 ELSE 0 END) as nominal_confidence_count,
            SUM(CASE WHEN confidence < 40 THEN 1 ELSE 0 END) as low_confidence_count
        FROM raw_hotspots
        WHERE region = :region {date_filter}
        GROUP BY region, h3_index, DATE(acq_datetime)
        ON CONFLICT (region, h3_index, date)
        DO UPDATE SET
            hotspot_count = EXCLUDED.hotspot_count,
            total_frp = EXCLUDED.total_frp,
            max_frp = EXCLUDED.max_frp,
            avg_frp = EXCLUDED.avg_frp,
            min_frp = EXCLUDED.min_frp,
            high_confidence_count = EXCLUDED.high_confidence_count,
            nominal_confidence_count = EXCLUDED.nominal_confidence_count,
            low_confidence_count = EXCLUDED.low_confidence_count
        """

        db.execute(text(query), params)
        db.commit()

        stats = db.execute(text("""
            SELECT
                COUNT(DISTINCT h3_index) as unique_cells,
                COUNT(DISTINCT date) as unique_dates,
                COUNT(*) as total_records,
                SUM(hotspot_count) as total_hotspots,
                AVG(hotspot_count) as avg_hotspots_per_cell_day,
                MAX(hotspot_count) as max_hotspots_in_cell_day
            FROM cell_day_aggregates
            WHERE region = :region
        """), {"region": region_id}).fetchone()

        logger.info(f"\nAggregation complete ({region_id})!")
        logger.info(f"  Unique H3 cells: {stats.unique_cells:,}")
        logger.info(f"  Unique dates: {stats.unique_dates}")
        logger.info(f"  Total cell-day records: {stats.total_records:,}")
        logger.info(f"  Total hotspots aggregated: {stats.total_hotspots:,}")

        return stats.total_records

    except Exception as e:
        logger.error(f"Error during aggregation: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Aggregate raw hotspots by H3 cell and date')
    parser.add_argument('--date', type=str, help='Specific date to aggregate (YYYY-MM-DD)')
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()

    aggregate_daily(target_date)

    print("\nAggregation complete!")
    print("Next: python scripts/build_features.py")
