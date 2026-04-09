# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
import sys, os
sys.path.insert(0, 'src')
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import create_engine, text
engine = create_engine(os.getenv('DATABASE_URL'))
try:
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
    print('Table created OK')
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
