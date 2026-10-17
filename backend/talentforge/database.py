from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from talentforge.config import get_settings


class Base(DeclarativeBase):
    pass


def _engine_options(url: str) -> dict[str, object]:
    if url.startswith("sqlite"):
        if url == "sqlite://":
            return {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


engine = create_engine(
    get_settings().database_url,
    **_engine_options(get_settings().database_url),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
