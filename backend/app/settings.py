from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Security (NO defaults!)
    GLH_ADMIN_USERNAME: str
    GLH_ADMIN_PASSWORD: str
    GLH_SECRET_KEY: str

    # Database
    GLH_DB_URL: str

    # UI
    RESULTS_POLL_MS: int = 5000

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
