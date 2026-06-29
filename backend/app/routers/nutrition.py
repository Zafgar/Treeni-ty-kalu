"""Ravintoseuranta: ruokakirjasto, päiväkirjaus ja intake-yhteenveto.

Ruoka-aineet (esim. maitorahka, banaani) ovat yhteisessä kirjastossa makroineen
(per 100 g). Käyttäjä lisää omia helposti. Päiväkohtaiset kirjaukset summataan
intake-graafiin, jota voi verrata painon ja voimatason kehitykseen.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/nutrition", tags=["nutrition"])


# ---------- Ruokakirjasto ----------
@router.get("/foods", response_model=list[schemas.FoodOut])
def list_foods(db: Session = Depends(get_db)):
    return db.query(models.Food).order_by(models.Food.name).all()


@router.post("/foods", response_model=schemas.FoodOut, status_code=201)
def create_food(payload: schemas.FoodCreate, db: Session = Depends(get_db)):
    if db.query(models.Food).filter(models.Food.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Ruoka samalla nimellä on jo olemassa.")
    food = models.Food(**payload.model_dump())
    db.add(food)
    db.commit()
    db.refresh(food)
    return food


@router.delete("/foods/{food_id}", status_code=204)
def delete_food(food_id: int, db: Session = Depends(get_db)):
    food = db.get(models.Food, food_id)
    if not food:
        raise HTTPException(status_code=404, detail="Ruokaa ei löytynyt.")
    db.delete(food)
    db.commit()


# ---------- Päiväkirjaus ----------
@router.get("/logs", response_model=list[schemas.FoodLogOut])
def list_logs(
    profile_id: int = Query(...),
    on_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(models.FoodLog).filter(models.FoodLog.profile_id == profile_id)
    if on_date is not None:
        q = q.filter(models.FoodLog.entry_date == on_date)
    return q.order_by(models.FoodLog.entry_date.desc(), models.FoodLog.id.desc()).all()


@router.post("/logs", response_model=schemas.FoodLogOut, status_code=201)
def create_log(profile_id: int, payload: schemas.FoodLogCreate, db: Session = Depends(get_db)):
    if not db.get(models.Food, payload.food_id):
        raise HTTPException(status_code=404, detail="Ruokaa ei löytynyt.")
    log = models.FoodLog(
        profile_id=profile_id,
        entry_date=payload.entry_date or date.today(),
        food_id=payload.food_id,
        grams=payload.grams,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.delete("/logs/{log_id}", status_code=204)
def delete_log(log_id: int, db: Session = Depends(get_db)):
    log = db.get(models.FoodLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Kirjausta ei löytynyt.")
    db.delete(log)
    db.commit()


# ---------- Yhteenveto + intake-aikasarja ----------
def _macros(food: models.Food, grams: float) -> dict:
    f = grams / 100.0
    return {
        "kcal": food.kcal * f,
        "protein_g": food.protein_g * f,
        "carbs_g": food.carbs_g * f,
        "fat_g": food.fat_g * f,
    }


@router.get("/summary")
def summary(
    profile_id: int = Query(...),
    on_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    """Päivän makrosumma (oletus tänään) ja koko intake-aikasarja graafia varten."""
    target_date = on_date or date.today()
    logs = db.query(models.FoodLog).filter(models.FoodLog.profile_id == profile_id).all()

    today_totals = {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    by_date: dict[date, dict] = {}
    for log in logs:
        m = _macros(log.food, log.grams)
        agg = by_date.setdefault(log.entry_date, {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0})
        for k in agg:
            agg[k] += m[k]
        if log.entry_date == target_date:
            for k in today_totals:
                today_totals[k] += m[k]

    timeline = [
        {"date": d.isoformat(), **{k: round(v) for k, v in by_date[d].items()}}
        for d in sorted(by_date)
    ]
    return {
        "date": target_date.isoformat(),
        "today": {k: round(v, 1) for k, v in today_totals.items()},
        "timeline": timeline,
    }
