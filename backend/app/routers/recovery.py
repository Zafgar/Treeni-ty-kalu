"""Palautuminen ja kunto: kardiotapahtumat, aerobisen kunnon seuranta ja
valmiuspisteet (ylikuormituksen tunnistus uni/HRV/leposyke/kuorma-yhdistelmästä).

Kardio tuo poltetut kalorit myös päivän kokonaiskulutukseen (dieettipuoli).
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import engine, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/recovery", tags=["recovery"])


# METs eri lajeille kun kalorimäärää ei anneta (arvio painosta ja kestosta).
CARDIO_MET = {
    "juoksumatto": 9.0, "juoksu": 9.5, "crosstrainer": 7.0, "pyöräily": 7.5,
    "kävely": 3.8, "soutu": 7.0, "uinti": 7.0, "hyppynaru": 11.0, "muu": 6.0,
}


# ---------- Kardiotapahtumat ----------
@router.get("/cardio", response_model=list[schemas.CardioSessionOut])
def list_cardio(profile_id: int | None = Query(None), db: Session = Depends(get_db)):
    q = db.query(models.CardioSession)
    if profile_id is not None:
        q = q.filter(models.CardioSession.profile_id == profile_id)
    return q.order_by(models.CardioSession.session_date.desc(), models.CardioSession.id.desc()).all()


@router.post("/cardio", response_model=schemas.CardioSessionOut, status_code=201)
def create_cardio(payload: schemas.CardioSessionCreate, profile_id: int = Query(...),
                  db: Session = Depends(get_db)):
    # Arvioi kcal jos ei annettu mutta paino + kesto tiedossa (MET-kaava)
    kcal = payload.kcal
    if not kcal and payload.duration_min:
        bw = _latest_bodyweight(db, profile_id)
        if bw:
            met = CARDIO_MET.get(payload.activity, 6.0)
            kcal = round(met * bw * (payload.duration_min / 60.0))
    session = models.CardioSession(
        profile_id=profile_id,
        session_date=payload.session_date or date.today(),
        activity=payload.activity,
        duration_min=payload.duration_min,
        kcal=kcal,
        avg_hr=payload.avg_hr,
        distance_km=payload.distance_km,
        notes=payload.notes,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.delete("/cardio/{cardio_id}", status_code=204)
def delete_cardio(cardio_id: int, db: Session = Depends(get_db)):
    c = db.get(models.CardioSession, cardio_id)
    if not c:
        raise HTTPException(status_code=404, detail="Kardiotapahtumaa ei löytynyt.")
    db.delete(c)
    db.commit()


def _latest_bodyweight(db: Session, profile_id: int | None) -> float | None:
    if profile_id is None:
        return None
    b = (db.query(models.BodyEntry)
         .filter(models.BodyEntry.profile_id == profile_id, models.BodyEntry.bodyweight.isnot(None))
         .order_by(models.BodyEntry.entry_date.desc()).first())
    return b.bodyweight if b else None


@router.get("/cardio/trend")
def cardio_trend(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Aerobisen kunnon kehitys: per tapahtuma keskinopeus (km/h) ja tahti
    (min/km) sekä viikon kokonaiskesto ja -kalorit."""
    sessions = (db.query(models.CardioSession)
                .filter(models.CardioSession.profile_id == profile_id)
                .order_by(models.CardioSession.session_date).all())
    points = []
    for s in sessions:
        speed = pace = None
        if s.distance_km and s.duration_min and s.duration_min > 0:
            speed = round(s.distance_km / (s.duration_min / 60.0), 2)  # km/h
            pace = round(s.duration_min / s.distance_km, 2)            # min/km
        points.append({
            "date": s.session_date.isoformat(), "activity": s.activity,
            "duration_min": s.duration_min, "kcal": s.kcal, "avg_hr": s.avg_hr,
            "distance_km": s.distance_km, "speed_kmh": speed, "pace_min_km": pace,
        })
    # Viikon yhteenveto (viim. 7 pv)
    today = date.today()
    week = [s for s in sessions if 0 <= (today - s.session_date).days < 7]
    week_kcal = round(sum(s.kcal or 0 for s in week))
    week_min = round(sum(s.duration_min or 0 for s in week))
    return {"points": points, "week_kcal": week_kcal, "week_minutes": week_min, "week_sessions": len(week)}


def _session_tonnage(s: models.WorkoutSession) -> float:
    tonnage = 0.0
    for we in s.exercises:
        top_w = max((st.weight for st in we.sets if st.completed), default=0.0)
        tonnage += sum(st.weight * st.reps for st in we.sets if st.completed)
        if we.missed_reps:
            tonnage = max(0.0, tonnage - we.missed_reps * top_w)
    return tonnage


@router.get("/readiness")
def readiness(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Valmiuspisteet ja ylikuormitusvaroitukset: HRV, leposyke, uni ja
    treenikuorman akuutti:krooninen-suhde (ACWR) yhdistettynä."""
    today = date.today()
    entries = (db.query(models.BodyEntry)
               .filter(models.BodyEntry.profile_id == profile_id)
               .order_by(models.BodyEntry.entry_date).all())

    def _avg(key, days_from, days_to):
        vals = [getattr(e, key) for e in entries
                if getattr(e, key) is not None
                and days_from <= (today - e.entry_date).days < days_to]
        return sum(vals) / len(vals) if vals else None

    hrv_recent = _avg("hrv", 0, 7)
    hrv_base = _avg("hrv", 7, 35)
    rhr_recent = _avg("resting_hr", 0, 7)
    rhr_base = _avg("resting_hr", 7, 35)
    sleep_recent = _avg("sleep_hours", 0, 7)

    # Treenikuorma: kokonaiskuorma (rauta) + kardiokalorit, ACWR
    workouts = (db.query(models.WorkoutSession)
                .filter(models.WorkoutSession.profile_id == profile_id,
                        models.WorkoutSession.status != "skipped").all())
    cardio = (db.query(models.CardioSession)
              .filter(models.CardioSession.profile_id == profile_id).all())

    def load_in(days_from, days_to):
        load = 0.0
        for s in workouts:
            if days_from <= (today - s.session_date).days < days_to:
                load += _session_tonnage(s)
        for c in cardio:
            if days_from <= (today - c.session_date).days < days_to:
                load += (c.kcal or 0) * 20  # kardio samaan mittakaavaan kuorman kanssa
        return load

    acute = load_in(0, 7)
    chronic4 = load_in(0, 28) / 4.0  # keskiviikko 4 viikolta
    acwr_info = engine.acwr_status(acute, chronic4)
    acwr = acwr_info["acwr"] if acwr_info else None

    result = engine.readiness(hrv_recent, hrv_base, rhr_recent, rhr_base, sleep_recent, acwr)
    result["acwr"] = acwr_info
    result["has_data"] = bool(result["factors"])
    return result
