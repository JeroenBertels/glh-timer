from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session as SessionBase, sessionmaker

from app.settings import get_settings


class Base(DeclarativeBase):
    pass


class SoftDeleteSession(SessionBase):
    def get(self, entity, ident, **kwargs):
        execution_options = dict(kwargs.get("execution_options") or {})
        include_deleted = execution_options.get("include_deleted", False)
        record = super().get(entity, ident, **kwargs)
        if include_deleted or record is None or not hasattr(record, "deleted_at"):
            return record
        if getattr(record, "deleted_at") is not None:
            return None
        return record


def get_engine():
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=get_engine(),
    class_=SoftDeleteSession,
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
