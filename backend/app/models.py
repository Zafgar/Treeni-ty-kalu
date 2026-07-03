"""Tietokantamallit.

Ydin (toteutettu nyt):
  - Exercise:           mikä tahansa liike
  - Program:            treeniohjelma, joko sykli- tai viikkopohjainen
  - ProgramDay:         ohjelman päivä (treeni / lepo)
  - ProgramExercise:    liikkeen ohjelmointi yhdelle päivälle (sarjat, toistot, paino, palautus)
  - WorkoutSession:     yksi toteutunut treenikerta
  - WorkoutExercise:    liike treenikerralla
  - SetLog:             yksittäinen sarja (tukee vajaita sarjoja kuten 4,4,4,3)

Rakenne on suunniteltu laajennettavaksi: myöhemmin lisätään mm. kehon mitat,
uni/HRV/kalorit ja kehitysennusteet ilman että ydinmalleja tarvitsee rikkoa.
"""
from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Profile(Base):
    """Henkilö jota seurataan (oma profiili, valmennettava tai läheinen).

    Ohjelmat, treenit ja kehodata skoopataan profiiliin, jotta voi vaihtaa
    ketä seuraa. Liikkeet ovat yhteisiä (kyykky on kyykky kaikille), mutta
    ennätykset ja 1RM lasketaan kunkin profiilin omista treeneistä.
    """

    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    sex: Mapped[str | None] = mapped_column(String(10), nullable=True)  # "mies"/"nainen"/muu
    birthdate: Mapped[date | None] = mapped_column(Date, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Korostusväri UI:ssa (esim. "#4f8cff")
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Onko kreatiini käytössä -> osa painosta on lihasvettä, ei rasvaa
    creatine: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Aloituskysely: treenitausta ja tavoite ohjaavat suosituksia ja ennusteita.
    # experience: "aloittelija" / "jonkin_verran" / "kokenut" / "palaava"
    experience: Mapped[str | None] = mapped_column(String(20), nullable=True)
    training_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    # goal: "voima" / "lihasmassa" / "kunto" / "painonpudotus"
    goal: Mapped[str | None] = mapped_column(String(20), nullable=True)
    days_per_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Exercise(Base):
    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    # Vapaa kategoria, esim. "jalat", "selkä", "olympia"
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Päälihasryhmä, vapaateksti
    muscle_group: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Onko pääliike (kyykky, mave, penkki, olympianostot) -> mukaan totaleihin
    is_main_lift: Mapped[bool] = mapped_column(Boolean, default=False)
    # Mihin lajitotaliin liike kuuluu, esim. "voimanosto" tai "olympia"
    sport: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Väline: tanko, käsipainot, talja, kahvakuula, keho, kone, muu
    equipment: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Onko paino per käsi (käsipainoliikkeet): tällöin kirjattu paino on
    # yhden käsipainon paino, ei yhteispaino. Vaikuttaa tulkintaan ja vertailuun.
    per_hand: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Yleisesti sopivat oletussarjat/-toistot (esim. moniniveliset 5x5,
    # eristävät 3x12) joilla liike alustetaan ohjelmaan/treeniin.
    default_sets: Mapped[int] = mapped_column(Integer, default=3)
    default_reps: Mapped[int] = mapped_column(Integer, default=10)
    unit: Mapped[str] = mapped_column(String(10), default="kg")
    # Suoritusohje + liikkeen idea (näytetään jos haluaa katsoa)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    # "cycle" (treeni-lepo-sykli) tai "weekly" (viikon päivät)
    schedule_type: Mapped[str] = mapped_column(String(20), default="cycle")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Mihin ohjelma tähtää, esim. "voima", "hypertrofia", "voimanostototal"
    goal: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Automaattinen progressio: nostaa tavoitepainoa kun edellinen kerta meni
    # täysillä (tuplaprogressio) treeniä ohjelmasta luotaessa.
    auto_progress: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Aktivoinnin aloitus ja lopetus (paljonko ohjelma kesti)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    days: Mapped[list["ProgramDay"]] = relationship(
        back_populates="program",
        cascade="all, delete-orphan",
        order_by="ProgramDay.order_index",
    )


class ProgramDay(Base):
    __tablename__ = "program_days"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id", ondelete="CASCADE"))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # "train" tai "rest"
    day_type: Mapped[str] = mapped_column(String(10), default="train")
    # Vapaa nimi, esim. "Päivä A", "Maanantai", "Jalat"
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)

    program: Mapped["Program"] = relationship(back_populates="days")
    exercises: Mapped[list["ProgramExercise"]] = relationship(
        back_populates="day",
        cascade="all, delete-orphan",
        order_by="ProgramExercise.order_index",
    )


class ProgramExercise(Base):
    """Liikkeen ohjelmointi yhdelle ohjelman päivälle (tavoitearvot)."""

    __tablename__ = "program_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_day_id: Mapped[int] = mapped_column(
        ForeignKey("program_days.id", ondelete="CASCADE")
    )
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    target_sets: Mapped[int] = mapped_column(Integer, default=3)
    target_reps: Mapped[int] = mapped_column(Integer, default=5)
    target_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    rest_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Tavoiteltu varasto (reps in reserve) -> käytetään painonlaskennassa
    target_rir: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Vapaa toistomalli per sarja, esim. "12,10,8" tai "5,5,5,5,5" (pyramidit).
    # Jos annettu, ohittaa target_sets/target_reps treeniä generoitaessa.
    rep_scheme: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Prosenttimalli 1RM:stä per sarja, esim. "60,70,80,80". Käytetään
    # voimajaksoissa: lähtöpaino lasketaan tämänhetkisestä arvioidusta 1RM:stä.
    percent_scheme: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    day: Mapped["ProgramDay"] = relationship(back_populates="exercises")
    exercise: Mapped["Exercise"] = relationship()


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int | None] = mapped_column(ForeignKey("profiles.id"), nullable=True, index=True)
    session_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    # Vapaaehtoinen kytkös ohjelman päivään
    program_day_id: Mapped[int | None] = mapped_column(
        ForeignKey("program_days.id"), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bodyweight: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Treenin kesto minuuteissa ja poltetut kalorit (esim. älykellosta)
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kcal_burned: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Fiilis: "positive" / "neutral" / "negative" + vapaa huomio. Auttaa
    # huomaamaan jos treenissä oli ongelma joka voi vaikuttaa jatkoon.
    feeling: Mapped[str | None] = mapped_column(String(12), nullable=True)
    feeling_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "planned" (suunniteltu), "completed" (suoritettu) tai "skipped" (skipattu)
    status: Mapped[str] = mapped_column(String(12), default="completed")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    exercises: Mapped[list["WorkoutExercise"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="WorkoutExercise.order_index",
    )


class WorkoutExercise(Base):
    __tablename__ = "workout_exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("workout_sessions.id", ondelete="CASCADE")
    )
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    # Liike kuitattu valmiiksi (kaikki sarjat tehty)
    done: Mapped[bool] = mapped_column(Boolean, default=False)
    # Pikakirjaus: montako toistoa jäi yhteensä vajaaksi (esim. "4 vajaa")
    # ilman että tarvitsee kirjata sarjoja erikseen (5,5,4,2). Vähennetään
    # volyymistä, jotta samalla painolla tehty sarjojen suoritus näkyy graafilla.
    missed_reps: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped["WorkoutSession"] = relationship(back_populates="exercises")
    exercise: Mapped["Exercise"] = relationship()
    sets: Mapped[list["SetLog"]] = relationship(
        back_populates="workout_exercise",
        cascade="all, delete-orphan",
        order_by="SetLog.set_index",
    )


class SetLog(Base):
    """Yksittäinen sarja. Useat rivit per liike -> tukee esim. 4,4,4,3."""

    __tablename__ = "set_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    workout_exercise_id: Mapped[int] = mapped_column(
        ForeignKey("workout_exercises.id", ondelete="CASCADE")
    )
    set_index: Mapped[int] = mapped_column(Integer, default=0)
    reps: Mapped[int] = mapped_column(Integer, default=0)
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    # Varasto: montako toistoa olisi vielä jäänyt (valinnainen)
    rir: Mapped[float | None] = mapped_column(Float, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    workout_exercise: Mapped["WorkoutExercise"] = relationship(back_populates="sets")


class BodyEntry(Base):
    """Päiväkohtainen kehon- ja hyvinvointidata (kaikki kentät vapaaehtoisia).

    Sisältää painon ja rasva-%:n (koostumusarviota varten) sekä hyvinvoinnin
    muuttujat (uni, HRV, leposyke, kalorit) myöhempää korrelaatioanalyysiä
    varten. Data on aina parempaa jos sitä kerää, mutta mikään ei ole pakollista.
    """

    __tablename__ = "body_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    bodyweight: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sleep_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Unipisteet 0-100 (esim. sormus/kello), vapaaehtoinen
    sleep_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hrv: Mapped[float | None] = mapped_column(Float, nullable=True)
    resting_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Askeleet (arkiaktiivisuus -> kulutus) ja juotu vesi (l)
    steps: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_l: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class CardioSession(Base):
    """Aerobinen / kunto-tapahtuma: juoksumatto, crosstrainer, pyöräily, kävely.

    Seuraa aerobisen kunnon kehitystä (matka, aika, keskinopeus, keskisyke) ja
    tuo poltetut kalorit mukaan päivän kokonaiskulutukseen. Kaikki kentät paitsi
    laji ja kesto ovat vapaaehtoisia.
    """

    __tablename__ = "cardio_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    session_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    activity: Mapped[str] = mapped_column(String(40))  # juoksumatto/crosstrainer/pyöräily/kävely/muu
    duration_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Measurement(Base):
    """Kehon ympärysmitta (cm) tietyltä kohdalta tiettynä päivänä.

    Joustava: site on vapaateksti (esim. hauis, pohje, rintakehä, hartia,
    reisi, vyötärö, kyynärvarsi), joten mitä tahansa kohtaa voi seurata.
    """

    __tablename__ = "measurements"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    site: Mapped[str] = mapped_column(String(60), index=True)
    value_cm: Mapped[float] = mapped_column(Float)


class ProgressPhoto(Base):
    """Edistymiskuva: päivätty valokuva kehon kehityksen seurantaan.
    Kuvatiedosto tallennetaan levylle (data/photos), rivi viittaa siihen."""

    __tablename__ = "progress_photos"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    filename: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Food(Base):
    """Ruoka-aine (yhteinen kirjasto). Makrot ja energia 100 grammaa kohden.

    Esim. maitorahka, banaani. Käyttäjä voi lisätä omia helposti.
    """

    __tablename__ = "foods"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    # Kategoria: esim. "hedelmät", "liha", "pasta & riisi", "juomat", "herkut"
    category: Mapped[str | None] = mapped_column(String(60), index=True, nullable=True)
    # Suosikki nopeaa valintaa varten
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    # Arvot per 100 g
    kcal: Mapped[float] = mapped_column(Float, default=0.0)
    protein_g: Mapped[float] = mapped_column(Float, default=0.0)
    carbs_g: Mapped[float] = mapped_column(Float, default=0.0)
    fat_g: Mapped[float] = mapped_column(Float, default=0.0)
    # Mikroravinteet (vapaaehtoisia), per 100 g
    fiber_g: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    sugar_g: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    sodium_mg: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # Tyypillinen annoskoko grammoina (esim. banaani ~120 g) nopeaa kirjausta varten
    default_grams: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FoodLog(Base):
    """Yhden ruoka-aineen kirjaus tietylle päivälle ja profiilille."""

    __tablename__ = "food_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    grams: Mapped[float] = mapped_column(Float, default=100.0)

    food: Mapped["Food"] = relationship()


class Meal(Base):
    """Oma ravintokokonaisuus (resepti), esim. smoothie: maito + marjat + whey.

    Voi pikakirjata yhdellä napilla päivän kirjauksiin tai muokata lennossa.
    """

    __tablename__ = "meals"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    items: Mapped[list["MealItem"]] = relationship(
        back_populates="meal", cascade="all, delete-orphan"
    )


class MealItem(Base):
    __tablename__ = "meal_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    meal_id: Mapped[int] = mapped_column(ForeignKey("meals.id", ondelete="CASCADE"))
    food_id: Mapped[int] = mapped_column(ForeignKey("foods.id"))
    grams: Mapped[float] = mapped_column(Float, default=100.0)

    meal: Mapped["Meal"] = relationship(back_populates="items")
    food: Mapped["Food"] = relationship()


class ForecastLog(Base):
    """Tallennettu ennuste myöhempää osuvuusvertailua varten.

    Kun ennuste lasketaan, tallennetaan mitä se lupasi tietyille horisonteille.
    Myöhemmin verrataan toteumaan -> nähdään osuvuus ja kalibroidaan tulevia.
    """

    __tablename__ = "forecast_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)  # "lift" | "measurement"
    ref: Mapped[str] = mapped_column(String(60), index=True)   # exercise_id tai mittakohta
    made_on: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    horizon_weeks: Mapped[int] = mapped_column(Integer)
    base_value: Mapped[float] = mapped_column(Float)
    predicted: Mapped[float] = mapped_column(Float)
    predicted_low: Mapped[float] = mapped_column(Float)
    predicted_high: Mapped[float] = mapped_column(Float)
    target_date: Mapped[date] = mapped_column(Date, index=True)


class VolumeAck(Base):
    """Käyttäjän kuittaus että viikon volyymi on OK eikä muutoksia tarvita."""

    __tablename__ = "volume_acks"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    week_key: Mapped[str] = mapped_column(String(12), index=True)  # esim. "2026-26"
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DietPhase(Base):
    """Aktiivinen dieettivaihe profiilille (cut / maintain / bulk).

    Tavoitetahti (kg/viikko) ja malli ohjaavat kcal- ja makrotavoitteita.
    Kehitystä seurataan viikkokeskiarvolla, jolloin korjaukset osuvat oikeaan
    suuntaan (ei päivän heilahduksiin).
    """

    __tablename__ = "diet_phases"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    goal: Mapped[str] = mapped_column(String(12), default="maintain")  # cut | maintain | bulk
    model: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # Tavoitemuutos kg/viikko (cut negatiivinen, bulk positiivinen)
    target_rate: Mapped[float] = mapped_column(Float, default=0.0)
    start_date: Mapped[date] = mapped_column(Date, default=date.today)
    start_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BiaMeasurement(Base):
    """Kehonkoostumusmittaus laitteella (InBody tms. bioimpedanssi).

    Laitteen antama rasva-% on luotettavin saatavilla oleva arvio ja toimii
    ANKKURINA: sen jälkeen päivittäiset painokirjaukset saavat automaattisen
    rasva-%-arvion (paino- ja vyötärömuutos suhteessa ankkuriin), ja laitteen
    lukema ohittaa käyttäjän omat arviot.
    """

    __tablename__ = "bia_measurements"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    entry_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    body_fat_pct: Mapped[float] = mapped_column(Float)
    # Lihasmassa (SMM), rasvamassa, sisäelinrasvataso ja laitteen pisteet
    muscle_mass_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_mass_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    visceral_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmr_kcal: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Raajakohtainen lihasjakauma (missä lihasta on)
    muscle_arms_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    muscle_legs_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    muscle_trunk_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    device: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
