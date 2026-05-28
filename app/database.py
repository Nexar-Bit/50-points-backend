from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import BACKEND_ROOT, settings


def resolve_database_url(url: str) -> str:
    if url.startswith("sqlite:///./"):
        db_path = BACKEND_ROOT / url.removeprefix("sqlite:///./")
    elif "../prisma/dev.db" in url:
        db_path = BACKEND_ROOT / "data" / "dev.db"
    else:
        return url
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.resolve().as_posix()}"


db_url = resolve_database_url(settings.database_url)
connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
engine = create_engine(db_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
