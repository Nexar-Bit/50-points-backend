from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import BACKEND_ROOT, settings


def normalize_database_url(url: str) -> str:
    """Render/Heroku use postgres://; SQLAlchemy 2 needs postgresql+psycopg://."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def resolve_database_url(url: str) -> str:
    if url.startswith("sqlite:///./"):
        db_path = BACKEND_ROOT / url.removeprefix("sqlite:///./")
    elif "../prisma/dev.db" in url:
        db_path = BACKEND_ROOT / "data" / "dev.db"
    else:
        return normalize_database_url(url)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.resolve().as_posix()}"


db_url = resolve_database_url(settings.database_url)
is_sqlite = db_url.startswith("sqlite")

if is_sqlite:
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
