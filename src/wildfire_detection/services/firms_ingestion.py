# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
NASA FIRMS Data Ingestion Module — global /world endpoint.
"""

import requests
import pandas as pd
from datetime import datetime
from typing import Optional
import h3
from sqlalchemy.orm import Session
from wildfire_detection.models import RawHotspot
from wildfire_detection.regions import DATA_REGION, firms_area_path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FIRMSClient:
    BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area"

    def __init__(self, map_key: str):
        self.map_key = map_key

    def fetch_hotspots(
        self,
        satellite: str = "VIIRS_SNPP_NRT",
        days: int = 1,
    ) -> pd.DataFrame:
        area = firms_area_path()
        url = f"{self.BASE_URL}/csv/{self.map_key}/{satellite}/{area}/{days}"
        logger.info(f"Fetching FIRMS world data from: {url}")
        try:
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))
            logger.info(f"Fetched {len(df)} hotspots from FIRMS")
            return df
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching FIRMS data: {e}")
            raise

    def fetch_all_satellites(self, days: int = 1) -> pd.DataFrame:
        satellites = ["VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "MODIS_NRT"]
        all_data = []
        for satellite in satellites:
            try:
                all_data.append(self.fetch_hotspots(satellite=satellite, days=days))
            except Exception as e:
                logger.warning(f"Failed to fetch {satellite}: {e}")
        if not all_data:
            raise ValueError("Failed to fetch data from any satellite")
        combined = pd.concat(all_data, ignore_index=True)
        return combined.drop_duplicates(
            subset=['latitude', 'longitude', 'acq_date', 'acq_time', 'satellite']
        )


class FIRMSIngester:
    def __init__(self, db_session: Session, h3_resolution: int = 7):
        self.db = db_session
        self.h3_resolution = h3_resolution

    def validate_hotspot(self, row: pd.Series) -> bool:
        lat, lng = float(row['latitude']), float(row['longitude'])
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return False
        if pd.isna(row['frp']) or row['frp'] < 0:
            return False
        conf = row['confidence']
        if isinstance(conf, str) and conf.lower() not in ['l', 'n', 'h']:
            return False
        if isinstance(conf, (int, float)) and not (0 <= conf <= 100):
            return False
        return True

    def parse_acquisition_datetime(self, row: pd.Series) -> datetime:
        time_str = str(int(row['acq_time'])).zfill(4)
        return datetime.strptime(f"{row['acq_date']} {time_str[:2]}:{time_str[2:]}", "%Y-%m-%d %H:%M")

    def confidence_to_int(self, confidence) -> int:
        if isinstance(confidence, (int, float)):
            return int(confidence)
        return {'l': 30, 'n': 60, 'h': 95}.get(str(confidence).lower(), 50)

    def ingest_dataframe(self, df: pd.DataFrame) -> int:
        inserted = skipped = 0
        for idx, row in df.iterrows():
            if not self.validate_hotspot(row):
                skipped += 1
                continue
            try:
                acq_datetime = self.parse_acquisition_datetime(row)
                h3_index = h3.latlng_to_cell(
                    float(row['latitude']), float(row['longitude']), self.h3_resolution
                )
                self.db.add(RawHotspot(
                    region=DATA_REGION,
                    lat=row['latitude'],
                    lng=row['longitude'],
                    geom=f"POINT({row['longitude']} {row['latitude']})",
                    frp=row['frp'],
                    confidence=self.confidence_to_int(row['confidence']),
                    satellite=row['satellite'],
                    acq_datetime=acq_datetime,
                    h3_index=h3_index,
                    ingested_at=datetime.now(),
                    bright_ti4=row.get('bright_ti4'),
                    bright_ti5=row.get('bright_ti5'),
                    scan=row.get('scan'),
                    track=row.get('track'),
                    instrument=row.get('instrument'),
                    version=row.get('version'),
                    daynight=row.get('daynight'),
                ))
                inserted += 1
            except Exception as e:
                logger.warning(f"Failed to ingest row {idx}: {e}")
                skipped += 1
        try:
            self.db.commit()
            logger.info(f"Inserted {inserted} hotspots, skipped {skipped}")
        except Exception as e:
            self.db.rollback()
            raise
        return inserted


def run_daily_ingestion(map_key: str, db_session: Session, days: int = 1, fetch_all_satellites: bool = True):
    client = FIRMSClient(map_key=map_key)
    df = client.fetch_all_satellites(days=days) if fetch_all_satellites else client.fetch_hotspots(days=days)
    return FIRMSIngester(db_session=db_session).ingest_dataframe(df)
