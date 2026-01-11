from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, DeclarativeBase

from .settings import settings

class Base(DeclarativeBase):
    pass

_engine = None
_SessionLocal = None

def init_db() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        return
    connect_args = {"check_same_thread": False} if settings.GLH_DB_URL.startswith("sqlite") else {}
    _engine = create_engine(settings.GLH_DB_URL, future=True, echo=False, connect_args=connect_args)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False, future=True)
    from . import models  # noqa
    Base.metadata.create_all(bind=_engine)

def get_session() -> Session:
    if _SessionLocal is None:
        init_db()
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()
