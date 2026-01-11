from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Security
    GLH_ADMIN_USERNAME: str = "admin"
    GLH_ADMIN_PASSWORD: str = "change-me"
    GLH_SECRET_KEY: str = "dev-secret-change-me"

    # Database
    GLH_DB_URL: str = "sqlite:///./glh_timer.db"

    # UI
    RESULTS_POLL_MS: int = 5000

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
