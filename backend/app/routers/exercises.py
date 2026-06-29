"""Liikkeiden hallinta: lisää mikä tahansa liike, muokkaa, poista."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/exercises", tags=["exercises"])


@router.get("", response_model=list[schemas.ExerciseOut])
def list_exercises(db: Session = Depends(get_db)):
    return db.query(models.Exercise).order_by(models.Exercise.name).all()


@router.post("", response_model=schemas.ExerciseOut, status_code=201)
def create_exercise(payload: schemas.ExerciseCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Exercise).filter(models.Exercise.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=409, detail="Liike samalla nimellä on jo olemassa.")
    ex = models.Exercise(**payload.model_dump())
    db.add(ex)
    db.commit()
    db.refresh(ex)
    return ex


@router.get("/{exercise_id}", response_model=schemas.ExerciseOut)
def get_exercise(exercise_id: int, db: Session = Depends(get_db)):
    ex = db.get(models.Exercise, exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Liikettä ei löytynyt.")
    return ex


@router.patch("/{exercise_id}", response_model=schemas.ExerciseOut)
def update_exercise(
    exercise_id: int, payload: schemas.ExerciseUpdate, db: Session = Depends(get_db)
):
    ex = db.get(models.Exercise, exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Liikettä ei löytynyt.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(ex, key, value)
    db.commit()
    db.refresh(ex)
    return ex


@router.delete("/{exercise_id}", status_code=204)
def delete_exercise(exercise_id: int, db: Session = Depends(get_db)):
    ex = db.get(models.Exercise, exercise_id)
    if not ex:
        raise HTTPException(status_code=404, detail="Liikettä ei löytynyt.")
    db.delete(ex)
    db.commit()
