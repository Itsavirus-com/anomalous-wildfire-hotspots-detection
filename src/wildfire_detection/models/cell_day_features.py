"""
Cell-day features for ML
"""

from sqlalchemy import Column, Integer, String, DECIMAL, Date, UniqueConstraint
from .base import Base

class CellDayFeatures(Base):
    """Engineered features for ML input"""
    __tablename__ = 'cell_day_features'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    h3_index = Column(String(15), nullable=False, index=True)
    date = Column(Date, nullable=False, index=True)
    
    # Base features (from aggregates)
    hotspot_count = Column(Integer, nullable=False)
    total_frp = Column(DECIMAL(10, 2))
    max_frp = Column(DECIMAL(8, 2))
    
    # Temporal features
    delta_count_vs_prev_day = Column(Integer)
    ratio_vs_7d_avg = Column(DECIMAL(6, 2))
    
    # Spatial features
    neighbor_activity = Column(Integer)  # Count of active neighbors
    
    __table_args__ = (
        UniqueConstraint('h3_index', 'date', name='uq_cell_day_features'),
    )
    
    def __repr__(self):
        return f"<CellDayFeatures(h3={self.h3_index}, date={self.date})>"
