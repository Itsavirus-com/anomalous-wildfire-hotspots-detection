"""
Simple script to create database tables
"""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load .env
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
print(f"DATABASE_URL: {DATABASE_URL}")

if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set!")
    sys.exit(1)

# Import models
from wildfire_detection.models import Base

# Create engine
print("Creating engine...")
engine = create_engine(DATABASE_URL)

# Test connection
print("Testing connection...")
with engine.connect() as conn:
    result = conn.execute(text("SELECT version()"))
    print(f"✅ Connected: {result.fetchone()[0][:50]}...")

# Create tables
print("\nCreating tables...")
Base.metadata.create_all(engine)

print("\n✅ Tables created!")

# Verify
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT table_name FROM information_schema.tables 
        WHERE table_schema = 'public' ORDER BY table_name
    """))
    print("\nTables:")
    for row in result:
        print(f"  - {row[0]}")

print("\n🎉 Done!")
