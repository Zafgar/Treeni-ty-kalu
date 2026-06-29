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


def ensure_columns():
    """Kevyt automaattimigraatio: lisää puuttuvat sarakkeet olemassa oleviin
    tauluihin. SQLAlchemyn create_all luo uudet taulut, mutta ei lisää uusia
    sarakkeita vanhoihin -> tehdään se tässä, jotta paikallinen kanta pysyy
    ajan tasalla ilman erillistä migraatiotyökalua."""
    from sqlalchemy import inspect, text

    # Sarakkeet jotka on lisätty mallien kehittyessä: (taulu, sarake, SQL-tyyppi)
    added = [
        ("program_exercises", "rep_scheme", "VARCHAR(120)"),
        ("program_exercises", "percent_scheme", "VARCHAR(120)"),
    ]
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, col_type in added:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
