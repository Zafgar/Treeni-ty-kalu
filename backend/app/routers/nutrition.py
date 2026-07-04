"""Ravintoseuranta: ruokakirjasto, päiväkirjaus ja intake-yhteenveto.

Ruoka-aineet (esim. maitorahka, banaani) ovat yhteisessä kirjastossa makroineen
(per 100 g). Käyttäjä lisää omia helposti. Päiväkohtaiset kirjaukset summataan
intake-graafiin, jota voi verrata painon ja voimatason kehitykseen.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/nutrition", tags=["nutrition"])


# ---------- Ruokakirjasto ----------
@router.get("/foods", response_model=list[schemas.FoodOut])
def list_foods(
    category: str | None = Query(None),
    q: str | None = Query(None),
    favorites: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Hae ruokia kategorialla, nimihaulla ja/tai vain suosikit."""
    query = db.query(models.Food)
    if category:
        query = query.filter(models.Food.category == category)
    if q:
        query = query.filter(models.Food.name.ilike(f"%{q}%"))
    if favorites:
        query = query.filter(models.Food.is_favorite.is_(True))
    return query.order_by(models.Food.name).all()


@router.get("/categories")
def list_categories(db: Session = Depends(get_db)):
    rows = db.query(models.Food.category).filter(models.Food.category.isnot(None)).distinct().all()
    return sorted({r[0] for r in rows if r[0]})


@router.post("/foods", response_model=schemas.FoodOut, status_code=201)
def create_food(payload: schemas.FoodCreate, db: Session = Depends(get_db)):
    if db.query(models.Food).filter(models.Food.name == payload.name).first():
        raise HTTPException(status_code=409, detail="Ruoka samalla nimellä on jo olemassa.")
    food = models.Food(**payload.model_dump())
    db.add(food)
    db.commit()
    db.refresh(food)
    return food


@router.patch("/foods/{food_id}", response_model=schemas.FoodOut)
def update_food(food_id: int, payload: schemas.FoodUpdate, db: Session = Depends(get_db)):
    """Muokkaa ruokaa tai vaihda suosikkitila."""
    food = db.get(models.Food, food_id)
    if not food:
        raise HTTPException(status_code=404, detail="Ruokaa ei löytynyt.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(food, key, value)
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


@router.get("/recent", response_model=list[schemas.FoodOut])
def recent_foods(profile_id: int = Query(...), limit: int = Query(12), db: Session = Depends(get_db)):
    """Viimeksi kirjatut ruoat (uniikit) nopeaa uudelleenkirjausta varten."""
    logs = (db.query(models.FoodLog)
            .filter(models.FoodLog.profile_id == profile_id)
            .order_by(models.FoodLog.entry_date.desc(), models.FoodLog.id.desc())
            .limit(120).all())
    seen, foods = set(), []
    for lg in logs:
        if lg.food_id in seen:
            continue
        seen.add(lg.food_id)
        foods.append(lg.food)
        if len(foods) >= limit:
            break
    return foods


@router.post("/logs", response_model=schemas.FoodLogOut, status_code=201)
def create_log(profile_id: int, payload: schemas.FoodLogCreate,
               on_date: date | None = Query(None), db: Session = Depends(get_db)):
    if not db.get(models.Food, payload.food_id):
        raise HTTPException(status_code=404, detail="Ruokaa ei löytynyt.")
    log = models.FoodLog(
        profile_id=profile_id,
        entry_date=payload.entry_date or on_date or date.today(),
        food_id=payload.food_id,
        grams=payload.grams,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


@router.patch("/logs/{log_id}", response_model=schemas.FoodLogOut)
def update_log(log_id: int, payload: schemas.FoodLogUpdate, db: Session = Depends(get_db)):
    """Muokkaa kirjauksen grammamäärää jälkikäteen."""
    log = db.get(models.FoodLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="Kirjausta ei löytynyt.")
    log.grams = payload.grams
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


# ---------- Ateriat (omat ravintokokonaisuudet) ----------
@router.get("/meals", response_model=list[schemas.MealOut])
def list_meals(profile_id: int = Query(...), db: Session = Depends(get_db)):
    return (
        db.query(models.Meal)
        .filter(models.Meal.profile_id == profile_id)
        .order_by(models.Meal.name)
        .all()
    )


@router.post("/meals", response_model=schemas.MealOut, status_code=201)
def create_meal(profile_id: int, payload: schemas.MealCreate, db: Session = Depends(get_db)):
    meal = models.Meal(profile_id=profile_id, name=payload.name)
    for it in payload.items:
        meal.items.append(models.MealItem(food_id=it.food_id, grams=it.grams))
    db.add(meal)
    db.commit()
    db.refresh(meal)
    return meal


@router.delete("/meals/{meal_id}", status_code=204)
def delete_meal(meal_id: int, db: Session = Depends(get_db)):
    meal = db.get(models.Meal, meal_id)
    if not meal:
        raise HTTPException(status_code=404, detail="Ateriaa ei löytynyt.")
    db.delete(meal)
    db.commit()


@router.post("/meals/{meal_id}/log")
def log_meal(
    meal_id: int,
    profile_id: int = Query(...),
    on_date: date | None = Query(None),
    db: Session = Depends(get_db),
):
    """Pikakirjaa koko ateria päivän kirjauksiin (laajenee ruokakohtaisiksi riveiksi)."""
    meal = db.get(models.Meal, meal_id)
    if not meal:
        raise HTTPException(status_code=404, detail="Ateriaa ei löytynyt.")
    target = on_date or date.today()
    for it in meal.items:
        db.add(models.FoodLog(profile_id=profile_id, entry_date=target,
                              food_id=it.food_id, grams=it.grams))
    db.commit()
    return {"logged": len(meal.items), "date": target.isoformat()}


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

    # 7 pv liukuva keskiarvo: syönti heiluu paljon päivittäin (paljon maanantaina,
    # vähän tiistaina), joten VAKAA kuva saadaan usean päivän keskiarvosta. Tämä on
    # oikea vertailuluku makrotavoitteisiin — yksittäinen päivä ei ratkaise.
    window_start = target_date - timedelta(days=6)
    logged = {d: v for d, v in by_date.items() if window_start <= d <= target_date}
    days_logged = len(logged)
    avg7 = None
    if days_logged:
        avg7 = {k: round(sum(v[k] for v in logged.values()) / days_logged, 1)
                for k in today_totals}
        avg7["days_logged"] = days_logged
        avg7["window_days"] = 7
    return {
        "date": target_date.isoformat(),
        "today": {k: round(v, 1) for k, v in today_totals.items()},
        "avg7": avg7,
        "timeline": timeline,
    }
