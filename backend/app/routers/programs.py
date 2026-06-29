"""Treeniohjelmat: sykli- tai viikkopohjaiset, päivineen ja liikkeineen.

Kaikkea voi muokata lennossa: päiviä ja liikkeitä lisätään/poistetaan
omilla päätepisteillään ilman että koko ohjelmaa tarvitsee luoda uudelleen.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/programs", tags=["programs"])


@router.get("", response_model=list[schemas.ProgramOut])
def list_programs(profile_id: int | None = Query(None), db: Session = Depends(get_db)):
    q = db.query(models.Program)
    if profile_id is not None:
        q = q.filter(models.Program.profile_id == profile_id)
    return q.order_by(models.Program.created_at.desc()).all()


@router.post("", response_model=schemas.ProgramOut, status_code=201)
def create_program(payload: schemas.ProgramCreate, db: Session = Depends(get_db)):
    program = models.Program(
        name=payload.name,
        profile_id=payload.profile_id,
        schedule_type=payload.schedule_type,
        description=payload.description,
        goal=payload.goal,
        is_active=payload.is_active,
    )
    for day_in in payload.days:
        day = models.ProgramDay(
            order_index=day_in.order_index,
            day_type=day_in.day_type,
            label=day_in.label,
        )
        for ex_in in day_in.exercises:
            day.exercises.append(models.ProgramExercise(**ex_in.model_dump()))
        program.days.append(day)
    db.add(program)
    db.commit()
    db.refresh(program)
    return program


@router.get("/{program_id}", response_model=schemas.ProgramOut)
def get_program(program_id: int, db: Session = Depends(get_db)):
    program = db.get(models.Program, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="Ohjelmaa ei löytynyt.")
    return program


@router.patch("/{program_id}", response_model=schemas.ProgramOut)
def update_program(
    program_id: int, payload: schemas.ProgramUpdate, db: Session = Depends(get_db)
):
    program = db.get(models.Program, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="Ohjelmaa ei löytynyt.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(program, key, value)
    db.commit()
    db.refresh(program)
    return program


@router.delete("/{program_id}", status_code=204)
def delete_program(program_id: int, db: Session = Depends(get_db)):
    program = db.get(models.Program, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="Ohjelmaa ei löytynyt.")
    db.delete(program)
    db.commit()


# ---------- Päivät (muokkaus lennossa) ----------
@router.post("/{program_id}/days", response_model=schemas.ProgramDayOut, status_code=201)
def add_day(program_id: int, payload: schemas.ProgramDayCreate, db: Session = Depends(get_db)):
    program = db.get(models.Program, program_id)
    if not program:
        raise HTTPException(status_code=404, detail="Ohjelmaa ei löytynyt.")
    day = models.ProgramDay(
        program_id=program_id,
        order_index=payload.order_index,
        day_type=payload.day_type,
        label=payload.label,
    )
    for ex_in in payload.exercises:
        day.exercises.append(models.ProgramExercise(**ex_in.model_dump()))
    db.add(day)
    db.commit()
    db.refresh(day)
    return day


@router.delete("/days/{day_id}", status_code=204)
def delete_day(day_id: int, db: Session = Depends(get_db)):
    day = db.get(models.ProgramDay, day_id)
    if not day:
        raise HTTPException(status_code=404, detail="Päivää ei löytynyt.")
    db.delete(day)
    db.commit()


# ---------- Liikkeet päivällä (muokkaus lennossa) ----------
@router.post(
    "/days/{day_id}/exercises",
    response_model=schemas.ProgramExerciseOut,
    status_code=201,
)
def add_day_exercise(
    day_id: int, payload: schemas.ProgramExerciseCreate, db: Session = Depends(get_db)
):
    day = db.get(models.ProgramDay, day_id)
    if not day:
        raise HTTPException(status_code=404, detail="Päivää ei löytynyt.")
    pe = models.ProgramExercise(program_day_id=day_id, **payload.model_dump())
    db.add(pe)
    db.commit()
    db.refresh(pe)
    return pe


@router.patch(
    "/exercises/{program_exercise_id}", response_model=schemas.ProgramExerciseOut
)
def update_day_exercise(
    program_exercise_id: int,
    payload: schemas.ProgramExerciseBase,
    db: Session = Depends(get_db),
):
    pe = db.get(models.ProgramExercise, program_exercise_id)
    if not pe:
        raise HTTPException(status_code=404, detail="Liikettä ei löytynyt.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(pe, key, value)
    db.commit()
    db.refresh(pe)
    return pe


@router.delete("/exercises/{program_exercise_id}", status_code=204)
def delete_day_exercise(program_exercise_id: int, db: Session = Depends(get_db)):
    pe = db.get(models.ProgramExercise, program_exercise_id)
    if not pe:
        raise HTTPException(status_code=404, detail="Liikettä ei löytynyt.")
    db.delete(pe)
    db.commit()
