"""Dieettimoottori: viikkokeskiarvoon perustuva ohjaus.

Laskee viikkokeskiarvon painosta, adaptiivisen TDEE:n toteutuneesta syönnistä
ja painomuutoksesta, makrotavoitteet ja suosituksen kalorien säädöstä.
Seuraa myös ettei rauta heikkene dieetillä, bulkin vyötärö-rajaa ja kehon
alueiden kehitystä (onko tullut uutta lihasta vyötäröön nähden).
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import engine, models
from ..database import get_db

router = APIRouter(prefix="/api/diet", tags=["diet"])


# Neljä yleistä dieettimallia.
DIET_MODELS = [
    {"id": "cut_maltillinen", "name": "Maltillinen pudotus", "goal": "cut",
     "target_rate": -0.5, "info": "~0.5 kg/vk. Säilyttää lihasta ja voimaa hyvin."},
    {"id": "cut_aggressiivinen", "name": "Aggressiivinen pudotus", "goal": "cut",
     "target_rate": -0.9, "info": "~0.9 kg/vk. Nopea, mutta vaatii korkean proteiinin ja voiman seurannan."},
    {"id": "yllapito", "name": "Ylläpito", "goal": "maintain",
     "target_rate": 0.0, "info": "Pidä paino vakaana ja keskity suorituskykyyn."},
    {"id": "lean_bulk", "name": "Lean bulk", "goal": "bulk",
     "target_rate": 0.20, "info": "~0.2 kg/vk. Hidas massan nosto minimoiden rasvan kertymisen."},
    {"id": "cut_16_8", "name": "16:8 paasto (cut)", "goal": "cut", "target_rate": -0.5,
     "info": "Syöt 8 tunnin ikkunassa (esim. 12–20), paastoat 16 h. Sama kaloritavoite, "
             "harvempi mutta isompi ateria. Helpottaa kalorivajeen pitämistä monelle."},
    {"id": "cut_lowcarb", "name": "Low carb cut", "goal": "cut", "target_rate": -0.5,
     "low_carb": True,
     "info": "Vähähiilihydraattinen pudotus: hiilarit minimiin, rasva korkeammaksi, "
             "proteiini korkea. Hyvä jos hiilarit lisäävät napostelua."},
]


class DietPhaseIn(BaseModel):
    profile_id: int
    model: str  # DIET_MODELS id
    start_weight: float | None = None


@router.get("/models")
def list_models():
    return DIET_MODELS


@router.get("/phase")
def get_phase(profile_id: int = Query(...), db: Session = Depends(get_db)):
    phase = (
        db.query(models.DietPhase)
        .filter(models.DietPhase.profile_id == profile_id, models.DietPhase.is_active.is_(True))
        .order_by(models.DietPhase.start_date.desc())
        .first()
    )
    if not phase:
        return None
    return {
        "id": phase.id, "goal": phase.goal, "model": phase.model,
        "target_rate": phase.target_rate, "start_date": phase.start_date.isoformat(),
        "start_weight": phase.start_weight,
    }


@router.post("/phase")
def set_phase(payload: DietPhaseIn, db: Session = Depends(get_db)):
    """Aloita uusi dieettivaihe (sulkee aiemman aktiivisen)."""
    model = next((m for m in DIET_MODELS if m["id"] == payload.model), None)
    if not model:
        raise HTTPException(status_code=404, detail="Dieettimallia ei löytynyt.")
    # Sulje aiemmat aktiiviset
    for p in db.query(models.DietPhase).filter(
        models.DietPhase.profile_id == payload.profile_id, models.DietPhase.is_active.is_(True)
    ).all():
        p.is_active = False
    phase = models.DietPhase(
        profile_id=payload.profile_id, goal=model["goal"], model=model["name"],
        target_rate=model["target_rate"], start_weight=payload.start_weight,
    )
    db.add(phase)
    db.commit()
    db.refresh(phase)
    return {"id": phase.id, "goal": phase.goal, "model": phase.model, "target_rate": phase.target_rate}


@router.delete("/phase/{phase_id}", status_code=204)
def end_phase(phase_id: int, db: Session = Depends(get_db)):
    phase = db.get(models.DietPhase, phase_id)
    if phase:
        phase.is_active = False
        db.commit()


def _avg_daily_cardio_kcal(db: Session, profile_id: int, ref_date: date, days: int) -> float:
    """Keskimääräinen kardiosta poltettu kcal/pv viim. N päivältä (jaettuna
    koko jaksolle, koska kardiota ei tehdä joka päivä)."""
    start = ref_date - timedelta(days=days - 1)
    sessions = (db.query(models.CardioSession)
                .filter(models.CardioSession.profile_id == profile_id,
                        models.CardioSession.session_date >= start,
                        models.CardioSession.session_date <= ref_date).all())
    total = sum(s.kcal or 0 for s in sessions)
    return round(total / days)


def _daily_kcal(db: Session, profile_id: int) -> dict[date, float]:
    out: dict[date, float] = {}
    for fl in db.query(models.FoodLog).filter(models.FoodLog.profile_id == profile_id).all():
        out[fl.entry_date] = out.get(fl.entry_date, 0.0) + fl.food.kcal * fl.grams / 100.0
    return out


def _strength_trend(db: Session, profile_id: int, ref_date: date) -> dict | None:
    """Vertaa kokonaisrautaa (tonnage) viim. 14 pv vs sitä edeltävät 14 pv.
    Dieetillä halutaan ettei rauta heikkene merkittävästi."""
    sessions = (
        db.query(models.WorkoutSession)
        .filter(models.WorkoutSession.profile_id == profile_id,
                models.WorkoutSession.status != "skipped")
        .all()
    )
    recent, prev = [], []
    for s in sessions:
        tonnage = 0.0
        for we in s.exercises:
            top_w = max((st.weight for st in we.sets if st.completed), default=0.0)
            tonnage += sum(st.weight * st.reps for st in we.sets if st.completed)
            if we.missed_reps:
                tonnage = max(0.0, tonnage - we.missed_reps * top_w)
        age = (ref_date - s.session_date).days
        if 0 <= age < 14:
            recent.append(tonnage)
        elif 14 <= age < 28:
            prev.append(tonnage)
    if not recent or not prev:
        return None
    r, p = sum(recent) / len(recent), sum(prev) / len(prev)
    change_pct = round((r - p) / p * 100, 1) if p else 0.0
    return {"recent_avg_kg": round(r), "prev_avg_kg": round(p), "change_pct": change_pct}


def _area_assessment(db: Session, profile_id: int) -> dict:
    """Kehon alueiden kehitys: per kohta muutos (cm) sekä lihaskasvun indikaattori
    vyötäröön nähden (kasvoiko raaja samalla kun vyötärö pysyi/pieneni)."""
    measurements = (
        db.query(models.Measurement)
        .filter(models.Measurement.profile_id == profile_id)
        .order_by(models.Measurement.entry_date)
        .all()
    )
    by_site: dict[str, list] = {}
    for m in measurements:
        by_site.setdefault(m.site, []).append((m.entry_date, m.value_cm))

    waist_change = 0.0
    if "vyötärö" in by_site and len(by_site["vyötärö"]) >= 2:
        waist_change = by_site["vyötärö"][-1][1] - by_site["vyötärö"][0][1]

    areas = []
    for site, vals in by_site.items():
        if len(vals) < 2:
            change = 0.0
        else:
            change = round(vals[-1][1] - vals[0][1], 1)
        entry = {"site": site, "latest_cm": vals[-1][1], "change_cm": change}
        # Lihaskasvun indikaattori: raaja kasvoi mutta vyötärö ei
        if site != "vyötärö" and change > 0 and waist_change <= 0.5:
            entry["note"] = "kasvanut ilman vyötärön kasvua → todennäköisesti uutta lihasta"
        elif site != "vyötärö" and change < 0:
            entry["note"] = "pienentynyt"
        areas.append(entry)
    areas.sort(key=lambda a: a["change_cm"], reverse=True)
    return {"areas": areas, "waist_change_cm": round(waist_change, 1)}


def _training_profile(db: Session, profile_id: int, ref_date: date) -> tuple[int, float | None]:
    """Arvioi treenipäivät/viikko (tuoreesta tiheydestä) ja keskim. treenin kcal."""
    sessions = (
        db.query(models.WorkoutSession)
        .filter(models.WorkoutSession.profile_id == profile_id,
                models.WorkoutSession.status != "skipped")
        .all()
    )
    recent = [s for s in sessions if 0 <= (ref_date - s.session_date).days < 21]
    if recent:
        # Toteutunut tiheys viim. 3 viikolta (voi olla matala jos on jätetty treenaamatta)
        per_week = max(0, min(7, round(len(recent) / 3)))
    elif sessions:
        per_week = 0  # treenejä on historiassa, mutta ei viime aikoina -> tauolla
    else:
        per_week = 3  # ei dataa lainkaan -> oletetaan maltillinen treenitausta
    kcals = [s.kcal_burned for s in sessions
             if s.kcal_burned and 0 <= (ref_date - s.session_date).days < 30]
    kcal_avg = round(sum(kcals) / len(kcals)) if kcals else None
    return per_week, kcal_avg


@router.get("/status")
def diet_status(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Kooste: trendi, TDEE, makrotavoitteet, suositus, vyötärö ja alueet."""
    profile = db.get(models.Profile, profile_id)
    phase = (
        db.query(models.DietPhase)
        .filter(models.DietPhase.profile_id == profile_id, models.DietPhase.is_active.is_(True))
        .first()
    )
    goal = phase.goal if phase else "maintain"
    target_rate = phase.target_rate if phase else 0.0

    entries = (
        db.query(models.BodyEntry)
        .filter(models.BodyEntry.profile_id == profile_id, models.BodyEntry.bodyweight.isnot(None))
        .order_by(models.BodyEntry.entry_date)
        .all()
    )
    points = [(e.entry_date, e.bodyweight) for e in entries]
    if not points:
        return {"goal": goal, "target_rate": target_rate, "message": "Kirjaa painoa muutaman päivän ajan, niin saat dieettiohjauksen."}

    ref_date = max(d for d, _ in points)
    week_avg = engine.weekly_average(points, ref_date, 7) or points[-1][1]
    trend = engine.weight_trend(points, ref_date)

    # Adaptiivinen TDEE 14 pv ikkunasta jos syöntidataa on, muuten arvio painosta
    kcal_by_date = _daily_kcal(db, profile_id)
    window_days = 14
    start = ref_date - timedelta(days=window_days - 1)
    intake_days = [kcal_by_date[d] for d in kcal_by_date if start <= d <= ref_date]
    avg_intake = sum(intake_days) / len(intake_days) if intake_days else None
    w_start = engine.weekly_average(points, start + timedelta(days=6), 7)
    w_end = engine.weekly_average(points, ref_date, 7)
    weight_change = (w_end - w_start) if (w_start and w_end) else 0.0

    # Treenitiheys (vaikuttaa kulutukseen) ja keskim. treenin kcal
    training_days, workout_kcal_avg = _training_profile(db, profile_id, ref_date)

    tdee = engine.adaptive_tdee(avg_intake, weight_change, window_days) if avg_intake else None
    if not tdee:
        # Ei syöntidataa vielä -> arvio painosta/pituudesta/iästä JA treenimäärästä
        age = engine.age_from_birthdate(profile.birthdate, date.today()) if profile else None
        tdee = engine.baseline_tdee(
            week_avg, profile.height_cm if profile else None, age,
            profile.sex if profile else None, training_days)
        # Lisää keskimääräinen kardiokulutus/pv (adaptiivinen malli huomioi
        # kardion jo automaattisesti painomuutoksen kautta).
        if tdee:
            tdee += _avg_daily_cardio_kcal(db, profile_id, ref_date, 14)

    low_carb = bool(next((m for m in DIET_MODELS
                          if phase and m["name"] == phase.model and m.get("low_carb")), None))
    targets = engine.macro_targets(week_avg, goal, tdee, target_rate, low_carb=low_carb)
    recommendation = engine.diet_recommendation(goal, target_rate, trend, avg_intake, targets)

    # Vyötärö (viimeisin) bulk-rajaa varten
    waist = (
        db.query(models.Measurement)
        .filter(models.Measurement.profile_id == profile_id, models.Measurement.site == "vyötärö")
        .order_by(models.Measurement.entry_date.desc())
        .first()
    )
    height = profile.height_cm if profile else None
    waist_info = engine.waist_assessment(waist.value_cm if waist else None, height, goal)

    strength = _strength_trend(db, profile_id, ref_date)
    strength_note = None
    if strength and goal == "cut" and strength["change_pct"] < -5:
        strength_note = (f"Rauta heikkenee dieetillä ({strength['change_pct']} %). Hidasta pudotusta tai "
                         f"nosta proteiinia — tavoite on säilyttää voima.")
    elif strength and strength["change_pct"] > 0:
        strength_note = f"Rauta kehittyy edelleen ({strength['change_pct']:+}%)."

    # Per-päivä-tavoitteet (treeni- vs lepopäivä) ja viikkoyhteenveto
    day_targets = engine.day_targets(targets, training_days, workout_kcal_avg)
    review = engine.weekly_review(targets["kcal"], avg_intake, target_rate, trend)

    # Kardio-/lämmittelyvinkit tavoitteen mukaan
    cardio_tip = None
    if goal == "cut":
        cardio_tip = ("Tehosta kcal-polttoa: 20–40 min kävelyä tai juoksumattoa treenin jälkeen tai "
                      "lepopäivänä lisää kulutusta ~150–350 kcal syömättä palautumista — helpottaa vajeen "
                      "saavuttamista ilman että tarvitsee leikata ruokaa lisää. Kirjaa se Palautuminen-välilehden kardioon.")
    elif goal == "maintain" and trend is not None and trend > 0.15:
        cardio_tip = ("Paino nousee tavoitetta nopeammin. Lisää arkeen kävelyä tai kevyttä kardiota "
                      "(esim. crosstrainer 20–30 min) tasapainottamaan, tai laske hieman kaloreita.")
    elif goal == "bulk":
        cardio_tip = ("Massalla kevyt kardio (kävely 2–3× viikossa) pitää sydänkunnon ja ruokahalun kunnossa "
                      "ilman että se haittaa massan nousua — älä ylitä, jottei kulutus kasva liikaa.")

    return {
        "goal": goal,
        "target_rate": target_rate,
        "cardio_tip": cardio_tip,
        "model": phase.model if phase else None,
        "week_avg_weight": week_avg,
        "trend_kg_per_week": trend,
        "intake_avg_kcal": round(avg_intake) if avg_intake else None,
        "targets": targets,
        "day_targets": day_targets,
        "weekly_review": review,
        "recommendation": recommendation,
        "waist": waist_info,
        "strength_trend": strength,
        "strength_note": strength_note,
        "body_areas": _area_assessment(db, profile_id),
    }


def _current_targets(db: Session, profile_id: int) -> tuple[dict | None, bool]:
    """Laske tämänhetkiset päivätavoitteet (sama logiikka kuin statuksessa).
    Palauttaa (targets, is_fasting). Käytetään ateria-aikataulussa."""
    phase = (
        db.query(models.DietPhase)
        .filter(models.DietPhase.profile_id == profile_id, models.DietPhase.is_active.is_(True))
        .first()
    )
    goal = phase.goal if phase else "maintain"
    target_rate = phase.target_rate if phase else 0.0
    entries = (
        db.query(models.BodyEntry)
        .filter(models.BodyEntry.profile_id == profile_id, models.BodyEntry.bodyweight.isnot(None))
        .order_by(models.BodyEntry.entry_date)
        .all()
    )
    points = [(e.entry_date, e.bodyweight) for e in entries]
    if not points:
        return None, False
    ref_date = max(d for d, _ in points)
    week_avg = engine.weekly_average(points, ref_date, 7) or points[-1][1]
    kcal_by_date = _daily_kcal(db, profile_id)
    start = ref_date - timedelta(days=13)
    intake_days = [kcal_by_date[d] for d in kcal_by_date if start <= d <= ref_date]
    avg_intake = sum(intake_days) / len(intake_days) if intake_days else None
    w_start = engine.weekly_average(points, start + timedelta(days=6), 7)
    w_end = engine.weekly_average(points, ref_date, 7)
    weight_change = (w_end - w_start) if (w_start and w_end) else 0.0
    tdee = engine.adaptive_tdee(avg_intake, weight_change, 14) if avg_intake else None
    if not tdee:
        profile = db.get(models.Profile, profile_id)
        age = engine.age_from_birthdate(profile.birthdate, date.today()) if profile else None
        training_days, _ = _training_profile(db, profile_id, ref_date)
        tdee = engine.baseline_tdee(
            week_avg, profile.height_cm if profile else None, age,
            profile.sex if profile else None, training_days)
    model = next((m for m in DIET_MODELS if phase and m["name"] == phase.model), None)
    low_carb = bool(model and model.get("low_carb"))
    fasting = bool(model and model["id"] == "cut_16_8")
    targets = engine.macro_targets(week_avg, goal, tdee, target_rate, low_carb=low_carb)
    return targets, fasting


@router.get("/meal-plan")
def meal_plan(
    profile_id: int = Query(...),
    meals: int = Query(4),
    wake: str | None = Query(None),
    sleep: str | None = Query(None),
    training: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Jaksota päivän makrot aterioille kellonaikojen ja treeniajan mukaan.

    meals: aterioiden määrä (sisältää välipalat). wake/sleep/training: 'HH:MM'.
    16:8-paastomalli rajaa syönti-ikkunan automaattisesti.
    """
    targets, fasting = _current_targets(db, profile_id)
    if not targets:
        return {"message": "Aseta dieettivaihe ja kirjaa paino, niin saat ateria-aikataulun.",
                "meals": []}
    plan = engine.meal_schedule(targets, meals, wake, sleep, training, fasting_16_8=fasting)
    return {
        "targets": targets,
        "fasting": fasting,
        "meals_per_day": meals,
        "meals": plan,
    }
