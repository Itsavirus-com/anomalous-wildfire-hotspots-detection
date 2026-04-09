# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Create database tables
Run this script to create all tables in the database
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine
from dotenv import load_dotenv
from src.wildfire_detection.models import Base, RawHotspot, CellDayAggregate, CellDayFeatures, CellDayScores, DailyAlerts

# Load environment variables
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("❌ ERROR: DATABASE_URL not found in .env file")
    print("Please set DATABASE_URL in .env file")
    print("Example: DATABASE_URL=postgresql://postgres:password@localhost:5432/wildfire_db")
    sys.exit(1)

print(f"📊 Connecting to database...")
print(f"   URL: {DATABASE_URL.replace(DATABASE_URL.split('@')[0].split('//')[1], '***')}")

try:
    # Create engine
    engine = create_engine(DATABASE_URL, echo=True)
    
    # Test connection
    with engine.connect() as conn:
        result = conn.execute("SELECT version();")
        version = result.fetchone()[0]
        print(f"\n✅ Connected to PostgreSQL")
        print(f"   Version: {version}")
        
        # Check PostGIS
        result = conn.execute("SELECT PostGIS_Version();")
        postgis_version = result.fetchone()[0]
        print(f"   PostGIS: {postgis_version}")
    
    # Create all tables
    print(f"\n📋 Creating tables...")
    Base.metadata.create_all(engine)
    
    print(f"\n✅ All tables created successfully!")
    print(f"\nTables created:")
    print(f"  - raw_hotspots")
    print(f"  - cell_day_aggregates")
    print(f"  - cell_day_features")
    print(f"  - cell_day_scores")
    print(f"  - daily_alerts")
    
    # Show table info
    print(f"\n📊 Verifying tables...")
    with engine.connect() as conn:
        result = conn.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name;
        """)
        tables = result.fetchall()
        print(f"\nTables in database:")
        for table in tables:
            print(f"  ✓ {table[0]}")
    
    print(f"\n🎉 Database setup complete!")
    print(f"\nNext steps:")
    print(f"  1. Import archive data: python scripts/import_archive.py")
    print(f"  2. Build features: python scripts/build_features.py")
    print(f"  3. Train model: python scripts/train_model.py")

except Exception as e:
    print(f"\n❌ Error: {e}")
    print(f"\nTroubleshooting:")
    print(f"  1. Check DATABASE_URL in .env file")
    print(f"  2. Ensure PostgreSQL is running")
    print(f"  3. Verify database 'wildfire_db' exists")
    print(f"  4. Check PostGIS extension is installed")
    sys.exit(1)
