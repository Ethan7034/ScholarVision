from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

from app.core.config import settings

# Configurable database URL; defaults to a local SQLite file. Switching to
# PostgreSQL is a .env change (DATABASE_URL), not a code change.
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

_engine_kwargs = {"echo": False}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    # SQLite 的 check_same_thread 是它专属参数，其他数据库不能传
    _engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(SQLALCHEMY_DATABASE_URL, **_engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)


class PaperHistory(Base):
    __tablename__ = "paper_history"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True)
    filename = Column(String)
    vlm_result = Column(Text)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# 自动建表（启动即建表，保证新环境开箱可用）
Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
