"""Tietokantayhteys ja istunnon hallinta (SQLite + SQLAlchemy)."""
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Tietokanta talletetaan projektin juureen kansioon data/
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "treeni.db"

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI-riippuvuus: antaa tietokantaistunnon ja sulkee sen lopuksi."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
