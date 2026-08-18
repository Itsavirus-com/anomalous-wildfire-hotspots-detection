# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
One-shot migration: add region column to pipeline tables.

1. Adds region VARCHAR(32) if missing
2. Backfills existing rows to 'indonesia'
3. Sets NOT NULL + indexes
4. Replaces unique constraints to include region
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

TABLES = [
    "raw_hotspots",
    "cell_day_aggregates",
    "cell_day_features",
    "cell_day_scores",
    "daily_alerts",
]

# Old unique constraint names → new ones including region
UNIQUE_MIGRATIONS = [
    ("cell_day_aggregates", "uq_cell_day", "uq_cell_day_region", ["region", "h3_index", "date"]),
    ("cell_day_features", "uq_cell_day_features", "uq_cell_day_features_region", ["region", "h3_index", "date"]),
    ("cell_day_scores", "uq_cell_day_score", "uq_cell_day_score_region", ["region", "h3_index", "date"]),
]


def column_exists(conn, table: str, column: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
    """), {"t": table, "c": column}).fetchone()
    return row is not None


def constraint_exists(conn, name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM pg_constraint WHERE conname = :n
    """), {"n": name}).fetchone()
    return row is not None


def index_exists(conn, name: str) -> bool:
    row = conn.execute(text("""
        SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = :n
    """), {"n": name}).fetchone()
    return row is not None


def migrate():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        for table in TABLES:
            print(f"\n→ {table}")
            if not column_exists(conn, table, "region"):
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN region VARCHAR(32)"))
                print("  added column region")
            else:
                print("  column region already exists")

            updated = conn.execute(text(f"""
                UPDATE {table} SET region = 'indonesia' WHERE region IS NULL OR region = ''
            """))
            print(f"  backfilled {updated.rowcount} rows → indonesia")

            conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN region SET DEFAULT 'indonesia'"))
            conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN region SET NOT NULL"))
            print("  set NOT NULL + default")

            idx = f"ix_{table}_region"
            if not index_exists(conn, idx):
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx} ON {table} (region)"))
                print(f"  created index {idx}")

        for table, old_uq, new_uq, cols in UNIQUE_MIGRATIONS:
            print(f"\n→ unique constraint on {table}")
            if constraint_exists(conn, old_uq):
                conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {old_uq}"))
                print(f"  dropped {old_uq}")
            if not constraint_exists(conn, new_uq):
                col_list = ", ".join(cols)
                conn.execute(text(
                    f"ALTER TABLE {table} ADD CONSTRAINT {new_uq} UNIQUE ({col_list})"
                ))
                print(f"  created {new_uq} ({col_list})")
            else:
                print(f"  {new_uq} already exists")

        # Composite region+date indexes for common filters
        composite = [
            ("raw_hotspots", "ix_raw_hotspots_region_acq", "(region, acq_datetime)"),
            ("cell_day_aggregates", "ix_cell_day_agg_region_date", "(region, date)"),
            ("cell_day_features", "ix_cell_day_feat_region_date", "(region, date)"),
            ("cell_day_scores", "ix_cell_day_scores_region_date", "(region, date)"),
            ("daily_alerts", "ix_daily_alerts_region_date", "(region, date)"),
        ]
        for table, name, cols in composite:
            if not index_exists(conn, name):
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} {cols}"))
                print(f"  created {name}")

    print("\n✅ Migration complete — region column ready on all pipeline tables")


if __name__ == "__main__":
    migrate()
