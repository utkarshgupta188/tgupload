from __future__ import annotations
from sqlalchemy import create_engine, String, Integer, Text, text, inspect
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool
from typing import Optional
import os

from .config import settings

class Base(DeclarativeBase):
    pass

class File(Base):
    __tablename__ = "files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_file_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional fields for user-mode (Pyrogram) downloads
    chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


def get_database_url() -> str:
    if settings.DATABASE_URL:
        return settings.DATABASE_URL
    # default to SQLite file in data folder
    data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    return f"sqlite:///{os.path.join(data_dir, 'app.db')}"


DATABASE_URL = get_database_url()
# Normalize postgres:// to postgresql:// for SQLAlchemy
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Render ephemeral FS okay; for SQLite concurrent, check_same_thread
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# Avoid connection pooling on serverless or edge (Postgres)
engine = create_engine(
    DATABASE_URL,
    poolclass=NullPool if DATABASE_URL.startswith("postgresql") else None,
    connect_args=connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    # Create tables if not exist
    Base.metadata.create_all(bind=engine)
    # Lightweight runtime migration for new columns
    try:
        insp = inspect(engine)
        cols = {c["name"] for c in insp.get_columns("files")}
        with engine.begin() as conn:
            if "chat_id" not in cols:
                conn.execute(text("ALTER TABLE files ADD COLUMN chat_id VARCHAR(64)"))
            if "message_id" not in cols:
                conn.execute(text("ALTER TABLE files ADD COLUMN message_id INTEGER"))
    except Exception:
        # Best-effort; ignore if migration not supported in environment
        pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
