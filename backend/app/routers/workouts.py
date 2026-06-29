"""Treenikertojen kirjaus ja muokkaus.

Tukee vajaita sarjoja (esim. 4,4,4,3): jokainen sarja on oma rivi omilla
toistoilla, painolla, varastolla ja huomioilla. Treeniä voi luoda ohjelman
päivästä pohjaksi tai täysin vapaasti.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import engine, models, schemas
from ..database import get_db
from .stats import _exercise_session_points, _records_for_exercise

router = APIRouter(prefix="/api/workouts", tags=["workouts"])


@router.get("", response_model=list[schemas.WorkoutSessionOut])
def list_workouts(db: Session = Depends(get_db)):
    return (
        db.query(models.WorkoutSession)
        .order_by(models.WorkoutSession.session_date.desc(), models.WorkoutSession.id.desc())
        .all()
    )


@router.post("", response_model=schemas.WorkoutSessionOut, status_code=201)
def create_workout(payload: schemas.WorkoutSessionCreate, db: Session = Depends(get_db)):
    session = models.WorkoutSession(
        session_date=payload.session_date or date.today(),
        program_day_id=payload.program_day_id,
        name=payload.name,
        bodyweight=payload.bodyweight,
        notes=payload.notes,
    )
    for we_in in payload.exercises:
        we = models.WorkoutExercise(
            exercise_id=we_in.exercise_id,
            order_index=we_in.order_index,
            notes=we_in.notes,
        )
        for s_in in we_in.sets:
            we.sets.append(models.SetLog(**s_in.model_dump()))
        session.exercises.append(we)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.post(
    "/from-program-day/{day_id}",
    response_model=schemas.WorkoutSessionOut,
    status_code=201,
)
def create_from_program_day(day_id: int, db: Session = Depends(get_db)):
    """Luo treenipohja ohjelman päivän tavoitearvoista (esitäytetyt sarjat)."""
    day = db.get(models.ProgramDay, day_id)
    if not day:
        raise HTTPException(status_code=404, detail="Päivää ei löytynyt.")
    session = models.WorkoutSession(
        session_date=date.today(),
        program_day_id=day_id,
        name=day.label,
    )
    for idx, pe in enumerate(day.exercises):
        we = models.WorkoutExercise(exercise_id=pe.exercise_id, order_index=idx, notes=pe.notes)

        # Toistomalli: rep_scheme ("12,10,8" / "5x5") tai target_sets x target_reps
        reps_per_set = engine.parse_scheme(pe.rep_scheme)
        if not reps_per_set:
            reps_per_set = [float(pe.target_reps)] * pe.target_sets

        # Prosenttimalli: lähtöpaino tämänhetkisestä arvioidusta 1RM:stä
        percents = engine.parse_scheme(pe.percent_scheme)
        current_1rm = None
        if percents:
            points = _exercise_session_points(db, pe.exercise_id)
            rec = _records_for_exercise(points, 56)
            current_1rm = rec["current_1rm"] if rec else None

        for s in range(len(reps_per_set)):
            if percents and current_1rm:
                pct = percents[s] if s < len(percents) else percents[-1]
                weight = engine.round_to_increment(current_1rm * pct / 100.0)
            else:
                weight = pe.target_weight or 0.0
            we.sets.append(
                models.SetLog(
                    set_index=s,
                    reps=int(reps_per_set[s]),
                    weight=weight,
                    rir=pe.target_rir,
                    completed=False,
                )
            )
        session.exercises.append(we)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/{workout_id}", response_model=schemas.WorkoutSessionOut)
def get_workout(workout_id: int, db: Session = Depends(get_db)):
    session = db.get(models.WorkoutSession, workout_id)
    if not session:
        raise HTTPException(status_code=404, detail="Treeniä ei löytynyt.")
    return session


@router.patch("/{workout_id}", response_model=schemas.WorkoutSessionOut)
def update_workout(
    workout_id: int, payload: schemas.WorkoutSessionUpdate, db: Session = Depends(get_db)
):
    session = db.get(models.WorkoutSession, workout_id)
    if not session:
        raise HTTPException(status_code=404, detail="Treeniä ei löytynyt.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(session, key, value)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/{workout_id}", status_code=204)
def delete_workout(workout_id: int, db: Session = Depends(get_db)):
    session = db.get(models.WorkoutSession, workout_id)
    if not session:
        raise HTTPException(status_code=404, detail="Treeniä ei löytynyt.")
    db.delete(session)
    db.commit()


# ---------- Liikkeet treenikerralla ----------
@router.post(
    "/{workout_id}/exercises",
    response_model=schemas.WorkoutExerciseOut,
    status_code=201,
)
def add_exercise(
    workout_id: int, payload: schemas.WorkoutExerciseCreate, db: Session = Depends(get_db)
):
    session = db.get(models.WorkoutSession, workout_id)
    if not session:
        raise HTTPException(status_code=404, detail="Treeniä ei löytynyt.")
    we = models.WorkoutExercise(
        session_id=workout_id,
        exercise_id=payload.exercise_id,
        order_index=payload.order_index,
        notes=payload.notes,
    )
    for s_in in payload.sets:
        we.sets.append(models.SetLog(**s_in.model_dump()))
    db.add(we)
    db.commit()
    db.refresh(we)
    return we


@router.delete("/exercises/{workout_exercise_id}", status_code=204)
def delete_workout_exercise(workout_exercise_id: int, db: Session = Depends(get_db)):
    we = db.get(models.WorkoutExercise, workout_exercise_id)
    if not we:
        raise HTTPException(status_code=404, detail="Liikettä ei löytynyt.")
    db.delete(we)
    db.commit()


# ---------- Yksittäiset sarjat (muokkaus lennossa) ----------
@router.post(
    "/exercises/{workout_exercise_id}/sets",
    response_model=schemas.SetLogOut,
    status_code=201,
)
def add_set(
    workout_exercise_id: int, payload: schemas.SetLogCreate, db: Session = Depends(get_db)
):
    we = db.get(models.WorkoutExercise, workout_exercise_id)
    if not we:
        raise HTTPException(status_code=404, detail="Liikettä ei löytynyt.")
    s = models.SetLog(workout_exercise_id=workout_exercise_id, **payload.model_dump())
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.patch("/sets/{set_id}", response_model=schemas.SetLogOut)
def update_set(set_id: int, payload: schemas.SetLogBase, db: Session = Depends(get_db)):
    s = db.get(models.SetLog, set_id)
    if not s:
        raise HTTPException(status_code=404, detail="Sarjaa ei löytynyt.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(s, key, value)
    db.commit()
    db.refresh(s)
    return s


@router.delete("/sets/{set_id}", status_code=204)
def delete_set(set_id: int, db: Session = Depends(get_db)):
    s = db.get(models.SetLog, set_id)
    if not s:
        raise HTTPException(status_code=404, detail="Sarjaa ei löytynyt.")
    db.delete(s)
    db.commit()
