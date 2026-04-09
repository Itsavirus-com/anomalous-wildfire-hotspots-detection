# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Import NASA FIRMS JSON archive data into database
"""

import json
import h3
import os
import sys
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import logging

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from wildfire_detection.models import Base, RawHotspot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()

# Database connection
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env file")
    sys.exit(1)

def import_json_archive(json_file: str):
    """
    Import JSON archive data into database
    
    Args:
        json_file: Path to JSON file from NASA FIRMS
    """
    # Setup database
    engine = create_engine(DATABASE_URL)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # Load JSON
    logger.info(f"Loading {json_file}...")
    with open(json_file, 'r') as f:
        data = json.load(f)
    
    logger.info(f"Found {len(data):,} hotspot records")
    
    # Import
    inserted = 0
    skipped = 0
    
    for idx, record in enumerate(data):
        try:
            # Parse datetime
            acq_date = record['acq_date']
            acq_time = str(record['acq_time']).zfill(4)
            acq_datetime = datetime.strptime(
                f"{acq_date} {acq_time[:2]}:{acq_time[2:]}",
                "%Y-%m-%d %H:%M"
            )
            
            # Calculate H3 index (H3 v4 API)
            h3_index = h3.latlng_to_cell(
                record['latitude'],
                record['longitude'],
                7  # resolution
            )
            
            # Map confidence
            confidence_map = {'l': 30, 'n': 50, 'h': 100}
            confidence = confidence_map.get(record['confidence'], 50)
            
            # Create record
            hotspot = RawHotspot(
                lat=record['latitude'],
                lng=record['longitude'],
                geom=f"POINT({record['longitude']} {record['latitude']})",
                frp=record['frp'],
                confidence=confidence,
                satellite=record['satellite'],
                acq_datetime=acq_datetime,
                h3_index=h3_index,
                ingested_at=datetime.now(),
                # Map JSON fields to database fields
                bright_ti4=record.get('brightness'),  # JSON uses 'brightness'
                bright_ti5=record.get('bright_t31'),  # JSON uses 'bright_t31'
                scan=record.get('scan'),
                track=record.get('track'),
                instrument=record.get('instrument'),
                version=record.get('version'),
                daynight=record.get('daynight')
            )
            
            db.add(hotspot)
            inserted += 1
            
            # Commit in batches
            if inserted % 1000 == 0:
                db.commit()
                logger.info(f"Progress: {inserted:,} / {len(data):,} ({inserted/len(data)*100:.1f}%)")
        
        except Exception as e:
            logger.warning(f"Failed to import record {idx}: {e}")
            skipped += 1
            continue
    
    # Final commit
    db.commit()
    db.close()
    
    logger.info(f"\n✅ Import complete!")
    logger.info(f"  Inserted: {inserted:,}")
    logger.info(f"  Skipped: {skipped:,}")
    logger.info(f"  Success rate: {inserted/(inserted+skipped)*100:.1f}%")
    
    return inserted


if __name__ == "__main__":
    # Import the JSON file from data directory
    json_file = Path(__file__).parent.parent / 'data' / 'fire_nrt_SV-C2_714486.json'
    
    if not json_file.exists():
        logger.error(f"File not found: {json_file}")
        logger.error("Please ensure fire_nrt_SV-C2_714486.json is in the data/ directory")
        sys.exit(1)
    
    import_json_archive(str(json_file))
    
    print("\n🎉 Archive data imported!")
    print("Next steps:")
    print("1. Run aggregation: python scripts/aggregate_daily.py")
    print("2. Build features: python scripts/build_features.py")
    print("3. Train model: python scripts/train_model.py")
    print("4. Start ML scoring!")
