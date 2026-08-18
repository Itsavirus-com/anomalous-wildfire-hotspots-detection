# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Raw hotspot data from NASA FIRMS
"""

from sqlalchemy import Column, Integer, String, DECIMAL, DateTime, Index
from geoalchemy2 import Geometry
from datetime import datetime
from .base import Base

class RawHotspot(Base):
    """Raw hotspot data from FIRMS (immutable)"""
    __tablename__ = 'raw_hotspots'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    region = Column(String(32), nullable=False, index=True, default='indonesia')
    lat = Column(DECIMAL(10, 7), nullable=False)
    lng = Column(DECIMAL(10, 7), nullable=False)
    geom = Column(Geometry('POINT', srid=4326))
    frp = Column(DECIMAL(8, 2))  # Fire Radiative Power (MW)
    confidence = Column(Integer)  # 0-100
    satellite = Column(String(50))
    acq_datetime = Column(DateTime, nullable=False)
    h3_index = Column(String(15), nullable=False, index=True)
    ingested_at = Column(DateTime, default=datetime.now)
    
    # Additional FIRMS fields
    bright_ti4 = Column(DECIMAL(6, 2))  # Brightness temperature I-4
    bright_ti5 = Column(DECIMAL(6, 2))  # Brightness temperature I-5
    scan = Column(DECIMAL(4, 2))
    track = Column(DECIMAL(4, 2))
    instrument = Column(String(20))
    version = Column(String(20))
    daynight = Column(String(1))  # D or N

    __table_args__ = (
        Index('ix_raw_hotspots_region_date', 'region', 'acq_datetime'),
    )
    
    def __repr__(self):
        return f"<RawHotspot(id={self.id}, region={self.region}, h3={self.h3_index}, frp={self.frp})>"
