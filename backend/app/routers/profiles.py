"""Profiilien hallinta: vaihda ketä seuraat (oma, valmennettavat, läheiset)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import engine, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


def _profile_summary(db: Session, p: models.Profile) -> dict:
    """Profiili + yleisnäkymän tunnusluvut yhdessä."""
    workouts = db.query(models.WorkoutSession).filter(models.WorkoutSession.profile_id == p.id).count()
    programs = db.query(models.Program).filter(models.Program.profile_id == p.id).count()
    last_body = (
        db.query(models.BodyEntry)
        .filter(models.BodyEntry.profile_id == p.id, models.BodyEntry.bodyweight.isnot(None))
        .order_by(models.BodyEntry.entry_date.desc())
        .first()
    )
    age = engine.age_from_birthdate(p.birthdate, date.today())
    return {
        "id": p.id, "name": p.name, "sex": p.sex,
        "birthdate": p.birthdate.isoformat() if p.birthdate else None,
        "age": age, "height_cm": p.height_cm, "color": p.color, "notes": p.notes,
        "creatine": bool(p.creatine),
        "experience": p.experience, "training_years": p.training_years,
        "goal": p.goal, "days_per_week": p.days_per_week,
        "workouts": workouts, "programs": programs,
        "latest_bodyweight": last_body.bodyweight if last_body else None,
    }


@router.get("")
def list_profiles(db: Session = Depends(get_db)):
    profiles = db.query(models.Profile).order_by(models.Profile.name).all()
    return [_profile_summary(db, p) for p in profiles]


@router.post("", response_model=schemas.ProfileOut, status_code=201)
def create_profile(payload: schemas.ProfileCreate, db: Session = Depends(get_db)):
    p = models.Profile(**payload.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/{profile_id}")
def get_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.get(models.Profile, profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profiilia ei löytynyt.")
    return _profile_summary(db, p)


@router.patch("/{profile_id}", response_model=schemas.ProfileOut)
def update_profile(profile_id: int, payload: schemas.ProfileUpdate, db: Session = Depends(get_db)):
    p = db.get(models.Profile, profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profiilia ei löytynyt.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(p, key, value)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.get(models.Profile, profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profiilia ei löytynyt.")
    if db.query(models.Profile).count() <= 1:
        raise HTTPException(status_code=400, detail="Vähintään yksi profiili tarvitaan.")
    db.delete(p)
    db.commit()
