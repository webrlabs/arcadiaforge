"""
Database Connection Manager
===========================

Handles the async connection to the project-specific SQLite database.
"""

import os
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import text

from arcadiaforge.db.models import Base

# Global session maker
_async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None
_engine = None

async def init_db(project_path: Path):
    """
    Initialize the database connection and create tables if they don't exist.
    The database file is stored in .arcadia/project.db within the project root.
    """
    global _async_session_maker, _engine

    # Ensure .arcadia directory exists
    db_dir = project_path / ".arcadia"
    db_dir.mkdir(parents=True, exist_ok=True)
    
    db_path = db_dir / "project.db"
    db_url = f"sqlite+aiosqlite:///{db_path}"

    _engine = create_async_engine(db_url, echo=False)
    
    # Create tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    _async_session_maker = async_sessionmaker(_engine, expire_on_commit=False)
    
    return _async_session_maker

def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Get the configured session maker."""
    if _async_session_maker is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _async_session_maker

async def get_db():
    """Dependency for getting a database session."""
    maker = get_session_maker()
    async with maker() as session:
        yield session
