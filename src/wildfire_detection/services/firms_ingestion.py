"""
NASA FIRMS Data Ingestion Module
Fetches wildfire hotspot data from NASA FIRMS API for Indonesia
"""

import requests
import pandas as pd
from datetime import datetime, timedelta, date
from typing import List, Optional
import h3
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from models import RawHotspot  # Your SQLAlchemy model
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FIRMSClient:
    """Client for NASA FIRMS API"""
    
    BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area"
    
    # Indonesia bounding box: [west, south, east, north]
    INDONESIA_BBOX = [95, -11, 141, 6]
    
    def __init__(self, map_key: str):
        """
        Initialize FIRMS client
        
        Args:
            map_key: NASA FIRMS API key
        """
        self.map_key = map_key
        
    def fetch_hotspots(
        self,
        satellite: str = "VIIRS_SNPP_NRT",
        days: int = 1,
        bbox: Optional[List[float]] = None
    ) -> pd.DataFrame:
        """
        Fetch hotspot data from FIRMS API
        
        Args:
            satellite: Satellite source (VIIRS_SNPP_NRT, VIIRS_NOAA20_NRT, MODIS_NRT)
            days: Number of days to fetch (1-10)
            bbox: Bounding box [west, south, east, north], defaults to Indonesia
            
        Returns:
            DataFrame with hotspot data
        """
        if bbox is None:
            bbox = self.INDONESIA_BBOX
        
        # Construct URL
        bbox_str = ",".join(map(str, bbox))
        url = f"{self.BASE_URL}/csv/{self.map_key}/{satellite}/{bbox_str}/{days}"
        
        logger.info(f"Fetching FIRMS data from: {url}")
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse CSV
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))
            
            logger.info(f"Fetched {len(df)} hotspots from FIRMS")
            
            return df
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching FIRMS data: {e}")
            raise
    
    def fetch_all_satellites(self, days: int = 1) -> pd.DataFrame:
        """
        Fetch data from all available satellites and combine
        
        Args:
            days: Number of days to fetch
            
        Returns:
            Combined DataFrame from all satellites
        """
        satellites = [
            "VIIRS_SNPP_NRT",    # Suomi NPP
            "VIIRS_NOAA20_NRT",  # NOAA-20
            "MODIS_NRT"          # Terra & Aqua
        ]
        
        all_data = []
        
        for satellite in satellites:
            try:
                df = self.fetch_hotspots(satellite=satellite, days=days)
                all_data.append(df)
            except Exception as e:
                logger.warning(f"Failed to fetch {satellite}: {e}")
                continue
        
        if not all_data:
            raise ValueError("Failed to fetch data from any satellite")
        
        # Combine all dataframes
        combined = pd.concat(all_data, ignore_index=True)
        
        # Remove duplicates (same location, time, satellite)
        combined = combined.drop_duplicates(
            subset=['latitude', 'longitude', 'acq_date', 'acq_time', 'satellite']
        )
        
        logger.info(f"Combined total: {len(combined)} unique hotspots")
        
        return combined


class FIRMSIngester:
    """Ingest FIRMS data into database"""
    
    def __init__(self, db_session: Session, h3_resolution: int = 7):
        """
        Initialize ingester
        
        Args:
            db_session: SQLAlchemy database session
            h3_resolution: H3 hexagon resolution (7 = ~5.16 km²)
        """
        self.db = db_session
        self.h3_resolution = h3_resolution
    
    def validate_hotspot(self, row: pd.Series) -> bool:
        """
        Validate hotspot data
        
        Args:
            row: DataFrame row
            
        Returns:
            True if valid, False otherwise
        """
        # Check coordinates are within Indonesia bounds
        if not (-11 <= row['latitude'] <= 6):
            return False
        if not (95 <= row['longitude'] <= 141):
            return False
        
        # Check FRP is reasonable
        if pd.isna(row['frp']) or row['frp'] < 0:
            return False
        
        # Check confidence
        if row['confidence'] not in ['l', 'n', 'h']:  # low, nominal, high
            return False
        
        return True
    
    def parse_acquisition_datetime(self, row: pd.Series) -> datetime:
        """
        Parse acquisition date and time into datetime
        
        Args:
            row: DataFrame row with acq_date and acq_time
            
        Returns:
            datetime object
        """
        # acq_date format: YYYY-MM-DD
        # acq_time format: HHMM (e.g., 416 = 04:16, 1234 = 12:34)
        date_str = row['acq_date']
        time_str = str(int(row['acq_time'])).zfill(4)  # Pad to 4 digits
        
        datetime_str = f"{date_str} {time_str[:2]}:{time_str[2:]}"
        return datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
    
    def confidence_to_int(self, confidence: str) -> int:
        """
        Convert confidence letter to integer
        
        Args:
            confidence: 'l', 'n', or 'h'
            
        Returns:
            Integer confidence (0-100)
        """
        mapping = {
            'l': 30,   # low
            'n': 50,   # nominal
            'h': 100   # high
        }
        return mapping.get(confidence, 50)
    
    def ingest_dataframe(self, df: pd.DataFrame) -> int:
        """
        Ingest DataFrame into database
        
        Args:
            df: DataFrame with FIRMS data
            
        Returns:
            Number of records inserted
        """
        inserted_count = 0
        skipped_count = 0
        
        for idx, row in df.iterrows():
            # Validate
            if not self.validate_hotspot(row):
                skipped_count += 1
                continue
            
            try:
                # Parse datetime
                acq_datetime = self.parse_acquisition_datetime(row)
                
                # Calculate H3 index
                h3_index = h3.geo_to_h3(
                    row['latitude'],
                    row['longitude'],
                    self.h3_resolution
                )
                
                # Create geometry point (PostGIS format)
                geom = f"POINT({row['longitude']} {row['latitude']})"
                
                # Create record
                hotspot = RawHotspot(
                    lat=row['latitude'],
                    lng=row['longitude'],
                    geom=geom,
                    frp=row['frp'],
                    confidence=self.confidence_to_int(row['confidence']),
                    satellite=row['satellite'],
                    acq_datetime=acq_datetime,
                    h3_index=h3_index,
                    ingested_at=datetime.now(),
                    # Additional fields
                    bright_ti4=row.get('bright_ti4'),
                    bright_ti5=row.get('bright_ti5'),
                    scan=row.get('scan'),
                    track=row.get('track'),
                    instrument=row.get('instrument'),
                    version=row.get('version'),
                    daynight=row.get('daynight')
                )
                
                self.db.add(hotspot)
                inserted_count += 1
                
            except Exception as e:
                logger.warning(f"Failed to ingest row {idx}: {e}")
                skipped_count += 1
                continue
        
        # Commit all records
        try:
            self.db.commit()
            logger.info(f"Inserted {inserted_count} hotspots, skipped {skipped_count}")
        except Exception as e:
            self.db.rollback()
            logger.error(f"Database commit failed: {e}")
            raise
        
        return inserted_count


def run_daily_ingestion(
    map_key: str,
    db_session: Session,
    days: int = 1,
    fetch_all_satellites: bool = True
):
    """
    Run daily ingestion job
    
    Args:
        map_key: NASA FIRMS API key
        db_session: Database session
        days: Number of days to fetch
        fetch_all_satellites: If True, fetch from all satellites
    """
    logger.info(f"Starting FIRMS ingestion for last {days} day(s)")
    
    # Initialize client
    client = FIRMSClient(map_key=map_key)
    
    # Fetch data
    if fetch_all_satellites:
        df = client.fetch_all_satellites(days=days)
    else:
        df = client.fetch_hotspots(satellite="VIIRS_SNPP_NRT", days=days)
    
    # Ingest into database
    ingester = FIRMSIngester(db_session=db_session)
    count = ingester.ingest_dataframe(df)
    
    logger.info(f"Ingestion complete: {count} records inserted")
    
    return count


# Example usage
if __name__ == "__main__":
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    
    # Database connection
    DATABASE_URL = "postgresql://user:password@localhost/wildfire_db"
    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    # NASA FIRMS API key
    MAP_KEY = "9ae1e0c7f5a6ae110169c38075aba8aa"
    
    try:
        # Run ingestion for last 5 days
        run_daily_ingestion(
            map_key=MAP_KEY,
            db_session=db,
            days=5,
            fetch_all_satellites=True
        )
    finally:
        db.close()
