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
    unit: Mapped[str] = mapped_column(String(10), default="kg")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Program(Base):
    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    # "cycle" (treeni-lepo-sykli) tai "weekly" (viikon päivät)
    schedule_type: Mapped[str] = mapped_column(String(20), default="cycle")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Mihin ohjelma tähtää, esim. "voima", "hypertrofia", "voimanostototal"
    goal: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
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
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    day: Mapped["ProgramDay"] = relationship(back_populates="exercises")
    exercise: Mapped["Exercise"] = relationship()


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    # Vapaaehtoinen kytkös ohjelman päivään
    program_day_id: Mapped[int | None] = mapped_column(
        ForeignKey("program_days.id"), nullable=True
    )
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    bodyweight: Mapped[float | None] = mapped_column(Float, nullable=True)
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
