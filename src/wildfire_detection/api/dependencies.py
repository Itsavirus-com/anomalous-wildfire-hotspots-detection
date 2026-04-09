# SPDX-License-Identifier: MIT
# Copyright (c) 2025 Itsavirus
"""
Database session dependency for FastAPI
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv
from typing import Generator

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,   # Verify connection before using from pool
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """Yield a DB session, close after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
