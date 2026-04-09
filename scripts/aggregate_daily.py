# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Daily Aggregation Script
Groups raw hotspots by H3 cell + date
"""

import os
import sys
from pathlib import Path
from datetime import datetime, date
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging

# Force UTF-8 output on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from wildfire_detection.models import Base, RawHotspot, CellDayAggregate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)


def aggregate_daily(target_date: date = None):
    """
    Aggregate raw hotspots by H3 cell and date
    
    Args:
        target_date: Specific date to aggregate (None = all dates)
    """
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Build query
        if target_date:
            logger.info(f"Aggregating data for {target_date}...")
            date_filter = "AND DATE(acq_datetime) = :target_date"
            params = {"target_date": target_date}
        else:
            logger.info("Aggregating all data...")
            date_filter = ""
            params = {}
        
        # Aggregate query
        query = f"""
        INSERT INTO cell_day_aggregates (
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
        WHERE 1=1 {date_filter}
        GROUP BY h3_index, DATE(acq_datetime)
        ON CONFLICT (h3_index, date) 
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
        
        # Execute
        result = db.execute(text(query), params)
        db.commit()
        
        # Get statistics
        stats_query = text("""
            SELECT 
                COUNT(DISTINCT h3_index) as unique_cells,
                COUNT(DISTINCT date) as unique_dates,
                COUNT(*) as total_records,
                SUM(hotspot_count) as total_hotspots,
                AVG(hotspot_count) as avg_hotspots_per_cell_day,
                MAX(hotspot_count) as max_hotspots_in_cell_day
            FROM cell_day_aggregates
        """)
        
        stats = db.execute(stats_query).fetchone()
        
        logger.info(f"\n✅ Aggregation complete!")
        logger.info(f"  Unique H3 cells: {stats.unique_cells:,}")
        logger.info(f"  Unique dates: {stats.unique_dates}")
        logger.info(f"  Total cell-day records: {stats.total_records:,}")
        logger.info(f"  Total hotspots aggregated: {stats.total_hotspots:,}")
        logger.info(f"  Avg hotspots per cell-day: {stats.avg_hotspots_per_cell_day:.1f}")
        logger.info(f"  Max hotspots in single cell-day: {stats.max_hotspots_in_cell_day}")
        
        # Show top 5 most active cells
        top_cells_query = text("""
            SELECT 
                h3_index,
                date,
                hotspot_count,
                total_frp,
                max_frp
            FROM cell_day_aggregates
            ORDER BY hotspot_count DESC
            LIMIT 5
        """)
        
        top_cells = db.execute(top_cells_query).fetchall()
        
        logger.info(f"\n🔥 Top 5 Most Active Cell-Days:")
        for idx, cell in enumerate(top_cells, 1):
            logger.info(f"  {idx}. Cell {cell.h3_index[:10]}... on {cell.date}")
            logger.info(f"     Hotspots: {cell.hotspot_count}, Total FRP: {cell.total_frp:.1f} MW, Max FRP: {cell.max_frp:.1f} MW")
        
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
    
    print("\n🎉 Aggregation complete!")
    print("\nNext steps:")
    print("  1. Build features: python scripts/build_features.py")
    print("  2. Train model: python scripts/train_model.py")
