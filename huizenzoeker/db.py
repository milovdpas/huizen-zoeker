from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def init_db(database_url: str) -> Engine:
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    _engine = create_engine(database_url, pool_pre_ping=True, pool_recycle=1800, future=True)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("DB not initialized — call init_db() first")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    if _SessionLocal is None:
        raise RuntimeError("DB not initialized — call init_db() first")
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
