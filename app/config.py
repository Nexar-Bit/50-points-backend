import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")

_DEFAULT_DB_PATH = (BACKEND_ROOT / "data" / "dev.db").as_posix()


class Settings:
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{_DEFAULT_DB_PATH}")
    jwt_secret: str = os.getenv("JWT_SECRET", "50points-secret-key")
    admin_secret: str | None = os.getenv("ADMIN_SECRET")
    cors_origins: str = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,https://50-points.vercel.app",
    )
    cors_origin_regex: str | None = os.getenv(
        "CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app"
    )
    environment: str = os.getenv("ENVIRONMENT", "development")
    racing_api_username: str | None = os.getenv("RACING_API_USERNAME") or os.getenv("RACING_API_KEY")
    racing_api_password: str | None = os.getenv("RACING_API_PASSWORD", "")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
