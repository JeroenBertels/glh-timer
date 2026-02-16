from __future__ import annotations

from functools import lru_cache
from pydantic import BaseModel
import os


class Settings(BaseModel):
    database_url: str = os.getenv("DATABASE_URL", None)
    admin_username: str = os.getenv("ADMIN_USERNAME", None)
    admin_password: str = os.getenv("ADMIN_PASSWORD", None)
    secret_key: str = os.getenv("SECRET_KEY", None)


@lru_cache
def get_settings() -> Settings:
    return Settings()
