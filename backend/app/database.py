"""Tietokantayhteys ja istunnon hallinta (SQLite + SQLAlchemy)."""
import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Tietokannan sijainti. Pilvessä voi osoittaa pysyvään levyyn ympäristömuuttujalla
# TREENI_DB_PATH (esim. /data/treeni.db). Muuten projektin juuren data/-kansio.
_db_env = os.environ.get("TREENI_DB_PATH")
if _db_env:
    DB_PATH = Path(_db_env)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
else:
    DATA_DIR = Path(__file__).resolve().parents[2] / "data"
    DATA_DIR.mkdir(exist_ok=True)
    DB_PATH = DATA_DIR / "treeni.db"

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

# Edistymiskuvat tallennetaan tietokannan viereen (data/photos).
PHOTOS_DIR = DB_PATH.parent / "photos"
PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

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
        ("workout_sessions", "feeling", "VARCHAR(12)"),
        ("workout_sessions", "feeling_note", "TEXT"),
        ("foods", "category", "VARCHAR(60)"),
        ("foods", "is_favorite", "BOOLEAN DEFAULT 0"),
        ("exercises", "description", "TEXT"),
        ("programs", "start_date", "DATE"),
        ("programs", "end_date", "DATE"),
        ("exercises", "per_hand", "BOOLEAN DEFAULT 0"),
        ("profiles", "creatine", "BOOLEAN DEFAULT 0"),
        ("programs", "auto_progress", "BOOLEAN DEFAULT 0"),
        ("body_entries", "steps", "FLOAT"),
        ("body_entries", "water_l", "FLOAT"),
        ("foods", "fiber_g", "FLOAT DEFAULT 0"),
        ("foods", "sugar_g", "FLOAT DEFAULT 0"),
        ("foods", "sodium_mg", "FLOAT DEFAULT 0"),
        ("foods", "alcohol_g", "FLOAT DEFAULT 0"),
        ("workout_exercises", "swap_reason", "VARCHAR(20)"),
        ("workout_exercises", "swapped_from", "VARCHAR(120)"),
        ("profiles", "experience", "VARCHAR(20)"),
        ("profiles", "training_years", "FLOAT"),
        ("profiles", "goal", "VARCHAR(20)"),
        ("profiles", "days_per_week", "INTEGER"),
        ("profiles", "pin_hash", "VARCHAR(200)"),
        ("profiles", "public_note", "VARCHAR(200)"),
        ("profiles", "hide_from_community", "BOOLEAN DEFAULT 0"),
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
        ("Pystypunnerrus", "olkapäät", "olkapää", "tanko", 5, 5, True, None),
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


# Laaja suomalainen ruokakirjasto. Arvot per 100 g (juomat per 100 ml ≈ 100 g).
# (nimi, kategoria, kcal, prot, hiili, rasva, oletusgrammat)
FOOD_LIBRARY = [
    # --- Hedelmät & marjat ---
    ("Banaani", "hedelmät & marjat", 89, 1.1, 23, 0.3, 120),
    ("Omena", "hedelmät & marjat", 52, 0.3, 14, 0.2, 150),
    ("Appelsiini", "hedelmät & marjat", 47, 0.9, 12, 0.1, 130),
    ("Mansikka", "hedelmät & marjat", 33, 0.7, 8, 0.3, 100),
    ("Mustikka", "hedelmät & marjat", 57, 0.7, 14, 0.3, 100),
    ("Vadelma", "hedelmät & marjat", 52, 1.2, 12, 0.7, 100),
    ("Viinirypäleet", "hedelmät & marjat", 69, 0.7, 18, 0.2, 100),
    ("Päärynä", "hedelmät & marjat", 57, 0.4, 15, 0.1, 150),
    ("Ananas", "hedelmät & marjat", 50, 0.5, 13, 0.1, 100),
    ("Avokado", "hedelmät & marjat", 160, 2, 9, 15, 100),
    # --- Vihannekset ---
    ("Tomaatti", "vihannekset", 18, 0.9, 3.9, 0.2, 100),
    ("Kurkku", "vihannekset", 15, 0.7, 3.6, 0.1, 100),
    ("Porkkana", "vihannekset", 41, 0.9, 10, 0.2, 80),
    ("Parsakaali", "vihannekset", 34, 2.8, 7, 0.4, 100),
    ("Pinaatti", "vihannekset", 23, 2.9, 3.6, 0.4, 50),
    ("Salaatti (jäävuori)", "vihannekset", 14, 0.9, 3, 0.1, 50),
    ("Sipuli", "vihannekset", 40, 1.1, 9, 0.1, 50),
    ("Paprika", "vihannekset", 31, 1, 6, 0.3, 100),
    # --- Kana (eri valmistustavat) ---
    ("Kanan rintafilee (raaka)", "kana", 110, 23, 0, 1.5, 150),
    ("Kanan rintafilee (kypsä)", "kana", 165, 31, 0, 3.6, 150),
    ("Kanan rintafilee (friteerattu)", "kana", 250, 22, 12, 13, 150),
    ("Kanan koipi-reisi (kypsä)", "kana", 210, 26, 0, 11, 150),
    ("Broileri nugetit", "kana", 280, 15, 17, 17, 100),
    ("Kalkkunaleike", "kana", 105, 22, 1, 1.5, 100),
    # --- Liha ---
    ("Naudan jauheliha 10%", "liha", 180, 19, 0, 11, 150),
    ("Naudan jauheliha 17%", "liha", 230, 17, 0, 18, 150),
    ("Naudan sisäfile (kypsä)", "liha", 215, 30, 0, 10, 150),
    ("Possun ulkofile (kypsä)", "liha", 195, 28, 0, 9, 150),
    ("Jauheliha-sika-nauta 23%", "liha", 280, 15, 0, 24, 150),
    ("Pekoni (paistettu)", "liha", 540, 37, 1.4, 42, 30),
    ("Nakit", "liha", 270, 11, 4, 24, 100),
    ("Lihapulla", "liha", 240, 14, 10, 16, 100),
    # --- Kala ---
    ("Lohi (kypsä)", "kala", 208, 22, 0, 13, 150),
    ("Kirjolohi (kypsä)", "kala", 190, 21, 0, 12, 150),
    ("Tonnikala vedessä", "kala", 100, 23, 0, 1, 100),
    ("Seiti (kypsä)", "kala", 90, 19, 0, 1, 150),
    ("Katkarapu", "kala", 99, 24, 0.2, 0.3, 100),
    # --- Kananmuna ---
    ("Kananmuna", "kananmuna", 155, 13, 1.1, 11, 60),
    ("Kananmunan valkuainen", "kananmuna", 52, 11, 0.7, 0.2, 33),
    # --- Pasta, riisi, peruna (raaka & kypsä) ---
    ("Pasta (kuiva)", "pasta & riisi", 360, 12, 71, 1.5, 80),
    ("Pasta (keitetty)", "pasta & riisi", 158, 5.8, 31, 0.9, 250),
    ("Täysjyväpasta (kuiva)", "pasta & riisi", 350, 13, 64, 2.5, 80),
    ("Riisi (kuiva)", "pasta & riisi", 360, 7, 79, 0.6, 75),
    ("Riisi (keitetty)", "pasta & riisi", 130, 2.7, 28, 0.3, 200),
    ("Basmatiriisi (keitetty)", "pasta & riisi", 121, 3, 25, 0.4, 200),
    ("Peruna (raaka)", "pasta & riisi", 77, 2, 17, 0.1, 200),
    ("Peruna (keitetty)", "pasta & riisi", 87, 2, 20, 0.1, 200),
    ("Bataatti (keitetty)", "pasta & riisi", 90, 2, 21, 0.1, 200),
    ("Ranskalaiset (uuni)", "pasta & riisi", 165, 3, 28, 5, 150),
    ("Lohkoperunat", "pasta & riisi", 150, 2.5, 24, 5, 150),
    # --- Maitotuotteet ---
    ("Maitorahka (rasvaton)", "maitotuotteet", 60, 11, 4, 0.2, 200),
    ("Maitorahka (maustettu)", "maitotuotteet", 75, 8, 9, 0.2, 200),
    ("Marjarahka", "maitotuotteet", 80, 8, 10, 1, 200),
    ("Kreikkalainen jogurtti", "maitotuotteet", 97, 9, 4, 5, 150),
    ("Maustamaton jogurtti", "maitotuotteet", 60, 3.5, 5, 3, 150),
    ("Raejuusto", "maitotuotteet", 98, 12, 3, 4.3, 150),
    ("Skyr", "maitotuotteet", 63, 11, 4, 0.2, 150),
    ("Voi", "maitotuotteet", 737, 0.7, 0.7, 81, 10),
    ("Kerma 15%", "maitotuotteet", 165, 2.5, 4, 15, 50),
    # --- Juusto ---
    ("Edam-juusto 17%", "juusto", 270, 28, 0, 17, 30),
    ("Mozzarella", "juusto", 250, 18, 3, 18, 50),
    ("Fetajuusto", "juusto", 260, 14, 4, 21, 50),
    ("Sulatejuusto", "juusto", 230, 10, 7, 18, 20),
    # --- Leipä & viljat ---
    ("Ruisleipä", "leipä & viljat", 220, 7, 38, 1.5, 30),
    ("Kaurahiutaleet", "leipä & viljat", 370, 13, 58, 7, 60),
    ("Paahtoleipä", "leipä & viljat", 265, 9, 49, 3.5, 30),
    ("Näkkileipä", "leipä & viljat", 340, 10, 64, 2, 15),
    ("Müsli", "leipä & viljat", 360, 9, 60, 8, 60),
    ("Mysli-patukka", "leipä & viljat", 410, 6, 65, 14, 35),
    # --- Pähkinät & rasvat ---
    ("Maapähkinä", "pähkinät & rasvat", 567, 26, 16, 49, 30),
    ("Maapähkinävoi", "pähkinät & rasvat", 600, 25, 14, 50, 30),
    ("Manteli", "pähkinät & rasvat", 579, 21, 22, 50, 30),
    ("Cashew", "pähkinät & rasvat", 553, 18, 30, 44, 30),
    ("Oliiviöljy", "pähkinät & rasvat", 884, 0, 0, 100, 10),
    ("Rypsiöljy", "pähkinät & rasvat", 884, 0, 0, 100, 10),
    # --- Kastikkeet ---
    ("Ketsuppi", "kastikkeet", 110, 1.2, 26, 0.1, 20),
    ("Sinappi", "kastikkeet", 95, 5, 9, 4, 15),
    ("Majoneesi (Hellmann's)", "kastikkeet", 680, 1, 2, 75, 20),
    ("Kevytmajoneesi", "kastikkeet", 320, 1, 8, 31, 20),
    ("BBQ-kastike", "kastikkeet", 170, 1, 40, 0.5, 25),
    ("Sweet chili -kastike", "kastikkeet", 230, 0.5, 56, 0.2, 25),
    ("Soijakastike", "kastikkeet", 60, 8, 6, 0, 15),
    ("Pestokastike", "kastikkeet", 450, 5, 6, 45, 25),
    # --- Juomat ---
    ("Rasvaton maito", "juomat", 33, 3.4, 5, 0.1, 200),
    ("Kevytmaito 1.5%", "juomat", 47, 3.3, 5, 1.5, 200),
    ("Täysmaito 3.5%", "juomat", 63, 3.2, 4.8, 3.5, 200),
    ("Kaurajuoma", "juomat", 45, 1, 7, 1.5, 200),
    ("Appelsiinimehu", "juomat", 45, 0.7, 10, 0.2, 200),
    ("Mehutiiviste (laimennettu)", "juomat", 40, 0, 10, 0, 200),
    ("Limsa (sokeri)", "juomat", 42, 0, 11, 0, 330),
    ("Light-limsa", "juomat", 1, 0, 0, 0, 330),
    ("Energiajuoma", "juomat", 45, 0, 11, 0, 250),
    ("Kahvi (musta)", "juomat", 2, 0.1, 0, 0, 200),
    ("Urheilujuoma", "juomat", 30, 0, 7, 0, 500),
    # --- Alkoholi (annoksina) ---
    ("Olut (lager) 0.33 l", "alkoholi", 43, 0.5, 3.5, 0, 330),
    ("Olut (lager) 0.5 l", "alkoholi", 43, 0.5, 3.5, 0, 500),
    ("IPA-olut 0.33 l", "alkoholi", 55, 0.6, 5, 0, 330),
    ("Lonkero 0.33 l", "alkoholi", 47, 0, 5, 0, 330),
    ("Punaviini (lasi 0.2 l)", "alkoholi", 85, 0.1, 2.6, 0, 200),
    ("Valkoviini (lasi 0.2 l)", "alkoholi", 82, 0.1, 2.6, 0, 200),
    ("Siideri (kuiva) 0.33 l", "alkoholi", 45, 0, 3, 0, 330),
    # --- Herkut ---
    ("Perunalastut (sipsit)", "herkut", 535, 6, 53, 33, 50),
    ("Nacho-lastut", "herkut", 500, 7, 60, 25, 50),
    ("Popcorn (voi)", "herkut", 480, 8, 55, 25, 30),
    ("Suklaa (maito)", "herkut", 535, 7, 58, 30, 30),
    ("Tumma suklaa 70%", "herkut", 600, 8, 46, 43, 30),
    ("Karkkipussi (sekoitus)", "herkut", 350, 4, 80, 0.5, 50),
    ("Lakritsi", "herkut", 325, 4, 75, 0.5, 40),
    ("Jäätelö (vanilja)", "herkut", 200, 3.5, 24, 10, 100),
    ("Donitsi", "herkut", 420, 6, 50, 22, 60),
    ("Keksi (suklaa)", "herkut", 480, 6, 65, 22, 25),
    ("Korvapuusti", "herkut", 360, 7, 55, 12, 80),
    # --- Proteiinijauheet & lisät ---
    ("Heraproteiini (whey 80)", "proteiinijauheet", 380, 80, 6, 6, 30),
    ("Heraisolaatti (whey 90)", "proteiinijauheet", 370, 90, 2, 1, 30),
    ("Hydrolysoitu hera (whey 100)", "proteiinijauheet", 375, 92, 1, 1, 30),
    ("Kaseiini", "proteiinijauheet", 360, 78, 8, 2, 30),
    ("Kasviproteiini (herne)", "proteiinijauheet", 400, 80, 5, 7, 30),
    ("Painonlisääjä (mass gainer)", "proteiinijauheet", 380, 20, 65, 4, 100),
    ("Proteiinipatukka", "proteiinijauheet", 350, 33, 35, 9, 55),
    ("Proteiinivanukas", "proteiinijauheet", 75, 10, 6, 1, 200),
    # --- Einekset ---
    ("Pizza (margherita)", "einekset", 250, 11, 30, 9, 300),
    ("Hampurilainen (iso)", "einekset", 250, 13, 20, 12, 250),
    ("Kebab-rulla", "einekset", 215, 12, 20, 10, 350),
    ("Sushi (8 palaa)", "einekset", 140, 5, 28, 1, 200),
    ("Lihapiirakka", "einekset", 280, 9, 32, 13, 150),
    ("Valmis lasagne", "einekset", 135, 7, 13, 6, 350),
]


def ensure_extra_exercises():
    """Lisää tietyt liikkeet jos ne puuttuvat (idempotentti, ajetaan aina).
    Näin olemassa olevat kannat saavat uudet liikkeet ilman uudelleenluontia."""
    from sqlalchemy import text

    # (nimi, kategoria, lihasryhmä, väline, sarjat, toistot, laji, per_hand)
    extra = [
        # Olympianostot
        ("Rinnalleveto", "olympia", "koko keho", "tanko", 5, 3, "olympia", 0),
        ("Työntö telineestä", "olympia", "olkapää/jalat", "tanko", 5, 2, "olympia", 0),
        ("Tempausveto", "olympia", "takaketju", "tanko", 4, 3, "olympia", 0),
        ("Rinnallevedon veto", "olympia", "takaketju", "tanko", 4, 3, "olympia", 0),
        ("Tempauskyykky (overhead squat)", "olympia", "koko keho", "tanko", 4, 4, "olympia", 0),
        ("Riipunnasta tempaus", "olympia", "koko keho", "tanko", 4, 2, "olympia", 0),
        # Käsipainoliikkeet (paino = per käsipaino)
        ("Vinopenkki käsipaino", "rinta", "ylärinta", "käsipainot", 4, 10, None, 1),
        ("Penkkipunnerrus käsipaino", "rinta", "rinta", "käsipainot", 4, 10, None, 1),
        ("Flyes käsipaino (vipunostot rinnalle)", "rinta", "rinta", "käsipainot", 3, 12, None, 1),
        ("Käsipainosoutu (yhden käden)", "selkä", "yläselkä", "käsipainot", 4, 10, None, 1),
        ("Pystypunnerrus käsipaino", "olkapää", "olkapää", "käsipainot", 4, 8, None, 1),
        ("Hauiskääntö käsipaino", "kädet", "hauis", "käsipainot", 3, 12, None, 1),
        ("Vasarakääntö käsipaino", "kädet", "hauis/kyynärvarsi", "käsipainot", 3, 12, None, 1),
        ("Yhden käden ojentajapunnerrus käsipaino", "kädet", "ojentaja", "käsipainot", 3, 12, None, 1),
        ("Ranskalainen punnerrus käsipaino", "kädet", "ojentaja", "käsipainot", 3, 12, None, 1),
        ("Käsipainokyykky (goblet)", "jalat", "etureidet/pakara", "käsipainot", 3, 12, None, 0),
        ("Bulgarialainen askelkyykky käsipaino", "jalat", "etureidet/pakara", "käsipainot", 3, 10, None, 1),
        # Taljat
        ("Alatalja soutu (kapea)", "selkä", "yläselkä", "talja", 4, 12, None, 0),
        ("Alatalja soutu (leveä)", "selkä", "yläselkä", "talja", 4, 12, None, 0),
        ("Ylätalja leveä", "selkä", "selän leveys", "talja", 4, 12, None, 0),
        ("Ylätalja kapea/myötäote", "selkä", "selän leveys", "talja", 4, 12, None, 0),
        ("Taljaveto kasvoille (face pull)", "olkapää", "takaolkapää", "talja", 3, 15, None, 0),
        ("Ojentajapunnerrus taljassa (köysi)", "kädet", "ojentaja", "talja", 3, 14, None, 0),
        ("Hauiskääntö taljassa", "kädet", "hauis", "talja", 3, 14, None, 0),
        ("Taljavipunostot sivulle", "olkapää", "sivuolkapää", "talja", 3, 15, None, 1),
        ("Taljan crossover (rinta)", "rinta", "rinta", "talja", 3, 14, None, 0),
        # Laitteet / koneet
        ("Reisiojennus (kone)", "jalat", "etureidet", "kone", 3, 14, None, 0),
        ("Takareisikoukistus (kone)", "jalat", "takareidet", "kone", 3, 14, None, 0),
        ("Pakaralaite / lonkan ojennus (kone)", "jalat", "pakara", "kone", 3, 14, None, 0),
        ("Lähennys (kone, sisäreisi)", "jalat", "lähentäjät", "kone", 3, 15, None, 0),
        ("Loitonnus (kone, pakara/lonkka)", "jalat", "loitontajat", "kone", 3, 15, None, 0),
        ("Pohjenousu (kone)", "jalat", "pohkeet", "kone", 4, 12, None, 0),
        ("Rintaprässi (kone)", "rinta", "rinta", "kone", 3, 12, None, 0),
        ("Vipunostot rinnalle (pec deck)", "rinta", "rinta", "kone", 3, 14, None, 0),
        ("Soutu (kone)", "selkä", "yläselkä", "kone", 4, 12, None, 0),
        ("Olkapääprässi (kone)", "olkapää", "olkapää", "kone", 3, 12, None, 0),
        ("Takaolkapää (reverse pec deck)", "olkapää", "takaolkapää", "kone", 3, 15, None, 0),
        ("Vatsarutistus (kone)", "keskivartalo", "vatsa", "kone", 3, 15, None, 0),
        ("Selän ojennus (kone/penkki)", "selkä", "alaselkä", "kone", 3, 15, None, 0),
        ("Hack-kyykky (kone)", "jalat", "etureidet", "kone", 4, 10, None, 0),
        # Hauis- ja ojentajavariaatiot
        ("Hauiskääntö vinopenkissä (käsipaino)", "kädet", "hauis (pitkä pää)", "käsipainot", 3, 12, None, 1),
        ("Drag curl (tanko)", "kädet", "hauis", "tanko", 3, 10, None, 0),
        ("Scott-kääntö (preacher)", "kädet", "hauis (lyhyt pää)", "tanko", 3, 12, None, 0),
        ("Keskitetty hauiskääntö (concentration)", "kädet", "hauis huippu", "käsipainot", 3, 12, None, 1),
        ("Spider curl", "kädet", "hauis", "käsipainot", 3, 12, None, 1),
        ("Zottman-kääntö", "kädet", "hauis/kyynärvarsi", "käsipainot", 3, 12, None, 1),
        ("Kapea penkkipunnerrus", "kädet", "ojentaja/rinta", "tanko", 4, 8, None, 0),
        ("Ojentajaprässi otsalle (skull crusher)", "kädet", "ojentaja", "tanko", 3, 10, None, 0),
        ("Ojentajapotku (kickback, käsipaino)", "kädet", "ojentaja", "käsipainot", 3, 14, None, 1),
        ("Ranneväännöt (kyynärvarsi)", "kädet", "kyynärvarsi", "tanko", 3, 15, None, 0),
    ]
    with engine.begin() as conn:
        existing = {r[0] for r in conn.execute(text("SELECT name FROM exercises")).fetchall()}
        for name, cat, mg, eq, sets, reps, sport, per_hand in extra:
            if name in existing:
                continue
            conn.execute(
                text("INSERT INTO exercises (name, category, muscle_group, equipment, "
                     "default_sets, default_reps, is_main_lift, sport, unit, per_hand, created_at) "
                     "VALUES (:n, :c, :m, :e, :s, :r, 0, :sport, 'kg', :ph, CURRENT_TIMESTAMP)"),
                {"n": name, "c": cat, "m": mg, "e": eq, "s": sets, "r": reps,
                 "sport": sport, "ph": per_hand},
            )
        # Merkitse käsipainoliikkeet per_hand:ksi (paino = yhden käsipainon paino)
        conn.execute(text(
            "UPDATE exercises SET per_hand = 1 "
            "WHERE equipment = 'käsipainot' AND (per_hand IS NULL OR per_hand = 0)"))
        # Pystypunnerrus (tanko) on kätevä voimaa mittaava pääliike (OHP) -> voimataso.
        # Ei lajitotaliin (sport pysyy tyhjänä, ettei se sekoita voimanoston yhteistulosta).
        conn.execute(text(
            "UPDATE exercises SET is_main_lift = 1 WHERE name = 'Pystypunnerrus'"))


EXERCISE_DESCRIPTIONS = {
    "Penkkipunnerrus": "Idea: kehittää rinnan, olkapään etuosan ja ojentajan voimaa. "
        "Maaten penkille, lapatuki kasaan, tanko rinnan alaosaan hallitusti, työnnä ylös jalat tukena.",
    "Takakyykky": "Idea: alavartalon (etureidet, pakarat) ja keskivartalon päävoimaliike. "
        "Tanko ylä-selälle, rintakehä ylös, kyykkää kantapäät maassa vähintään reidet vaakaan, työnnä ylös.",
    "Maastaveto": "Idea: koko takaketjun (selkä, pakarat, takareidet) voimaliike. "
        "Tanko lähelle säärtä, selkä suorana, työnnä lattiasta jaloilla ja ojenna lonkka loppuun.",
    "Pystypunnerrus": "Idea: olkapäiden ja ojentajien pystysuora työntövoima. "
        "Tanko/käsipainot hartioilta suoraan ylös pään yli, keskivartalo tiukkana, vältä selän notkoa.",
    "Tankosoutu": "Idea: yläselän paksuus ja vetovoima. Lantiosta etunoja, selkä suorana, "
        "vedä tanko alavatsaa kohti lapaa vetäen, laske hallitusti.",
    "Ylätalja eteen": "Idea: leveän selkälihaksen leveys. Vedä tanko rintaan lapaa alas vetäen, "
        "kyynärpäät alas ja taakse, hallittu palautus.",
    "Leuanveto": "Idea: leveä selkä ja hauis omalla kehonpainolla. Vedä leuka tangon yli "
        "lapaa alas vetäen, laske täysin suoriin käsiin.",
    "Hauiskääntö tanko": "Idea: hauiksen eristävä liike. Kyynärpäät paikallaan kyljissä, "
        "käännä tanko ylös hauista jännittäen, laske hallitusti.",
    "Romanialainen maastaveto": "Idea: takareiden ja pakaran venyttävä voima. Lähes suorin jaloin "
        "työnnä lantio taakse, tanko lähellä jalkoja, tunne venytys takareisissä.",
    "Jalkaprässi": "Idea: etureiden ja pakaran turvallinen massaliike. Jalat lavalla, "
        "laske polvet hallitusti ~90°, työnnä takaisin lukitsematta polvia.",
    "Tempaus": "Idea: olympianosto — tanko lattialta suoraan käsien varaan yhdellä vedolla. "
        "Vaatii tekniikkaa: räjähtävä veto, nopea alituki. Tekniikka ennen kuormaa.",
    "Rinnalleveto ja työntö": "Idea: olympianosto — tanko rinnalle ja siitä työntäen pään yli. "
        "Kaksiosainen räjähtävä liike, vaatii liikkuvuutta ja tekniikkaa.",
    "Dippi": "Idea: alarinnan ja ojentajan kehonpainoliike. Laske hallitusti kunnes olkavarsi "
        "vaakaan, työnnä ylös. Hieman etunoja korostaa rintaa.",
    "Pohjenousu": "Idea: pohkeen eristävä liike. Nouse varpaille täydellä liikeradalla, "
        "tauko huipulla, laske kantapää hallitusti alas asti.",
    "Sivunostot": "Idea: olkapään sivuosa (leveys). Nosta käsipainot sivuille hartiatasoon, "
        "kevyt kyynärtaivutus, laske hallitusti — älä heilauta.",
    "Hauiskääntö vinopenkissä (käsipaino)": "Idea: hauiksen pitkä pää venytettynä (huippu). Istu vinopenkille "
        "taakse nojaten, kädet roikkuvat suorina takana. Käännä käsipainot ylös kyynärpäät paikallaan — "
        "korostaa hauiksen alaosaa ja huippua. Paino = per käsipaino.",
    "Drag curl (tanko)": "Idea: hauis ilman etuolkapään apua. Vedä tanko YLÖS vartaloa pitkin niin että "
        "kyynärpäät menevät taakse ja tanko pysyy lähellä kehoa — ei eteen heilautusta. Hauis tekee työn.",
    "Scott-kääntö (preacher)": "Idea: hauiksen lyhyt pää eristettynä. Olkavarret Scott-penkin tyynyllä, "
        "käännä tanko ylös ja laske täyteen venytykseen hallitusti. Estää huijaamisen selällä.",
    "Keskitetty hauiskääntö (concentration)": "Idea: hauiksen huippu ja erottelu. Istu, kyynärpää reiden "
        "sisäpintaa vasten, käännä käsipaino ylös yhdellä kädellä keskittyen supistukseen. Paino = per käsi.",
    "Kapea penkkipunnerrus": "Idea: ojentajapainotteinen penkki. Ote hartioita kapeampi, kyynärpäät "
        "lähellä kylkiä, tanko alarintaan. Kehittää ojentajaa ja lukko-osan penkkivoimaa.",
    "Ojentajaprässi otsalle (skull crusher)": "Idea: ojentajan pitkä pää. Selinmakuulla laske tanko otsan "
        "taakse kyynärpäät paikallaan, ojenna ylös. Pidä liike hallittuna kyynärnivelten suojaamiseksi.",
    "Reisiojennus (kone)": "Idea: etureiden eristävä liike. Ojenna polvet suoriksi hallitusti, tauko "
        "huipulla, laske jarruttaen. Hyvä etureiden lämmittelyyn ja loppurutistukseen.",
    "Takareisikoukistus (kone)": "Idea: takareiden eristävä liike. Koukista kantapäät pakaroita kohti "
        "hallitusti, purista huipulla, laske jarruttaen. Tasapainottaa etureisivoimaa.",
    "Alatalja soutu (leveä)": "Idea: yläselän leveys ja takaolkapää. Leveä ote, vedä kahva rintakehän "
        "yläosaan kyynärpäät ulos, purista lapoja yhteen. Selkä suorana, ei kiskomista alaselällä.",
    "Ylätalja leveä": "Idea: selän leveys (V-malli). Leveä ote, vedä tanko rintaan lapaa alas ja taakse "
        "vetäen, kyynärpäät alas. Palauta täyteen venytykseen hallitusti.",
    "Alatalja soutu": "Idea: yläselän paksuus istuen. Selkä suorana, vedä kahva vatsaa kohti "
        "lapoja yhteen puristaen, palauta käsivarret suoriksi hallitusti.",
    "Alatalja soutu (kapea)": "Idea: yläselän keskiosa ja paksuus. Kapea ote, vedä kahva alavatsaan "
        "kyynärpäät kylkiä pitkin, purista lapoja, palauta venytykseen.",
    "Askelkyykky": "Idea: etureiden ja pakaran yksijalkatyö + tasapaino. Astu pitkä askel eteen, "
        "laske takapolvi lähelle lattiaa, työnnä etujalalla takaisin. Paino = lisäpaino yhteensä.",
    "Bulgarialainen askelkyykky käsipaino": "Idea: yhden jalan etureisi/pakaraliike. Takajalka penkillä, "
        "laske hallitusti etujalan varassa, työnnä ylös. Paino = per käsipaino. Tehokas myös tasapainolle.",
    "Bulgarian askelkyykky": "Idea: yhden jalan etureisi/pakaraliike. Takajalka penkillä, laske "
        "hallitusti etujalan varassa, työnnä kantapäällä ylös. Kova pakaralle pienelläkin painolla.",
    "Etukyykky": "Idea: etureisipainotteinen kyykky pystymmällä selällä. Tanko etuhartioilla, "
        "kyynärpäät ylös, kyykkää syvään keskivartalo tiukkana. Kevyempi alaselälle kuin takakyykky.",
    "Etunostot": "Idea: olkapään etuosan eristävä liike. Nosta paino suorin käsin eteen hartiatasoon, "
        "laske hallitusti. Yleensä riittää vähän — etuolkapää saa työtä punnerruksistakin.",
    "Face pull": "Idea: takaolkapää ja lapaa tukevat lihakset — ryhdin paras kaveri. Vedä köysi "
        "kasvoja kohti kyynärpäät ylhäällä ja ulkona, käännä kädet taakse. Kevyt paino, iso hyöty.",
    "Flyes käsipaino (vipunostot rinnalle)": "Idea: rinnan eristävä venyttävä liike. Selinmakuulla vie "
        "käsipainot kaarella sivuille kevyt kyynärtaivutus, tunne venytys rinnassa, tuo yhteen kaarella.",
    "Hack-kyykky (kone)": "Idea: etureiden ohjattu massaliike. Selkä tuettuna kelkkaa vasten, laske "
        "syvään hallitusti, työnnä lukitsematta polvia. Turvallinen tapa kuormittaa reidet raskaasti.",
    "Hauiskääntö käsipaino": "Idea: hauiksen perusliike vapailla painoilla. Kyynärpäät kyljissä, käännä "
        "painot ylös (halutessa kierrolla), laske hallitusti. Paino = per käsipaino.",
    "Hauiskääntö taljassa": "Idea: hauis tasaisella vastuksella koko liikeradalla. Kyynärpäät paikallaan, "
        "käännä kahva ylös, jarruta paluu. Talja pitää jännityksen myös ala-asennossa.",
    "Jalkojen koukistus": "Idea: takareiden eristävä liike koneessa. Koukista kantapäät pakaroita kohti "
        "hallitusti, purista huipulla, laske jarruttaen.",
    "Jalkojen ojennus": "Idea: etureiden eristävä liike koneessa. Ojenna polvet hallitusti suoriksi, "
        "pieni tauko huipulla, laske jarruttaen.",
    "Kahvakuulaheilautus": "Idea: takaketjun (pakarat, takareidet) räjähtävä lantiosarana. Heilauta kuula "
        "lantion työnnöllä hartiatasoon — kädet ovat vain koukut, voima tulee lantiosta. Hyvä myös kunnolle.",
    "Kapea penkki": "Idea: ojentajapainotteinen penkkipunnerrus. Ote hartioita kapeampi, kyynärpäät "
        "lähellä kylkiä, tanko alarintaan ja työnnä ylös. Vahvistaa penkin lukko-osaa.",
    "Käsipainokyykky (goblet)": "Idea: kyykkytekniikan opettelu ja etureisi/pakaratyö. Pidä käsipainoa "
        "pystyssä rintaa vasten, kyykkää syvään kyynärpäät polvien sisäpuolelle, työnnä ylös.",
    "Käsipainosoutu": "Idea: yläselän vetoliike käsipainoilla. Etunojassa vedä painot alavatsaa kohti "
        "lapoja puristaen, laske hallitusti. Paino = per käsipaino.",
    "Käsipainosoutu (yhden käden)": "Idea: yläselän yksipuolinen veto — tukikäsi penkillä sallii raskaan "
        "kuorman turvallisesti. Vedä paino lonkkaa kohti kiertämättä vartaloa, laske venytykseen.",
    "Lankku": "Idea: keskivartalon tukilihasten staattinen pito. Kyynärnoja, vartalo suorana kuin lauta, "
        "pakara ja vatsa tiukkana. Kirjaa kesto sekunteina toistoihin.",
    "Lantionnosto": "Idea: pakaran pääliike (hip thrust). Yläselkä penkkiä vasten, työnnä lantio ylös "
        "pakaraa puristaen täyteen ojennukseen, laske hallitusti. Leuka rintaan, ei selän notkoa.",
    "Loitonnus (kone, pakara/lonkka)": "Idea: keskipakaran eristävä liike. Työnnä polvia ulospäin vastusta "
        "vasten istuen, palauta hallitusti. Tukee lonkan hallintaa kyykyissä ja juoksussa.",
    "Lähennys (kone, sisäreisi)": "Idea: sisäreiden eristävä liike. Purista polvet yhteen vastusta vasten "
        "hallitusti, palauta jarruttaen. Tasapainottaa reiden kuormitusta.",
    "Ojentajan punnerrus köysi": "Idea: ojentajan eristävä liike köydellä. Kyynärpäät kyljissä, ojenna "
        "köysi alas ja levitä päät alhaalla, palauta hallitusti kyynärpäät paikallaan.",
    "Ojentajapotku (kickback, käsipaino)": "Idea: ojentajan huippusupistus. Etunojassa olkavarsi vaakatasossa, "
        "ojenna kyynärnivel suoraksi ja purista, palauta hallitusti. Kevyt paino, tarkka suoritus.",
    "Ojentajapunnerrus taljassa (köysi)": "Idea: ojentajan perusliike taljassa. Kyynärpäät kyljissä "
        "paikallaan, ojenna köysi alas, levitä päät ala-asennossa, jarruta paluu.",
    "Olkapääprässi (kone)": "Idea: olkapäiden ohjattu punnerrus — helppo kuormittaa turvallisesti. "
        "Työnnä kahvat ylös täyteen ojennukseen, laske hallitusti korvien tasolle.",
    "Pakaralaite / lonkan ojennus (kone)": "Idea: pakaran eristävä ojennus koneessa. Työnnä jalka/lantio "
        "taakse-ylös pakaraa puristaen, palauta hallitusti.",
    "Penkkipunnerrus käsipaino": "Idea: rinnan punnerrus vapailla painoilla — pidempi liikerata ja "
        "tasapainotyö. Laske painot rinnan tasolle, työnnä ylös ja hieman yhteen. Paino = per käsipaino.",
    "Penkkipunnerrus käsipainoilla": "Idea: rinnan punnerrus vapailla painoilla — pidempi liikerata ja "
        "tasapainotyö kuin tangolla. Laske rinnan tasolle, työnnä ylös ja hieman yhteen. Paino = per käsipaino.",
    "Pohjenousu (kone)": "Idea: pohkeen eristävä liike lisäkuormalla. Nouse varpaille täydellä radalla, "
        "tauko huipulla, laske kantapää alas venytykseen asti.",
    "Punnerrus": "Idea: rinnan ja ojentajan kehonpainoliike. Vartalo suorana, laske rinta lähelle lattiaa, "
        "työnnä ylös. Kirjaa lisäpaino jos käytät levyä selässä; muuten paino 0.",
    "Pystypunnerrus käsipaino": "Idea: olkapäiden punnerrus käsipainoilla — vapaampi rata ja enemmän "
        "tukilihastyötä kuin tangolla. Työnnä painot hartioilta ylös, laske korvien tasolle. Paino = per käsipaino.",
    "Pystypunnerrus käsipainoilla": "Idea: olkapäiden punnerrus käsipainoilla — vapaampi rata ja enemmän "
        "tukilihastyötä kuin tangolla. Työnnä painot hartioilta ylös pään yli. Paino = per käsipaino.",
    "Pystysoutu": "Idea: olkapään sivuosa ja epäkäslihas vetoliikkeenä. Vedä tanko/kahva leukaa kohti "
        "kyynärpäät edellä hartiatasoon. Pidä ote reilun hartianlevyisenä olkapäiden säästämiseksi.",
    "Ranneväännöt (kyynärvarsi)": "Idea: kyynärvarren ja puristusvoiman eristävä liike. Kyynärvarret "
        "tuettuna, väännä rannetta ylös hallitusti, laske jarruttaen. Kevyt paino, paljon toistoja.",
    "Ranskalainen punnerrus": "Idea: ojentajan pitkän pään venyttävä liike. Selinmakuulla tai istuen "
        "laske paino pään taakse kyynärpäät paikallaan, ojenna ylös. Hallittu tempo suojaa kyynärniveliä.",
    "Ranskalainen punnerrus käsipaino": "Idea: ojentajan pitkä pää käsipainolla. Laske paino pään taakse "
        "kyynärpäät ylhäällä paikallaan, ojenna ylös. Voi tehdä istuen tai maaten.",
    "Riipunnasta tempaus": "Idea: tempauksen osaharjoite ilman lattiavetoa — tanko aloittaa reisiltä. "
        "Räjähtävä lantion ojennus ja nopea alituki. Opettaa vedon loppuosan tekniikkaa.",
    "Riipunta jalannosto": "Idea: alavatsan haastava kehonpainoliike. Riipu tangosta, nosta jalat "
        "(tai polvet) hallitusti ylös heilumatta, laske jarruttaen.",
    "Rinnallevedon veto": "Idea: rinnallevedon voimaosa ilman alitukea — veto ylös räjähtävästi ja "
        "hallittu lasku. Kehittää vetovoimaa tekniikkaa kuormittamatta.",
    "Rinnalleveto": "Idea: olympianoston ensimmäinen osa — tanko lattialta rinnalle räjähtävällä "
        "lantion ojennuksella ja nopealla alituella. Tekniikka ennen kuormaa.",
    "Rintaprässi (kone)": "Idea: rinnan ohjattu punnerrus — turvallinen tapa kuormittaa raskaasti ilman "
        "avustajaa. Työnnä kahvat eteen täyteen ojennukseen, palauta hallitusti.",
    "Selän ojennus (kone/penkki)": "Idea: alaselän ja pakaran ojentava liike. Taivuta vartalo alas "
        "selkä suorana, ojenna ylös pakaralla ja selän ojentajilla — älä yliojenna.",
    "Soutu (kone)": "Idea: yläselän ohjattu vetoliike. Rinta tukea vasten, vedä kahvat taakse lapoja "
        "puristaen, palauta hallitusti venytykseen.",
    "Spider curl": "Idea: hauiksen lyhyt pää huippusupistuksessa. Rinta vinopenkkiä vasten, olkavarret "
        "roikkuvat suoraan alas, käännä paino ylös ilman heijausta.",
    "T-tankosoutu": "Idea: yläselän paksuuden raskas vetoliike. Etunoja tangon yli, vedä kahva rintaa "
        "kohti lapoja puristaen, laske hallitusti. Pidä selkä suorana koko ajan.",
    "Takaolkapää (reverse pec deck)": "Idea: takaolkapään eristävä liike koneessa. Vie kahvat kaarella "
        "taakse hartiatasossa lapoja puristaen, palauta hallitusti. Tärkeä olkapään tasapainolle.",
    "Taljahauis": "Idea: hauis taljassa tasaisella jännityksellä. Kyynärpäät kyljissä paikallaan, käännä "
        "kahva ylös, jarruta paluu ala-asentoon asti.",
    "Taljan crossover (rinta)": "Idea: rinnan eristävä liike ristikkäistaljassa. Tuo kahvat kaarella "
        "yhteen rinnan edessä, purista, palauta venytykseen hallitusti. Jännitys säilyy koko radalla.",
    "Taljapunnerrus": "Idea: ojentajan perusliike taljassa. Kyynärpäät kyljissä paikallaan, paina kahva "
        "alas täyteen ojennukseen, jarruta paluu.",
    "Taljaristikko": "Idea: rinnan eristävä liike ristikkäistaljassa. Tuo kahvat yhteen kaarella rinnan "
        "edessä, purista huipulla, palauta hallitusti venytykseen.",
    "Taljarutistus": "Idea: vatsalihasten kuormitettava rutistus. Polvillaan köysi niskan takana, rutista "
        "vartalo alas vatsalla pyöristäen — älä vedä käsillä. Lisää painoa kun toistot ylittyvät.",
    "Taljaveto kasvoille (face pull)": "Idea: takaolkapää ja lavan tukilihakset. Vedä köysi kasvoja kohti "
        "kyynärpäät ylhäällä, käännä kädet taakse. Kevyt paino, hallittu suoritus — ryhtiliike.",
    "Taljavipunostot sivulle": "Idea: olkapään sivuosa taljassa — jännitys myös ala-asennossa. Nosta "
        "kahva sivulle hartiatasoon hallitusti, jarruta paluu.",
    "Tempauskyykky (overhead squat)": "Idea: tempauksen vastaanottoasennon voima ja liikkuvuus. Tanko "
        "suorilla käsillä pään yllä leveällä otteella, kyykkää syvään tanko lapaluiden päällä linjassa.",
    "Tempausveto": "Idea: tempauksen voimaosa ilman alitukea. Vedä tanko räjähtävästi lantion ojennuksella "
        "ylös leveällä otteella, hallittu lasku. Kehittää vedon voimaa turvallisesti.",
    "Työntö telineestä": "Idea: työnnön harjoittelu ilman rinnallevetoa — tanko telineestä hartioilta. "
        "Pieni jalkojen dippi ja räjähtävä työntö pään yli, jalat ottavat vastaan.",
    "Vasarakääntö": "Idea: hauis + kyynärvarren pitkät lihakset. Käännä painot ylös peukalot ylöspäin "
        "(vasaraote), kyynärpäät paikallaan. Kasvattaa käsivarren paksuutta.",
    "Vasarakääntö käsipaino": "Idea: hauis + kyynärvarsi vasaraotteella (peukalot ylös). Käännä painot "
        "ylös kyynärpäät kyljissä, laske hallitusti. Paino = per käsipaino.",
    "Vatsarutistus": "Idea: vatsalihasten perusliike. Selinmakuulla rutista lapaluut irti lattiasta "
        "vatsalla — älä vedä niskasta. Hidas ja hallittu tehoaa kevyelläkin.",
    "Vatsarutistus (kone)": "Idea: vatsalihasten kuormitettava rutistus koneessa. Rutista vartalo eteen "
        "vatsalla pyöristäen, palauta hallitusti. Lisää painoa maltillisesti.",
    "Vinopenkki käsipaino": "Idea: ylärinnan punnerrus käsipainoilla — pitkä liikerata. Penkki ~30–45°, "
        "laske painot ylärinnan tasolle, työnnä ylös ja hieman yhteen. Paino = per käsipaino.",
    "Vinopenkki käsipainoilla": "Idea: ylärinnan punnerrus käsipainoilla — pitkä liikerata ja tasapainotyö. "
        "Penkki ~30–45°, laske ylärinnan tasolle, työnnä ylös. Paino = per käsipaino.",
    "Vinopenkki tanko": "Idea: ylärinnan ja etuolkapään punnerrus. Penkki ~30–45°, tanko solisluiden "
        "tasolle hallitusti, työnnä ylös. Täydentää tasapenkkiä ylärinnan osalta.",
    "Vipunostot rinnalle (pec deck)": "Idea: rinnan eristävä liike koneessa. Tuo kahvat kaarella yhteen "
        "rinnan edessä, purista huipulla, palauta hallitusti venytykseen.",
    "Vipunostot taakse": "Idea: takaolkapään eristävä liike. Etunojassa nosta painot kaarella sivuille-taakse "
        "lapoja puristaen, laske hallitusti. Kevyt paino, tarkka suoritus.",
    "Yhden käden ojentajapunnerrus käsipaino": "Idea: ojentajan yksipuolinen liike — paljastaa puolierot. "
        "Ojenna käsipaino pään yltä suoraksi kyynärpää paikallaan, laske pään taakse hallitusti.",
    "Ylätalja kapea/myötäote": "Idea: selän leveys + hauis mukana vahvasti. Kapea myötäote, vedä kahva "
        "rintaan kyynärpäät edessä alas, palauta täyteen venytykseen.",
    "Zottman-kääntö": "Idea: hauis + kyynärvarret yhdessä liikkeessä. Käännä ylös hauiskäännöllä "
        "(kämmenet ylös), käännä ranteet huipulla ja laske vasaraotteella hitaasti — lasku kuormittaa kyynärvarsia.",
}


def ensure_exercise_descriptions():
    """Täytä suoritusohjeet tunnetuille liikkeille (vain jos puuttuu)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        for name, desc in EXERCISE_DESCRIPTIONS.items():
            conn.execute(
                text("UPDATE exercises SET description = :d "
                     "WHERE name = :n AND (description IS NULL OR description = '')"),
                {"d": desc, "n": name},
            )


def ensure_seed_foods():
    """Siemennä laaja suomalainen ruokakirjasto (per 100 g) jos kirjasto tyhjä."""
    from sqlalchemy import text

    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM foods")).scalar()
        if count and count > 0:
            return
        for name, cat, kcal, prot, carb, fat, grams in FOOD_LIBRARY:
            conn.execute(
                text("INSERT INTO foods (name, category, is_favorite, kcal, protein_g, carbs_g, "
                     "fat_g, default_grams, created_at) "
                     "VALUES (:n, :cat, 0, :k, :p, :c, :f, :g, CURRENT_TIMESTAMP)"),
                {"n": name, "cat": cat, "k": kcal, "p": prot, "c": carb, "f": fat, "g": grams},
            )


# Laaja lisäys ruokakirjastoon (per 100 g): (nimi, kategoria, kcal, prot, hiilari, rasva, annos_g)
EXTRA_FOODS = [
    # --- Hedelmät & marjat ---
    ("Päärynä", "hedelmät & marjat", 57, 0.4, 15, 0.1, 160),
    ("Mandariini", "hedelmät & marjat", 53, 0.8, 13, 0.3, 90),
    ("Kiivi", "hedelmät & marjat", 61, 1.1, 15, 0.5, 75),
    ("Ananas", "hedelmät & marjat", 50, 0.5, 13, 0.1, 100),
    ("Vesimeloni", "hedelmät & marjat", 30, 0.6, 8, 0.2, 200),
    ("Hunajameloni", "hedelmät & marjat", 36, 0.5, 9, 0.1, 150),
    ("Persikka", "hedelmät & marjat", 39, 0.9, 10, 0.3, 150),
    ("Nektariini", "hedelmät & marjat", 44, 1.1, 11, 0.3, 140),
    ("Luumu", "hedelmät & marjat", 46, 0.7, 11, 0.3, 60),
    ("Kirsikka", "hedelmät & marjat", 63, 1.1, 16, 0.2, 100),
    ("Puolukka", "hedelmät & marjat", 46, 0.8, 11, 0.5, 100),
    ("Karpalo", "hedelmät & marjat", 46, 0.4, 12, 0.1, 100),
    ("Mango", "hedelmät & marjat", 60, 0.8, 15, 0.4, 150),
    ("Avokado", "hedelmät & marjat", 160, 2.0, 9, 15, 100),
    ("Granaattiomena", "hedelmät & marjat", 83, 1.7, 19, 1.2, 100),
    ("Rusinat", "hedelmät & marjat", 299, 3.1, 79, 0.5, 30),
    ("Taateli (kuivattu)", "hedelmät & marjat", 282, 2.5, 75, 0.4, 30),
    # --- Vihannekset ---
    ("Parsakaali", "vihannekset", 34, 2.8, 7, 0.4, 150),
    ("Kukkakaali", "vihannekset", 25, 1.9, 5, 0.3, 150),
    ("Pinaatti", "vihannekset", 23, 2.9, 3.6, 0.4, 80),
    ("Ruusukaali", "vihannekset", 43, 3.4, 9, 0.3, 150),
    ("Kesäkurpitsa", "vihannekset", 17, 1.2, 3.1, 0.3, 150),
    ("Munakoiso", "vihannekset", 25, 1.0, 6, 0.2, 150),
    ("Punajuuri", "vihannekset", 43, 1.6, 10, 0.2, 100),
    ("Bataatti", "vihannekset", 86, 1.6, 20, 0.1, 150),
    ("Herneet (pakaste)", "vihannekset", 81, 5.4, 14, 0.4, 100),
    ("Maissi", "vihannekset", 86, 3.3, 19, 1.4, 100),
    ("Sipuli", "vihannekset", 40, 1.1, 9, 0.1, 60),
    ("Valkosipuli", "vihannekset", 149, 6.4, 33, 0.5, 10),
    ("Salaatti (lehti)", "vihannekset", 15, 1.4, 2.9, 0.2, 50),
    ("Avomaankurkku", "vihannekset", 15, 0.7, 3.6, 0.1, 100),
    ("Retiisi", "vihannekset", 16, 0.7, 3.4, 0.1, 50),
    ("Selleri (varsi)", "vihannekset", 16, 0.7, 3, 0.2, 60),
    ("Sienet (herkkusieni)", "vihannekset", 22, 3.1, 3.3, 0.3, 100),
    ("Suolakurkku", "vihannekset", 11, 0.3, 2.3, 0.2, 50),
    ("Hapankaali", "vihannekset", 19, 0.9, 4.3, 0.1, 100),
    # --- Kana & liha ---
    ("Kalkkunan fileesuikale", "kana", 105, 22, 0.5, 1.5, 150),
    ("Broilerin koipireisi (nahalla)", "kana", 215, 17, 0, 16, 200),
    ("Kananpojan sisäfilee", "kana", 106, 23, 0.3, 1.2, 150),
    ("Broilerin jauheliha", "kana", 130, 19, 0, 6, 150),
    ("Naudan jauheliha 10 %", "liha", 176, 20, 0, 10, 150),
    ("Naudan jauheliha 17 %", "liha", 220, 18, 0, 17, 150),
    ("Sika-nautajauheliha", "liha", 240, 17, 0, 19, 150),
    ("Porsaan ulkofilee", "liha", 143, 21, 0, 6, 150),
    ("Naudan sisäpaisti", "liha", 130, 22, 0, 4.5, 150),
    ("Karitsan paisti", "liha", 176, 20, 0, 10, 150),
    ("Poronkäristys", "liha", 180, 27, 0, 8, 150),
    ("Maksalaatikko", "liha", 130, 7.5, 17, 3.5, 300),
    ("Nakit", "liha", 250, 10, 3, 22, 100),
    ("Grillimakkara", "liha", 270, 11, 4, 23, 100),
    ("Meetvursti", "liha", 400, 20, 1, 35, 30),
    ("Kinkkuleike", "liha", 100, 18, 1.5, 2.5, 40),
    ("Kalkkunaleike", "liha", 95, 18, 1.5, 1.8, 40),
    ("Pekoni", "liha", 450, 13, 1, 44, 50),
    # --- Kala ---
    ("Kirjolohi", "kala", 160, 20, 0, 9, 150),
    ("Tonnikala vedessä", "kala", 105, 24, 0, 1, 120),
    ("Tonnikala öljyssä (valutettu)", "kala", 190, 27, 0, 9, 120),
    ("Seiti", "kala", 80, 18, 0, 0.7, 150),
    ("Kuha", "kala", 84, 19, 0, 0.7, 150),
    ("Muikku", "kala", 130, 17, 0, 7, 150),
    ("Silakka", "kala", 145, 16, 0, 9, 150),
    ("Savulohi", "kala", 170, 22, 0, 9, 100),
    ("Katkarapu", "kala", 85, 20, 0, 0.7, 100),
    ("Kalapuikot", "kala", 190, 12, 17, 8, 125),
    # --- Maitotuotteet & juusto ---
    ("Skyr (maustamaton)", "maitotuotteet", 63, 11, 4, 0.2, 200),
    ("Kreikkalainen jogurtti", "maitotuotteet", 120, 4.5, 4, 10, 150),
    ("Vanukas (vanilja)", "maitotuotteet", 110, 3, 18, 3, 125),
    ("Piimä", "maitotuotteet", 38, 3.3, 4, 1, 200),
    ("Kermaviili", "maitotuotteet", 130, 2.8, 4, 12, 60),
    ("Ranskankerma", "maitotuotteet", 190, 2.5, 3, 19, 50),
    ("Kuohukerma", "maitotuotteet", 355, 2, 3, 38, 30),
    ("Ruokakerma 15 %", "maitotuotteet", 160, 2.5, 4, 15, 50),
    ("Kaurajuoma", "maitotuotteet", 45, 1, 7, 1.5, 200),
    ("Proteiinivanukas", "maitotuotteet", 80, 10, 8, 1.5, 200),
    ("Mozzarella", "juusto", 250, 18, 2, 19, 50),
    ("Feta", "juusto", 265, 14, 2, 22, 50),
    ("Halloumi", "juusto", 320, 22, 2, 25, 60),
    ("Sulatejuusto", "juusto", 230, 10, 6, 19, 25),
    ("Parmesaani", "juusto", 400, 33, 3, 29, 15),
    # --- Leipä & viljat ---
    ("Kaurahiutaleet", "leipä & viljat", 370, 13, 59, 7, 40),
    ("Näkkileipä", "leipä & viljat", 330, 10, 62, 2.5, 15),
    ("Sekaleipä", "leipä & viljat", 250, 8, 45, 3, 30),
    ("Vaalea paahtoleipä", "leipä & viljat", 265, 8, 49, 3.5, 25),
    ("Riisipiirakka", "leipä & viljat", 220, 5.5, 40, 4, 60),
    ("Tortilla (vehnä)", "leipä & viljat", 300, 8, 50, 7, 65),
    ("Couscous (keitetty)", "leipä & viljat", 112, 3.8, 23, 0.2, 150),
    ("Kvinoa (keitetty)", "leipä & viljat", 120, 4.4, 21, 1.9, 150),
    ("Ohrasuurimo (keitetty)", "leipä & viljat", 123, 2.3, 28, 0.4, 150),
    ("Müsli (hedelmä)", "leipä & viljat", 350, 8, 68, 5, 50),
    ("Granola", "leipä & viljat", 450, 10, 55, 20, 50),
    ("Korppu", "leipä & viljat", 390, 10, 70, 7, 15),
    # --- Pähkinät, siemenet, palkokasvit ---
    ("Cashewpähkinä", "pähkinät & rasvat", 553, 18, 30, 44, 30),
    ("Maapähkinä", "pähkinät & rasvat", 567, 26, 16, 49, 30),
    ("Pähkinäsekoitus", "pähkinät & rasvat", 580, 17, 15, 50, 30),
    ("Maapähkinävoi", "pähkinät & rasvat", 590, 25, 20, 50, 15),
    ("Chia-siemenet", "pähkinät & rasvat", 486, 17, 42, 31, 15),
    ("Auringonkukansiemenet", "pähkinät & rasvat", 580, 21, 20, 51, 20),
    ("Linssit (keitetty)", "vihannekset", 116, 9, 20, 0.4, 150),
    ("Kikherneet (keitetty)", "vihannekset", 164, 9, 27, 2.6, 150),
    ("Mustapavut (keitetty)", "vihannekset", 132, 8.9, 24, 0.5, 150),
    ("Tofu", "vihannekset", 76, 8, 1.9, 4.8, 150),
    ("Härkis", "vihannekset", 150, 17, 6, 6, 125),
    ("Nyhtökaura", "vihannekset", 130, 15, 10, 3.5, 125),
    # --- Herkut & välipalat ---
    ("Tumma suklaa 70 %", "herkut", 550, 8, 34, 42, 20),
    ("Proteiinipatukka", "herkut", 350, 30, 35, 10, 55),
    ("Perunalastut", "herkut", 536, 6, 50, 34, 50),
    ("Popcorn (popattu)", "herkut", 387, 12, 63, 5, 30),
    ("Vaniljajäätelö", "herkut", 200, 3.5, 24, 10, 75),
    ("Korvapuusti", "herkut", 340, 7, 52, 11, 90),
    ("Kaurakeksi", "herkut", 460, 7, 62, 20, 25),
    ("Salmiakki", "herkut", 350, 1, 85, 0.5, 30),
    ("Hedelmäkarkit", "herkut", 340, 0.2, 84, 0.2, 30),
    ("Lakritsi", "herkut", 350, 3, 80, 1, 30),
    # --- Juomat ---
    ("Appelsiinitäysmehu", "juomat", 45, 0.7, 10, 0.2, 200),
    ("Omenatäysmehu", "juomat", 46, 0.1, 11, 0.1, 200),
    ("Smoothie (hedelmä)", "juomat", 60, 1, 13, 0.3, 250),
    ("Kaakao (maitoon)", "juomat", 85, 3.5, 12, 2.5, 200),
    ("Urheilujuoma", "juomat", 26, 0, 6, 0, 500),
    ("Kombucha", "juomat", 20, 0, 5, 0, 330),
    # --- Kastikkeet & lisät ---
    ("Hunaja", "kastikkeet", 304, 0.3, 82, 0, 15),
    ("Sokeri", "kastikkeet", 400, 0, 100, 0, 10),
    ("Vaahterasiirappi", "kastikkeet", 260, 0, 67, 0, 20),
    ("Mansikkahillo", "kastikkeet", 170, 0.3, 42, 0.1, 20),
    ("Soijakastike", "kastikkeet", 60, 6, 6, 0.1, 15),
    ("Sweet chili -kastike", "kastikkeet", 230, 0.5, 55, 0.5, 20),
    ("BBQ-kastike", "kastikkeet", 170, 1, 40, 0.5, 20),
    ("Pesto", "kastikkeet", 450, 5, 6, 45, 25),
    ("Hummus", "kastikkeet", 250, 7, 12, 19, 50),
    ("Guacamole", "kastikkeet", 150, 2, 7, 13, 50),
    ("Kookosmaito (tölkki)", "kastikkeet", 180, 1.8, 3, 18, 100),
    # --- Einekset & valmisruoat ---
    ("Kebab (liha)", "einekset", 215, 18, 2, 15, 150),
    ("Hampurilainen (juusto)", "einekset", 260, 13, 26, 12, 150),
    ("Ranskalaiset perunat", "einekset", 310, 3.5, 40, 15, 150),
    ("Makaronilaatikko", "einekset", 130, 7, 13, 5.5, 400),
    ("Lihapullat", "einekset", 230, 13, 8, 16, 150),
    ("Hernekeitto", "einekset", 75, 5.5, 9, 2, 300),
    ("Lohikeitto", "einekset", 90, 6, 6, 4.5, 300),
    ("Kanawokki (valmis)", "einekset", 120, 9, 12, 4, 350),
    ("Sushi (lohi, 8 palaa)", "einekset", 150, 6, 27, 2, 250),
    ("Pinaattiletut", "einekset", 160, 5, 21, 6, 150),
    ("Kasvispihvi", "einekset", 190, 6, 18, 10, 100),
    ("Pyttipannu", "einekset", 110, 5, 12, 5, 350),
]

# Laajennus: suomalaiset herkut, kahvilatuotteet, patukat tutuilla nimillä,
# pikaruoka-annokset (kebab-ranskalaiset, Big Mac -ateria, Kotipizza...),
# pakastepizzat ja kauppojen valmisruoat. Oletusgrammat = tyypillinen annos,
# jotta kirjaus onnistuu yhdellä klikkauksella.
EXTRA_FOODS += [
    # --- Pullat & leivonnaiset ---
    ("Voisilmäpulla", "herkut", 375, 6.5, 51, 16, 90),
    ("Munkki (sokerimunkki)", "herkut", 380, 6, 48, 18, 80),
    ("Hillomunkki", "herkut", 330, 6, 50, 12, 90),
    ("Munkkirinkilä", "herkut", 400, 6, 50, 20, 60),
    ("Wieneri (vanilja)", "herkut", 400, 6, 46, 22, 90),
    ("Suklaadonitsi", "herkut", 450, 5.5, 52, 25, 70),
    ("Croissant", "herkut", 410, 8, 45, 22, 65),
    ("Suklaacroissant", "herkut", 430, 7, 48, 23, 70),
    ("Mustikkapiirakka (pala)", "herkut", 280, 4.5, 40, 11, 100),
    ("Omenapiirakka (pala)", "herkut", 270, 3.5, 40, 10, 100),
    ("Mokkapala", "herkut", 420, 5, 55, 20, 60),
    ("Kääretorttu (pala)", "herkut", 350, 5.5, 52, 13, 60),
    ("Runebergintorttu", "herkut", 380, 5, 52, 16, 65),
    ("Laskiaispulla", "herkut", 350, 6, 42, 17, 130),
    ("Joulutorttu", "herkut", 380, 4, 48, 19, 60),
    ("Brownie", "herkut", 450, 5, 50, 26, 70),
    ("Pannukakku (pala)", "herkut", 190, 6, 26, 7, 150),
    ("Letut/ohukaiset (3 kpl)", "herkut", 220, 6.5, 26, 10, 80),
    ("Vohveli hillolla ja kermalla", "herkut", 300, 5, 38, 14, 120),
    # --- Patukat & suklaat (tutut merkit) ---
    ("Snickers-patukka", "herkut", 488, 8.5, 60, 24, 50),
    ("Mars-patukka", "herkut", 450, 4, 70, 17, 51),
    ("Twix-patukka", "herkut", 495, 4.5, 64, 24, 50),
    ("KitKat-patukka", "herkut", 520, 6, 60, 27, 42),
    ("Bounty-patukka", "herkut", 475, 3.8, 58, 25, 57),
    ("Daim-patukka", "herkut", 530, 4, 63, 29, 28),
    ("Geisha-patukka", "herkut", 550, 8, 51, 35, 37),
    ("Fazer Sininen (pala/rivi)", "herkut", 530, 7.5, 55, 31, 30),
    ("Kismet-patukka", "herkut", 500, 6, 57, 27, 55),
    ("Tupla-patukka", "herkut", 490, 7, 57, 26, 48),
    ("Pätkis-patukka", "herkut", 480, 5, 60, 24, 40),
    ("Suffeli-patukka", "herkut", 520, 5, 58, 30, 21),
    ("Jim-patukka", "herkut", 400, 3, 68, 13, 27),
    ("Dumle (kourallinen)", "herkut", 460, 3.5, 67, 19, 40),
    ("Marianne (kourallinen)", "herkut", 460, 2, 75, 17, 30),
    ("Suklaakonvehti (1 kpl)", "herkut", 530, 6, 55, 31, 15),
    ("Salmiakkipussi", "herkut", 360, 2, 85, 0.5, 40),
    ("Jäätelötuutti", "herkut", 260, 4, 32, 13, 110),
    ("Jäätelöpuikko (suklaakuorrute)", "herkut", 320, 4.5, 30, 20, 65),
    # --- Kahvilajuomat & limut ---
    ("Kahvi maidolla", "juomat", 12, 0.7, 1.3, 0.4, 230),
    ("Kahvi maidolla ja sokerilla", "juomat", 25, 0.7, 4.5, 0.4, 230),
    ("Latte (kevytmaito)", "juomat", 40, 2.5, 4.5, 1.3, 250),
    ("Cappuccino", "juomat", 30, 2, 3.5, 1, 200),
    ("Coca-Cola", "juomat", 42, 0, 10.6, 0, 330),
    ("Coca-Cola Zero", "juomat", 0.3, 0, 0, 0, 330),
    ("Limonadi (Jaffa tms.)", "juomat", 42, 0, 10.5, 0, 330),
    # --- Pikaruoka (annokset yhdellä klikkauksella) ---
    ("Big Mac", "pikaruoka", 232, 11.9, 19.2, 12.3, 219),
    ("Big Mac -ateria (ranskalaiset + limu)", "pikaruoka", 148, 4.5, 17.9, 6.3, 663),
    ("Juustohampurilainen (McD)", "pikaruoka", 255, 13, 26, 12, 119),
    ("Kananugetit (6 kpl)", "pikaruoka", 270, 15, 16, 16, 96),
    ("Kebab-ranskalaiset (annos)", "pikaruoka", 210, 9, 18, 11, 500),
    ("Kebab riisillä (annos)", "pikaruoka", 160, 10, 17, 6, 450),
    ("Hodari (grilli)", "pikaruoka", 260, 9, 24, 14, 150),
    ("Lihapiirakka (grilli)", "pikaruoka", 330, 8, 33, 18, 200),
    ("Lihapiirakka kahdella nakilla", "pikaruoka", 320, 9, 30, 18, 300),
    ("Burrito (täytetty)", "pikaruoka", 220, 10, 25, 9, 300),
    ("Subway 15 cm (kana)", "pikaruoka", 150, 12, 18, 3, 230),
    ("Tortilla-kebabrulla (iso)", "pikaruoka", 215, 12, 20, 10, 400),
    # --- Pizzat ---
    ("Kotipizza Berlusconi", "pikaruoka", 257, 12, 26, 12, 420),
    ("Kotipizza Opera", "pikaruoka", 256, 13, 26, 11, 410),
    ("Kebab-pizza (grilli)", "pikaruoka", 270, 13, 27, 12, 450),
    ("Pakastepizza (Grandiosa kinkku)", "einekset", 220, 9, 27, 8, 350),
    ("Pakastepizza (Ristorante Mozzarella)", "einekset", 259, 10, 25, 13, 355),
    ("Pizzapala (huoltoasema)", "pikaruoka", 260, 11, 27, 12, 150),
    # --- Valmisruoat (kaupan einekset) ---
    ("Maksalaatikko (Saarioinen)", "einekset", 125, 6, 16, 4, 400),
    ("Lasagne (valmis)", "einekset", 120, 6, 13, 4.5, 400),
    ("Kinkkukiusaus (valmis)", "einekset", 120, 5, 12, 5.5, 400),
    ("Valmisateria kanapasta", "einekset", 110, 8, 12, 3, 350),
    ("Kalapuikot (5 kpl)", "einekset", 190, 11, 18, 8, 125),
    ("Hernekeitto (purkki)", "einekset", 70, 4.5, 8, 1.8, 435),
    ("Grillimakkara (HK Sininen tms.)", "einekset", 240, 9, 4.5, 21, 100),
    ("Riisipuuro (valmis)", "einekset", 110, 3, 17, 3, 300),
    ("Veriletut", "einekset", 170, 7, 22, 5.5, 200),
]

# Käyttäjän toivelista: kotitekoinen ragu, brändätyt pastat (kypsä paino),
# nuudelit, tonnikalaversiot, kastikkeet, peruna- ja ranskisversiot, pähkinät,
# myslit, jogurtit ja patongit. Grammat = tyypillinen annos -> yksi klikkaus.
EXTRA_FOODS += [
    # --- Ragu & pastakastikkeet (kypsä paino / valmis annos) ---
    # Reseptistä laskettu: 2 kg jauhelihaa, pancetta, runsas öljy+voi, tomaatti,
    # ~3.9 kg valmista kastiketta -> ~215 kcal/100 g. Annos ~250 g.
    ("Ragu (jauhelihakastike, kotitekoinen)", "kastikkeet", 215, 10.5, 4, 17, 250),
    ("Bolognesekastike (valmis, purkki)", "kastikkeet", 110, 6, 8, 5.5, 200),
    ("Tomaatti-basilikakastike (valmis)", "kastikkeet", 55, 1.6, 8, 1.8, 150),
    # --- Pastat kypsänä (brändätyt, helppo klikata) ---
    # Rummo on durumvehnäpasta; kypsä paino imee ~2.2x vettä -> ~158 kcal/100 g.
    ("Rummo spaghetti (kypsä)", "pasta & riisi", 158, 5.5, 31, 0.9, 250),
    ("Rummo penne (kypsä)", "pasta & riisi", 158, 5.5, 31, 0.9, 250),
    ("Rummo fusilli (kypsä)", "pasta & riisi", 158, 5.5, 31, 0.9, 250),
    ("Rummo tagliatelle (kypsä)", "pasta & riisi", 165, 6, 32, 1.2, 250),
    ("Rummo pasta (kuiva)", "pasta & riisi", 359, 12.5, 71, 1.5, 90),
    ("Täysjyväpasta (kypsä)", "pasta & riisi", 145, 6, 27, 1.3, 250),
    ("Tuorepasta (kypsä)", "pasta & riisi", 175, 7, 30, 2.5, 220),
    # --- Nuudelit ---
    ("Mama-nuudelit (1 pss, kuiva)", "pasta & riisi", 475, 10, 62, 20, 55),
    ("Mama-nuudelit (valmis keitto)", "einekset", 100, 2.2, 13, 4.2, 350),
    ("Nuudeli (keitetty)", "pasta & riisi", 138, 4.5, 25, 2.1, 200),
    ("Riisinuudeli (keitetty)", "pasta & riisi", 108, 1.8, 25, 0.2, 200),
    # --- Tonnikalaversiot ---
    ("Tonnikala tomaattikastikkeessa", "kala", 115, 16, 6, 3, 100),
    ("Tonnikala chilikastikkeessa", "kala", 130, 16, 8, 4, 100),
    ("Tonnikalatahna (levite)", "kala", 180, 14, 4, 12, 40),
    # --- Kastikkeet ---
    ("HP-kastike (ruskea kastike)", "kastikkeet", 120, 1, 28, 0.1, 15),
    ("Ketsuppi (Heinz)", "kastikkeet", 102, 1.2, 24, 0.1, 20),
    ("Ketsuppi (sokeriton)", "kastikkeet", 25, 1.3, 5, 0.1, 20),
    ("Sweet chili -kastike (Blue Dragon)", "kastikkeet", 225, 0.6, 54, 0.2, 25),
    ("Sweet chili -kastike (sokeriton)", "kastikkeet", 45, 0.5, 10, 0.2, 25),
    ("Teriyakikastike", "kastikkeet", 90, 3, 18, 0.1, 20),
    ("Soijakastike (kevyt suola)", "kastikkeet", 60, 6, 8, 0.1, 15),
    ("Sriracha-kastike", "kastikkeet", 100, 2, 19, 1, 15),
    ("Valkosipulimajoneesi (aioli)", "kastikkeet", 640, 1, 3, 69, 20),
    ("Bearnaisekastike", "kastikkeet", 380, 2, 3, 40, 40),
    # --- Peruna- ja ranskisversiot ---
    ("Ranskalaiset (rasvakeitetyt)", "pasta & riisi", 312, 3.4, 41, 15, 150),
    ("Ranskalaiset (pakaste, uuni)", "pasta & riisi", 170, 3, 28, 5, 150),
    ("Bataattiranskalaiset (uuni)", "pasta & riisi", 175, 2.5, 30, 5.5, 150),
    ("Lohkoperunat (uuni)", "pasta & riisi", 155, 2.8, 24, 5.2, 150),
    ("Lohkoperunat (pakaste, uuni)", "pasta & riisi", 145, 2.5, 23, 4.8, 150),
    ("Perunamuusi (voi + maito)", "pasta & riisi", 110, 2, 15, 4.5, 200),
    ("Perunamuusi (valmis, hiutaleista)", "pasta & riisi", 85, 2, 14, 2.5, 200),
    ("Uuniperuna", "pasta & riisi", 93, 2.5, 20, 0.1, 200),
    ("Paistetut perunat (pannulla)", "pasta & riisi", 150, 2.5, 22, 5.5, 150),
    ("Rösti / perunaröstit", "pasta & riisi", 210, 2.5, 24, 11, 120),
    # --- Pähkinät (eri lajit) ---
    ("Saksanpähkinä", "pähkinät & rasvat", 654, 15, 14, 65, 30),
    ("Hasselpähkinä", "pähkinät & rasvat", 628, 15, 17, 61, 30),
    ("Pekaanipähkinä", "pähkinät & rasvat", 691, 9, 14, 72, 30),
    ("Pistaasipähkinä", "pähkinät & rasvat", 560, 20, 28, 45, 30),
    ("Parapähkinä", "pähkinät & rasvat", 659, 14, 12, 67, 30),
    ("Macadamiapähkinä", "pähkinät & rasvat", 718, 8, 14, 76, 30),
    ("Paahdetut suolapähkinät", "pähkinät & rasvat", 600, 20, 18, 50, 30),
    ("Kookoshiutaleet", "pähkinät & rasvat", 660, 7, 24, 64, 20),
    # --- Myslit & murot ---
    ("Mysli (tavallinen)", "leipä & viljat", 360, 9, 60, 8, 60),
    ("Mysli (paahdettu, crunchy)", "leipä & viljat", 440, 8, 62, 16, 60),
    ("Hedelmämysli", "leipä & viljat", 350, 8, 63, 7, 60),
    ("Maissihiutaleet (Corn Flakes)", "leipä & viljat", 378, 7, 84, 0.9, 40),
    ("Murot (suklaa)", "leipä & viljat", 385, 6, 82, 4, 40),
    # --- Jogurtit (maustetut) ---
    ("Mansikkajogurtti", "maitotuotteet", 90, 3, 15, 2, 150),
    ("Vaniljajogurtti", "maitotuotteet", 92, 3, 15, 2.2, 150),
    ("Mustikkajogurtti", "maitotuotteet", 88, 3, 14, 2, 150),
    ("Vaniljakvarki (maustettu rahka)", "maitotuotteet", 90, 11, 8, 1, 150),
    ("Mansikkarahka", "maitotuotteet", 88, 11, 8, 0.5, 150),
    ("Juotava jogurtti (marja)", "maitotuotteet", 75, 3, 13, 1.2, 200),
    # --- Patongit & leivät ---
    ("Patonki (iso, kaupan)", "leipä & viljat", 270, 9, 52, 2.5, 125),
    ("Patonki (puolikas)", "leipä & viljat", 270, 9, 52, 2.5, 125),
    ("Valkosipulipatonki (pakaste)", "leipä & viljat", 330, 7, 45, 13, 80),
    ("Ciabatta", "leipä & viljat", 271, 9, 52, 3, 90),
    ("Vaalea sämpylä", "leipä & viljat", 265, 9, 50, 3, 70),
]

# Käyttäjän toivelista 2: kotitekoinen pizza, pikaruokaketjujen KOKONAISET
# annokset (yksi klikkaus = koko hampurilainen; grammat = annoksen paino),
# jaetut limut ja uunituotteet.
EXTRA_FOODS += [
    # --- Kotitekoinen pizza (laskettu aineksista) ---
    # 2 peltiä: pizzapohjat+tomaattisoosi 800 g, juustoraaste 400 g, jauheliha
    # 10% (400 g raaka -> ~320 g kypsä), pepperoni 120 g -> 1640 g, 4656 kcal.
    ("Jauheliha-pepperonipizza (kotitekoinen)", "pikaruoka", 284, 16, 24, 14, 410),
    ("Kotitekoinen pizza (juusto-kinkku)", "pikaruoka", 250, 12, 30, 9, 400),
    # --- Burger King (koko annos) ---
    ("Whopper (BK)", "pikaruoka", 233, 10, 18.5, 12.6, 270),
    ("Tuplawhopper (BK)", "pikaruoka", 240, 12.8, 13.3, 14.9, 375),
    ("Crispy Chicken (BK)", "pikaruoka", 263, 11, 24, 13, 190),
    ("Chicken King (BK)", "pikaruoka", 270, 12, 22.6, 14.3, 230),
    ("Steakhouse (BK)", "pikaruoka", 241, 10.7, 16.6, 14.1, 290),
    ("Bacon King (BK)", "pikaruoka", 288, 15, 12, 20, 400),
    ("BK ranskalaiset (keskikok.)", "pikaruoka", 300, 3.6, 38, 14.5, 110),
    ("BK ranskalaiset (iso)", "pikaruoka", 300, 3.6, 38, 14.5, 150),
    ("Sipulirenkaat (BK)", "pikaruoka", 410, 5, 46, 22, 90),
    # --- McDonald's (koko annos) ---
    ("Quarter Pounder juusto (McD)", "pikaruoka", 260, 15, 21, 13, 200),
    ("McChicken (McD)", "pikaruoka", 250, 9.4, 25, 12.5, 160),
    ("McFeast (McD)", "pikaruoka", 235, 12, 20, 12, 215),
    ("Chicken McNuggets (9 kpl)", "pikaruoka", 277, 16, 16, 16.7, 150),
    ("Filet-O-Fish (McD)", "pikaruoka", 239, 10.7, 26, 10, 140),
    ("McDonald's ranskalaiset (keskikok.)", "pikaruoka", 296, 3.5, 37, 14, 115),
    ("McDonald's ranskalaiset (iso)", "pikaruoka", 296, 3.5, 37, 14, 150),
    ("McFlurry (Daim)", "pikaruoka", 178, 3.3, 28, 6, 180),
    # --- Hesburger (koko annos) ---
    ("Hesburger (perus)", "pikaruoka", 207, 10, 19, 9.3, 140),
    ("Iso Hesburger", "pikaruoka", 218, 11, 15, 12.3, 220),
    ("Kolmoishesburger", "pikaruoka", 245, 14, 12, 16, 300),
    ("Hesburger kana", "pikaruoka", 210, 10.5, 18.4, 10, 190),
    ("Ruisburger (Hesburger)", "pikaruoka", 213, 10, 18.8, 10, 160),
    ("Hesburger ranskalaiset", "pikaruoka", 264, 3.6, 34.5, 11.8, 110),
    ("Hesburger pirtelö (0.4 l)", "pikaruoka", 110, 2.7, 18.3, 2.7, 300),
    # --- Jaetut limut & juomat (pikaruoka-annokset) ---
    ("Coca-Cola (iso muki 0.5 l)", "juomat", 42, 0, 10.6, 0, 500),
    ("Sprite", "juomat", 37, 0, 9, 0, 400),
    ("Fanta", "juomat", 46, 0, 11, 0, 400),
    ("Milkshake (vanilja/suklaa)", "juomat", 110, 3, 18, 3, 300),
    # --- Uunituotteet (helppo lisätä) ---
    ("Lihapasteija (uuni)", "einekset", 285, 9, 30, 14, 100),
    ("Kinkkupasteija (uuni)", "einekset", 270, 9, 30, 12, 100),
    ("Lihapiirakka (pakaste, uuni)", "einekset", 290, 9, 32, 14, 130),
    ("Uunivalkosipulipatonki (iso)", "leipä & viljat", 330, 7, 45, 13, 100),
    ("Kinkku-juustocroissant (uuni)", "leipä & viljat", 340, 12, 33, 17, 110),
    ("Voisarvi (croissant, uuni)", "leipä & viljat", 406, 8, 45, 21, 60),
    ("Karjalanpiirakka", "leipä & viljat", 235, 6, 40, 5, 80),
    ("Karjalanpiirakka + munavoi", "leipä & viljat", 290, 7, 30, 15, 100),
    ("Täytetty sämpylä (kinkku-juusto)", "leipä & viljat", 250, 12, 28, 9, 120),
    ("Pizzapala (pakaste, uuni)", "pikaruoka", 260, 11, 28, 11, 150),
]


def ensure_extra_foods():
    """Lisää puuttuvat ruoat kirjastoon (idempotentti — myös vanhat kannat
    saavat uudet ruoat ilman uudelleenluontia)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        existing = {r[0] for r in conn.execute(text("SELECT name FROM foods")).fetchall()}
        for name, cat, kcal, prot, carb, fatg, grams in EXTRA_FOODS:
            if name in existing:
                continue
            conn.execute(
                text("INSERT INTO foods (name, category, is_favorite, kcal, protein_g, carbs_g, "
                     "fat_g, fiber_g, sugar_g, sodium_mg, default_grams, created_at) "
                     "VALUES (:n, :cat, 0, :k, :p, :c, :f, 0, 0, 0, :g, CURRENT_TIMESTAMP)"),
                {"n": name, "cat": cat, "k": kcal, "p": prot, "c": carb, "f": fatg, "g": grams},
            )


# ---------- Alkoholijuomat (puhtaan alkoholin grammoineen) ----------
# (nimi, kcal/100, hiilarit/100, rasva/100, ABV-%, annos g/ml). Puhdas
# alkoholi lasketaan ABV:sta: g/100ml = ABV% * 0.789 (etanolin tiheys).
# Suomalainen vakioannos = 12 g puhdasta alkoholia. Kattaa myös jo kannassa
# olevat oluet/viinit, jotta niidenkin alkoholigrammat täydentyvät.
ALCOHOL_FOODS = [
    # --- Oluet ---
    ("Lager vaalea 0.33 l", 42, 3.3, 0, 4.6, 330),
    ("Lager vaalea 0.5 l", 42, 3.3, 0, 4.6, 500),
    ("Tumma lager 0.33 l", 47, 4.5, 0, 5.0, 330),
    ("Pale Ale 0.33 l", 48, 3.8, 0, 5.2, 330),
    ("IPA 0.33 l", 55, 4.5, 0, 5.6, 330),
    ("IPA 0.5 l", 58, 4.6, 0, 6.0, 500),
    ("Tupla-IPA (DIPA) 0.33 l", 80, 6, 0, 8.0, 330),
    ("Vehnäolut 0.5 l", 45, 4, 0, 5.0, 500),
    ("Pils 0.5 l", 42, 3.3, 0, 4.7, 500),
    ("Vahva olut (A) 0.5 l", 63, 4.5, 0, 7.0, 500),
    ("Stout / portteri 0.33 l", 60, 5.5, 0, 5.5, 330),
    ("Alkoholiton olut 0.33 l", 25, 5, 0, 0.4, 330),
    ("Olut (lager) 0.33 l", 43, 3.5, 0, 4.7, 330),   # täydentää vanhan
    ("Olut (lager) 0.5 l", 43, 3.5, 0, 4.7, 500),
    ("IPA-olut 0.33 l", 55, 5, 0, 5.6, 330),
    # --- Siiderit & lonkerot ---
    ("Siideri (kuiva) 0.33 l", 45, 3, 0, 4.7, 330),
    ("Siideri (makea) 0.33 l", 55, 8, 0, 4.7, 330),
    ("Lonkero 0.33 l", 47, 5, 0, 5.5, 330),
    ("Lonkero (kuiva) 0.33 l", 38, 1.5, 0, 5.5, 330),
    ("Hard seltzer 0.33 l", 30, 1, 0, 5.0, 330),
    # --- Viinit ---
    ("Punaviini (lasi 0.16 l)", 85, 2.6, 0, 13.0, 160),
    ("Valkoviini (lasi 0.16 l)", 82, 2.6, 0, 12.0, 160),
    ("Roseeviini (lasi 0.16 l)", 82, 3, 0, 12.0, 160),
    ("Kuohuviini / samppanja (lasi 0.12 l)", 80, 1.5, 0, 12.0, 120),
    ("Sangria (lasi 0.2 l)", 90, 11, 0, 10.0, 200),
    ("Glögi (alkoholillinen, lasi 0.15 l)", 130, 22, 0, 10.0, 150),
    ("Portviini / jälkiruokaviini (lasi 0.08 l)", 160, 12, 0, 19.0, 80),
    ("Punaviini (lasi 0.2 l)", 85, 2.6, 0, 13.0, 200),   # täydentää vanhan
    ("Valkoviini (lasi 0.2 l)", 82, 2.6, 0, 12.0, 200),
    ("Siideri (kuiva) 0.33 l ", 45, 3, 0, 4.7, 330),
    # --- Väkevät (4 cl = vakiopaukku) ---
    ("Viski (4 cl)", 250, 0, 0, 40.0, 40),
    ("Konjakki (4 cl)", 250, 0, 0, 40.0, 40),
    ("Vodka (4 cl)", 220, 0, 0, 40.0, 40),
    ("Gini (4 cl)", 245, 0, 0, 40.0, 40),
    ("Rommi (4 cl)", 245, 0, 0, 40.0, 40),
    ("Tequila (4 cl)", 235, 0, 0, 38.0, 40),
    ("Jaloviina (4 cl)", 225, 1, 0, 38.0, 40),
    ("Salmiakkikossu / salmari (4 cl)", 235, 20, 0, 32.0, 40),
    ("Fisu-shotti (4 cl)", 195, 12, 0, 27.0, 40),
    ("Jägermeister (4 cl)", 235, 24, 0, 35.0, 40),
    ("Minttuviina (4 cl)", 300, 30, 0, 40.0, 40),
    ("Likööri (4 cl)", 245, 25, 0, 20.0, 40),
    ("Baileys (4 cl)", 325, 20, 6, 17.0, 40),
    # --- Drinkit & cocktailit ---
    ("Gin tonic (0.33 l)", 90, 8, 0, 8.0, 330),
    ("Mojito (drinkki)", 180, 20, 0, 12.0, 220),
    ("Long Island Iced Tea", 220, 24, 0, 15.0, 230),
    ("Cosmopolitan", 180, 15, 0, 20.0, 120),
    ("Margarita", 170, 14, 0, 18.0, 150),
    ("Viski-kola (drinkki)", 100, 10, 0, 7.0, 330),
    ("Aperol Spritz", 120, 14, 0, 9.0, 200),
]


def ensure_alcohol_foods():
    """Siemennä alkoholijuomat ja laske puhtaan alkoholin grammat ABV:sta.
    Täydentää myös jo kannassa olevien alkoholien alcohol_g:n."""
    from sqlalchemy import text
    ETHANOL_DENSITY = 0.789
    with engine.begin() as conn:
        existing = {r[0] for r in conn.execute(text("SELECT name FROM foods")).fetchall()}
        for name, kcal, carb, fatg, abv, grams in ALCOHOL_FOODS:
            alcohol_g = round(abv * ETHANOL_DENSITY, 2)  # per 100 ml
            if name in existing:
                # Täydennä vain alkoholigrammat (älä ylikirjoita käyttäjän muokkauksia)
                conn.execute(text("UPDATE foods SET alcohol_g = :a WHERE name = :n AND "
                                  "(alcohol_g IS NULL OR alcohol_g = 0)"),
                             {"a": alcohol_g, "n": name})
            else:
                conn.execute(
                    text("INSERT INTO foods (name, category, is_favorite, kcal, protein_g, "
                         "carbs_g, fat_g, fiber_g, sugar_g, sodium_mg, alcohol_g, default_grams, "
                         "created_at) VALUES (:n, 'alkoholi', 0, :k, 0, :c, :f, 0, :c, 0, :a, :g, "
                         "CURRENT_TIMESTAMP)"),
                    {"n": name, "k": kcal, "c": carb, "f": fatg, "a": alcohol_g, "g": grams})
