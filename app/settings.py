from __future__ import annotations

from functools import lru_cache
from pydantic import BaseModel
import os


class Settings(BaseModel):
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg2://postgres:postgres@db:5432/glh_timer")
    admin_username: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "admin")
    secret_key: str = os.getenv("SECRET_KEY", "change-me")


@lru_cache
def get_settings() -> Settings:
    return Settings()
