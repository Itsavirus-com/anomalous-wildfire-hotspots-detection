"""
Feature Engineering Script
Calculates temporal and spatial features for ML
"""

import os
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging
import h3

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from wildfire_detection.models import Base, CellDayAggregate, CellDayFeatures

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
H3_RESOLUTION = int(os.getenv("H3_RESOLUTION", 7))

if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)


def build_features(target_date: date = None):
    """
    Build ML features from aggregated data
    
    Features:
    - Temporal: delta vs prev day, ratio vs 7-day avg
    - Spatial: neighbor activity count
    
    Args:
        target_date: Specific date to build features for (None = all dates)
    """
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Get date range
        if target_date:
            logger.info(f"Building features for {target_date}...")
            date_filter = "WHERE date = :target_date"
            params = {"target_date": target_date}
        else:
            logger.info("Building features for all dates...")
            date_filter = ""
            params = {}
        
        # Get all cell-day records
        query = f"""
            SELECT h3_index, date, hotspot_count, total_frp, max_frp
            FROM cell_day_aggregates
            {date_filter}
            ORDER BY date, h3_index
        """
        
        records = db.execute(text(query), params).fetchall()
        logger.info(f"Processing {len(records):,} cell-day records...")
        
        features_created = 0
        features_updated = 0
        
        for idx, record in enumerate(records):
            h3_index = record.h3_index
            current_date = record.date
            hotspot_count = record.hotspot_count
            total_frp = record.total_frp
            max_frp = record.max_frp
            
            # === TEMPORAL FEATURES ===
            
            # 1. Delta vs previous day
            prev_day_query = text("""
                SELECT hotspot_count 
                FROM cell_day_aggregates
                WHERE h3_index = :h3_index 
                AND date = :prev_date
            """)
            
            prev_day = db.execute(prev_day_query, {
                "h3_index": h3_index,
                "prev_date": current_date - timedelta(days=1)
            }).fetchone()
            
            if prev_day:
                delta_count_vs_prev_day = hotspot_count - prev_day.hotspot_count
            else:
                delta_count_vs_prev_day = 0
            
            # 2. Ratio vs 7-day average
            avg_7d_query = text("""
                SELECT AVG(hotspot_count) as avg_count
                FROM cell_day_aggregates
                WHERE h3_index = :h3_index
                AND date BETWEEN :start_date AND :end_date
            """)
            
            avg_7d = db.execute(avg_7d_query, {
                "h3_index": h3_index,
                "start_date": current_date - timedelta(days=7),
                "end_date": current_date - timedelta(days=1)
            }).fetchone()
            
            if avg_7d and avg_7d.avg_count and avg_7d.avg_count > 0:
                ratio_vs_7d_avg = hotspot_count / avg_7d.avg_count
            else:
                ratio_vs_7d_avg = 1.0
            
            # === SPATIAL FEATURES ===
            
            # 3. Neighbor activity (count of active neighbors)
            try:
                # Get 1-ring neighbors (6 adjacent hexagons)
                neighbors = list(h3.grid_ring(h3_index, 1))
                
                # Count active neighbors
                neighbor_query = text("""
                    SELECT COUNT(*) as active_count
                    FROM cell_day_aggregates
                    WHERE h3_index = ANY(:neighbors)
                    AND date = :current_date
                    AND hotspot_count > 0
                """)
                
                neighbor_result = db.execute(neighbor_query, {
                    "neighbors": neighbors,
                    "current_date": current_date
                }).fetchone()
                
                neighbor_activity = neighbor_result.active_count if neighbor_result else 0
                
            except Exception as e:
                logger.warning(f"Error calculating neighbor activity for {h3_index}: {e}")
                neighbor_activity = 0
            
            # === INSERT/UPDATE FEATURES ===
            
            upsert_query = text("""
                INSERT INTO cell_day_features (
                    h3_index, date, hotspot_count, total_frp, max_frp,
                    delta_count_vs_prev_day, ratio_vs_7d_avg, neighbor_activity
                )
                VALUES (
                    :h3_index, :date, :hotspot_count, :total_frp, :max_frp,
                    :delta_count_vs_prev_day, :ratio_vs_7d_avg, :neighbor_activity
                )
                ON CONFLICT (h3_index, date)
                DO UPDATE SET
                    hotspot_count = EXCLUDED.hotspot_count,
                    total_frp = EXCLUDED.total_frp,
                    max_frp = EXCLUDED.max_frp,
                    delta_count_vs_prev_day = EXCLUDED.delta_count_vs_prev_day,
                    ratio_vs_7d_avg = EXCLUDED.ratio_vs_7d_avg,
                    neighbor_activity = EXCLUDED.neighbor_activity
            """)
            
            db.execute(upsert_query, {
                "h3_index": h3_index,
                "date": current_date,
                "hotspot_count": hotspot_count,
                "total_frp": total_frp,
                "max_frp": max_frp,
                "delta_count_vs_prev_day": delta_count_vs_prev_day,
                "ratio_vs_7d_avg": ratio_vs_7d_avg,
                "neighbor_activity": neighbor_activity
            })
            
            features_created += 1
            
            # Commit in batches
            if features_created % 500 == 0:
                db.commit()
                logger.info(f"Progress: {features_created:,} / {len(records):,} ({features_created/len(records)*100:.1f}%)")
        
        # Final commit
        db.commit()
        
        # Statistics
        stats_query = text("""
            SELECT 
                COUNT(*) as total_features,
                AVG(delta_count_vs_prev_day) as avg_delta,
                AVG(ratio_vs_7d_avg) as avg_ratio,
                AVG(neighbor_activity) as avg_neighbors,
                MAX(neighbor_activity) as max_neighbors
            FROM cell_day_features
        """)
        
        stats = db.execute(stats_query).fetchone()
        
        logger.info(f"\n✅ Feature engineering complete!")
        logger.info(f"  Total features created: {stats.total_features:,}")
        logger.info(f"  Avg delta vs prev day: {stats.avg_delta:.1f}")
        logger.info(f"  Avg ratio vs 7-day avg: {stats.avg_ratio:.2f}x")
        logger.info(f"  Avg neighbor activity: {stats.avg_neighbors:.1f}")
        logger.info(f"  Max neighbor activity: {stats.max_neighbors}")
        
        # Show top anomalous features
        top_features_query = text("""
            SELECT 
                h3_index, date, hotspot_count,
                delta_count_vs_prev_day, ratio_vs_7d_avg, neighbor_activity
            FROM cell_day_features
            WHERE ratio_vs_7d_avg > 1.5
            ORDER BY ratio_vs_7d_avg DESC
            LIMIT 5
        """)
        
        top_features = db.execute(top_features_query).fetchall()
        
        logger.info(f"\n🔥 Top 5 Potentially Anomalous Cell-Days:")
        for idx, feat in enumerate(top_features, 1):
            logger.info(f"  {idx}. Cell {feat.h3_index[:10]}... on {feat.date}")
            logger.info(f"     Hotspots: {feat.hotspot_count}, Delta: {feat.delta_count_vs_prev_day:+d}, Ratio: {feat.ratio_vs_7d_avg:.2f}x, Neighbors: {feat.neighbor_activity}")
        
        return stats.total_features
        
    except Exception as e:
        logger.error(f"Error during feature engineering: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Build ML features from aggregated data')
    parser.add_argument('--date', type=str, help='Specific date to build features for (YYYY-MM-DD)')
    args = parser.parse_args()
    
    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    
    build_features(target_date)
    
    print("\n🎉 Feature engineering complete!")
    print("\nNext steps:")
    print("  1. Train model: python scripts/train_model.py")
    print("  2. Score anomalies: python scripts/score_daily.py")
