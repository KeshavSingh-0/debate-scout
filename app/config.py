from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./data/debate_scout.db"
    upload_dir: str = "./data/uploads"
    scrape_concurrency: int = 3
    # DEBUG shows every scraper navigation/click step and Jev request/response
    # shape (never credentials). Set via Render's env var dashboard, no
    # redeploy needed to change it back.
    log_level: str = "INFO"

    @property
    def upload_path(self) -> Path:
        path = Path(self.upload_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
