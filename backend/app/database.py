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
        ("programs", "profile_id", "INTEGER"),
        ("workout_sessions", "profile_id", "INTEGER"),
        ("workout_sessions", "status", "VARCHAR(12) DEFAULT 'completed'"),
        ("workout_exercises", "done", "BOOLEAN DEFAULT 0"),
        ("workout_exercises", "missed_reps", "INTEGER DEFAULT 0"),
        ("exercises", "equipment", "VARCHAR(40)"),
        ("exercises", "default_sets", "INTEGER DEFAULT 3"),
        ("exercises", "default_reps", "INTEGER DEFAULT 10"),
        ("body_entries", "sleep_score", "FLOAT"),
        ("workout_sessions", "duration_min", "INTEGER"),
        ("workout_sessions", "kcal_burned", "FLOAT"),
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


def ensure_default_profile():
    """Varmista että vähintään yksi profiili on olemassa ja että vanha
    profiloimaton data liitetään siihen. Näin sovellus toimii heti."""
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(text("SELECT id FROM profiles ORDER BY id LIMIT 1")).fetchone()
        if row is None:
            conn.execute(text(
                "INSERT INTO profiles (name, color, created_at) "
                "VALUES ('Minä', '#4f8cff', CURRENT_TIMESTAMP)"
            ))
            row = conn.execute(text("SELECT id FROM profiles ORDER BY id LIMIT 1")).fetchone()
        default_id = row[0]
        # Liitä profiloimaton (NULL) data oletusprofiiliin.
        conn.execute(text("UPDATE programs SET profile_id = :pid WHERE profile_id IS NULL"), {"pid": default_id})
        conn.execute(text("UPDATE workout_sessions SET profile_id = :pid WHERE profile_id IS NULL"), {"pid": default_id})


def ensure_seed_exercises():
    """Siemennä kattava liikekirjasto (kategoria + väline + oletussarjat) jos
    liikkeitä ei vielä ole. Moniniveliset saavat matalat toistot (voima),
    eristävät korkeammat (hypertrofia)."""
    from sqlalchemy import text

    # (nimi, kategoria, lihasryhmä, väline, sarjat, toistot, pääliike, laji)
    lib = [
        # Rinta
        ("Penkkipunnerrus", "rinta", "rintalihas", "tanko", 5, 5, True, "voimanosto"),
        ("Vinopenkki tanko", "rinta", "ylärinta", "tanko", 4, 8, False, None),
        ("Penkkipunnerrus käsipainoilla", "rinta", "rintalihas", "käsipainot", 4, 10, False, None),
        ("Vinopenkki käsipainoilla", "rinta", "ylärinta", "käsipainot", 3, 10, False, None),
        ("Taljaristikko", "rinta", "rintalihas", "talja", 3, 12, False, None),
        ("Dippi", "rinta", "alarinta", "keho", 3, 10, False, None),
        ("Punnerrus", "rinta", "rintalihas", "keho", 3, 15, False, None),
        # Selkä
        ("Maastaveto", "selkä", "selkä/takaketju", "tanko", 5, 5, True, "voimanosto"),
        ("Ylätalja eteen", "selkä", "leveä selkälihas", "talja", 4, 10, False, None),
        ("Alatalja soutu", "selkä", "selkä", "talja", 4, 10, False, None),
        ("Tankosoutu", "selkä", "selkä", "tanko", 4, 8, False, None),
        ("Käsipainosoutu", "selkä", "selkä", "käsipainot", 3, 10, False, None),
        ("Leuanveto", "selkä", "leveä selkälihas", "keho", 4, 8, False, None),
        ("T-tankosoutu", "selkä", "selkä", "tanko", 4, 10, False, None),
        # Jalat
        ("Takakyykky", "jalat", "etureisi", "tanko", 5, 5, True, "voimanosto"),
        ("Etukyykky", "jalat", "etureisi", "tanko", 4, 6, False, None),
        ("Jalkaprässi", "jalat", "etureisi", "kone", 4, 10, False, None),
        ("Askelkyykky", "jalat", "etureisi/pakara", "käsipainot", 3, 12, False, None),
        ("Bulgarian askelkyykky", "jalat", "etureisi/pakara", "käsipainot", 3, 10, False, None),
        ("Romanialainen maastaveto", "jalat", "takareisi", "tanko", 4, 8, False, None),
        ("Jalkojen ojennus", "jalat", "etureisi", "kone", 3, 15, False, None),
        ("Jalkojen koukistus", "jalat", "takareisi", "kone", 3, 12, False, None),
        ("Pohjenousu", "pohkeet", "pohje", "kone", 4, 15, False, None),
        ("Lantionnosto", "jalat", "pakara", "tanko", 3, 12, False, None),
        # Olkapäät
        ("Pystypunnerrus", "olkapäät", "olkapää", "tanko", 5, 5, False, None),
        ("Pystypunnerrus käsipainoilla", "olkapäät", "olkapää", "käsipainot", 4, 10, False, None),
        ("Sivunostot", "olkapäät", "sivuolkapää", "käsipainot", 3, 15, False, None),
        ("Etunostot", "olkapäät", "etuolkapää", "käsipainot", 3, 12, False, None),
        ("Vipunostot taakse", "olkapäät", "takaolkapää", "käsipainot", 3, 15, False, None),
        ("Pystysoutu", "olkapäät", "olkapää/lapa", "tanko", 3, 12, False, None),
        ("Face pull", "olkapäät", "takaolkapää", "talja", 3, 15, False, None),
        # Hauis
        ("Hauiskääntö tanko", "hauis", "hauis", "tanko", 3, 10, False, None),
        ("Hauiskääntö käsipaino", "hauis", "hauis", "käsipainot", 3, 12, False, None),
        ("Vasarakääntö", "hauis", "hauis/kyynärvarsi", "käsipainot", 3, 12, False, None),
        ("Taljahauis", "hauis", "hauis", "talja", 3, 15, False, None),
        # Ojentajat
        ("Ranskalainen punnerrus", "ojentajat", "ojentaja", "tanko", 3, 10, False, None),
        ("Taljapunnerrus", "ojentajat", "ojentaja", "talja", 3, 12, False, None),
        ("Kapea penkki", "ojentajat", "ojentaja", "tanko", 4, 8, False, None),
        ("Ojentajan punnerrus köysi", "ojentajat", "ojentaja", "talja", 3, 15, False, None),
        # Vatsa / keskivartalo
        ("Vatsarutistus", "vatsa", "vatsalihas", "keho", 3, 20, False, None),
        ("Lankku", "vatsa", "keskivartalo", "keho", 3, 60, False, None),
        ("Riipunta jalannosto", "vatsa", "alavatsa", "keho", 3, 15, False, None),
        ("Taljarutistus", "vatsa", "vatsalihas", "talja", 3, 20, False, None),
        # Olympia
        ("Tempaus", "olympia", "koko keho", "tanko", 5, 3, True, "olympia"),
        ("Rinnalleveto ja työntö", "olympia", "koko keho", "tanko", 5, 2, True, "olympia"),
        ("Kahvakuulaheilautus", "jalat", "takaketju", "kahvakuula", 3, 15, False, None),
    ]
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM exercises")).scalar()
        if count and count > 0:
            return
        for name, cat, mg, eq, sets, reps, main, sport in lib:
            conn.execute(
                text("INSERT INTO exercises (name, category, muscle_group, equipment, "
                     "default_sets, default_reps, is_main_lift, sport, unit, created_at) "
                     "VALUES (:n, :c, :m, :e, :s, :r, :main, :sp, 'kg', CURRENT_TIMESTAMP)"),
                {"n": name, "c": cat, "m": mg, "e": eq, "s": sets, "r": reps,
                 "main": 1 if main else 0, "sp": sport},
            )


def ensure_seed_foods():
    """Siemennä yleiset ruoka-aineet (makrot per 100 g) jos kirjasto on tyhjä."""
    from sqlalchemy import text

    common = [
        # (nimi, kcal, prot, hiili, rasva, oletusgrammat)
        ("Maitorahka (rasvaton)", 60, 11, 4, 0.2, 200),
        ("Banaani", 89, 1.1, 23, 0.3, 120),
        ("Kananmuna", 155, 13, 1.1, 11, 60),
        ("Kaurahiutaleet", 370, 13, 58, 7, 60),
        ("Kanan rintafilee", 110, 23, 0, 1.5, 150),
        ("Naudan jauheliha 10%", 180, 19, 0, 11, 150),
        ("Riisi (keitetty)", 130, 2.7, 28, 0.3, 200),
        ("Peruna (keitetty)", 87, 2, 20, 0.1, 200),
        ("Ruisleipä", 220, 7, 38, 1.5, 30),
        ("Oliiviöljy", 884, 0, 0, 100, 10),
    ]
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM foods")).scalar()
        if count and count > 0:
            return
        for name, kcal, prot, carb, fat, grams in common:
            conn.execute(
                text("INSERT INTO foods (name, kcal, protein_g, carbs_g, fat_g, default_grams, created_at) "
                     "VALUES (:n, :k, :p, :c, :f, :g, CURRENT_TIMESTAMP)"),
                {"n": name, "k": kcal, "p": prot, "c": carb, "f": fat, "g": grams},
            )
