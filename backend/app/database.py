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
