# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Feature Engineering Script — region-scoped bulk/vectorized implementation.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, date, timedelta
from typing import Optional

import h3
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import logging

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
load_dotenv()

from wildfire_detection.regions import DATA_REGION

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    logger.error("DATABASE_URL not found in .env"); sys.exit(1)


def build_features(target_date: Optional[date] = None) -> int:
    region_id = DATA_REGION
    engine = create_engine(DATABASE_URL)

    if target_date:
        context_start = target_date - timedelta(days=8)
        logger.info(
            f"Building features for {target_date} ({region_id}) "
            f"(context from {context_start})..."
        )
        df = pd.read_sql(
            text("""
                SELECT h3_index, date, hotspot_count, total_frp, max_frp
                FROM cell_day_aggregates
                WHERE region = :region AND date BETWEEN :start AND :end
                ORDER BY h3_index, date
            """),
            engine,
            params={"region": region_id, "start": context_start, "end": target_date},
        )
    else:
        logger.info(f"Building features for ALL dates ({region_id})...")
        df = pd.read_sql(
            text("""
                SELECT h3_index, date, hotspot_count, total_frp, max_frp
                FROM cell_day_aggregates
                WHERE region = :region
                ORDER BY h3_index, date
            """),
            engine,
            params={"region": region_id},
        )

    if df.empty:
        logger.warning("No aggregate data found. Run aggregate_daily.py first.")
        return 0

    logger.info(f"Loaded {len(df):,} cell-day records for feature computation")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values(["h3_index", "date"]).reset_index(drop=True)

    df["delta_count_vs_prev_day"] = (
        df.groupby("h3_index")["hotspot_count"].diff().fillna(0).astype(int)
    )
    df["prior_7d_avg"] = (
        df.groupby("h3_index")["hotspot_count"]
        .transform(lambda x: x.shift(1).rolling(7, min_periods=1).mean())
    )
    df["ratio_vs_7d_avg"] = (
        df["hotspot_count"] / df["prior_7d_avg"].replace(0, float("nan"))
    ).fillna(1.0)

    if target_date:
        target_df = df[df["date"] == target_date].copy()
    else:
        target_df = df.copy()

    if target_df.empty:
        logger.warning(f"No records for {target_date} after temporal computation.")
        return 0

    logger.info(f"Computing spatial features for {len(target_df):,} target records...")
    neighbor_activity_map = {}

    for proc_date, date_group in target_df.groupby("date"):
        cells = date_group["h3_index"].tolist()
        cell_neighbors = {}
        all_neighbor_set = set()

        for h3_idx in cells:
            try:
                neighbors = list(h3.grid_ring(h3_idx, 1))
            except Exception:
                neighbors = []
            cell_neighbors[h3_idx] = neighbors
            all_neighbor_set.update(neighbors)

        if all_neighbor_set:
            with engine.connect() as conn:
                active_rows = conn.execute(text("""
                    SELECT h3_index
                    FROM cell_day_aggregates
                    WHERE region = :region
                      AND h3_index = ANY(:neighbors)
                      AND date = :d
                      AND hotspot_count > 0
                """), {
                    "region": region_id,
                    "neighbors": list(all_neighbor_set),
                    "d": proc_date,
                }).fetchall()
            active_set = {row.h3_index for row in active_rows}
        else:
            active_set = set()

        for h3_idx in cells:
            count = sum(1 for n in cell_neighbors.get(h3_idx, []) if n in active_set)
            neighbor_activity_map[(h3_idx, proc_date)] = count

    target_df["neighbor_activity"] = target_df.apply(
        lambda row: neighbor_activity_map.get((row["h3_index"], row["date"]), 0),
        axis=1,
    )

    logger.info(f"Upserting {len(target_df):,} records into cell_day_features...")
    records = [
        {
            "region": region_id,
            "h3_index": row.h3_index,
            "date": row.date,
            "hotspot_count": int(row.hotspot_count),
            "total_frp": float(row.total_frp) if pd.notna(row.total_frp) else None,
            "max_frp": float(row.max_frp) if pd.notna(row.max_frp) else None,
            "delta_count_vs_prev_day": int(row.delta_count_vs_prev_day),
            "ratio_vs_7d_avg": round(float(row.ratio_vs_7d_avg), 6),
            "neighbor_activity": int(row.neighbor_activity),
        }
        for row in target_df.itertuples()
    ]

    BATCH = 1000
    with engine.begin() as conn:
        for i in range(0, len(records), BATCH):
            batch = records[i: i + BATCH]
            conn.execute(text("""
                INSERT INTO cell_day_features
                    (region, h3_index, date, hotspot_count, total_frp, max_frp,
                     delta_count_vs_prev_day, ratio_vs_7d_avg, neighbor_activity)
                VALUES
                    (:region, :h3_index, :date, :hotspot_count, :total_frp, :max_frp,
                     :delta_count_vs_prev_day, :ratio_vs_7d_avg, :neighbor_activity)
                ON CONFLICT (region, h3_index, date) DO UPDATE SET
                    hotspot_count            = EXCLUDED.hotspot_count,
                    total_frp                = EXCLUDED.total_frp,
                    max_frp                  = EXCLUDED.max_frp,
                    delta_count_vs_prev_day  = EXCLUDED.delta_count_vs_prev_day,
                    ratio_vs_7d_avg          = EXCLUDED.ratio_vs_7d_avg,
                    neighbor_activity        = EXCLUDED.neighbor_activity
            """), batch)

    with engine.connect() as conn:
        stats = conn.execute(text("""
            SELECT COUNT(*) AS total_features
            FROM cell_day_features WHERE region = :region
        """), {"region": region_id}).fetchone()

    logger.info(f"Feature engineering complete ({region_id})!")
    logger.info(f"  Total features in DB: {stats.total_features:,}")
    return len(target_df)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build ML features from aggregated hotspot data")
    parser.add_argument("--date", type=str, default=None, help="Specific date YYYY-MM-DD")
    args = parser.parse_args()

    target_date = None
    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()

    count = build_features(target_date)
    print(f"\nFeature engineering complete — {count:,} records upserted")
    print("Next: python scripts/score_daily.py")
