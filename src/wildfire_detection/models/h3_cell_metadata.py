# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
H3 Cell Metadata — Region mapping for H3 hexagons
"""

from sqlalchemy import Column, String, Float, DateTime
from datetime import datetime
from .base import Base


class H3CellMetadata(Base):
    """Maps each H3 cell to its Indonesian administrative region"""
    __tablename__ = 'h3_cell_metadata'

    h3_index = Column(String(15), primary_key=True)

    # Coordinates (center of hexagon)
    center_lat = Column(Float, nullable=False)
    center_lng = Column(Float, nullable=False)

    # Indonesian administrative regions
    province = Column(String(100))       # Provinsi   e.g. "Kalimantan Tengah"
    regency = Column(String(150))        # Kabupaten  e.g. "Kabupaten Kotawaringin Timur"
    district = Column(String(150))       # Kecamatan  e.g. "Cempaga"
    display_name = Column(String(500))   # Full display name from geocoder

    # Meta
    enriched_at = Column(DateTime, default=datetime.now)
    geocode_source = Column(String(20), default='nominatim')  # nominatim / manual / unknown

    def __repr__(self):
        return f"<H3CellMetadata(h3={self.h3_index}, province={self.province})>"
