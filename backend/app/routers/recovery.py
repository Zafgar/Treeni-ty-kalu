"""Palautuminen ja kunto: kardiotapahtumat, aerobisen kunnon seuranta ja
valmiuspisteet (ylikuormituksen tunnistus uni/HRV/leposyke/kuorma-yhdistelmästä).

Kardio tuo poltetut kalorit myös päivän kokonaiskulutukseen (dieettipuoli).
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import engine, models, schemas
from ..database import get_db
from .stats import _latest_bodyweight, _session_tonnage

router = APIRouter(prefix="/api/recovery", tags=["recovery"])


# METs eri lajeille kun kalorimäärää ei anneta (arvio painosta ja kestosta).
CARDIO_MET = {
    "juoksumatto": 9.0, "juoksu": 9.5, "crosstrainer": 7.0, "pyöräily": 7.5,
    "kävely": 3.8, "soutu": 7.0, "uinti": 7.0, "hyppynaru": 11.0, "muu": 6.0,
    # Lihashuolto / lämmittely (matala kulutus, mutta seurantaa varten)
    "lämmittely": 4.0, "venyttely": 2.5, "foam roll": 2.8, "liikkuvuus": 2.8,
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


@router.get("/readiness")
def readiness(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Valmiuspisteet ja ylikuormitusvaroitukset: HRV, leposyke, uni ja
    treenikuorman akuutti:krooninen-suhde (ACWR) yhdistettynä."""
    today = date.today()
    entries = (db.query(models.BodyEntry)
               .filter(models.BodyEntry.profile_id == profile_id)
               .order_by(models.BodyEntry.entry_date).all())

    def _stat(key, days_from, days_to):
        vals = [getattr(e, key) for e in entries
                if getattr(e, key) is not None
                and days_from <= (today - e.entry_date).days < days_to]
        return (sum(vals) / len(vals) if vals else None), len(vals)

    # Pitkän ajan vertailujakso (7–42 pv) vaimentaa yksittäiset heilahdukset
    hrv_recent, hrv_rn = _stat("hrv", 0, 7)
    hrv_base, hrv_bn = _stat("hrv", 7, 42)
    rhr_recent, rhr_rn = _stat("resting_hr", 0, 7)
    rhr_base, rhr_bn = _stat("resting_hr", 7, 42)
    sleep_recent, sleep_n = _stat("sleep_hours", 0, 7)

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
    # Krooninen = EDELTÄVIEN 4 viikon keskiarvo (pv 7-35), EI sisällä akuuttia
    # viikkoa — muuten piikki laimentaisi omaa vertailutasoaan. Lisäksi ACWR
    # lasketaan vasta kun historiaa on vähintään ~3 viikkoa: muuten uusi
    # käyttäjä saisi aina "kuormapiikin" koska vertailujakso on tyhjä.
    all_dates = ([s.session_date for s in workouts] + [c.session_date for c in cardio])
    history_days = max(((today - d).days for d in all_dates), default=0)
    chronic4 = load_in(7, 35) / 4.0
    acwr_info = None
    if history_days >= 21 and chronic4 > 0:
        acwr_info = engine.acwr_status(acute, chronic4)
        if acwr_info:
            acwr_info["acute_load"] = round(acute)
            acwr_info["chronic_weekly_avg"] = round(chronic4)
            acwr_info["note"] = ("Akuutti = viimeisen 7 pv kuorma (rauta-kg + kardio), "
                                 "krooninen = edeltävien 4 viikon viikkokeskiarvo (pv 7–35). "
                                 "Optimi ~0.8–1.3; yli 1.5 = äkillinen kuormapiikki.")
    elif all_dates:
        acwr_info = {"acwr": None, "zone": "keräysvaihe",
                     "note": ("Kuormasuhde (ACWR) lasketaan kun treenihistoriaa on "
                              "vähintään 3 viikkoa — vertailutaso rakentuu vielä.")}
    acwr = acwr_info["acwr"] if acwr_info else None

    # Treenifiilis (huono hymiö) viim. 14 pv — auttaa kun muuta dataa on vähän
    recent_feel = [s.feeling for s in workouts
                   if s.feeling and 0 <= (today - s.session_date).days < 14]
    neg_ratio = (sum(1 for f in recent_feel if f == "negative") / len(recent_feel)) if recent_feel else None

    # Ravinnon vajaus viim. 14 pv (vain jos tarpeeksi kirjattuja päiviä)
    nutrition_deficit, nutrition_n = _nutrition_deficit(db, profile_id, today)

    result = engine.readiness(
        hrv_recent, hrv_base, hrv_bn, hrv_rn,
        rhr_recent, rhr_base, rhr_bn, rhr_rn,
        sleep_recent, sleep_n, acwr,
        neg_feeling_ratio=neg_ratio, feeling_n=len(recent_feel),
        nutrition_deficit_pct=nutrition_deficit, nutrition_n=nutrition_n)
    result["acwr"] = acwr_info

    # Lihashuolto (venyttely/foam roll/liikkuvuus) viim. 7 pv -> pieni bonus
    care_acts = ("venyttely", "foam roll", "liikkuvuus", "lämmittely")
    care_n = sum(1 for c in cardio
                 if c.activity in care_acts and 0 <= (today - c.session_date).days < 7)
    if care_n:
        bonus = min(6, care_n * 2)
        result["score"] = min(100, result["score"] + bonus)
        result["factors"].append({"name": "Lihashuolto", "recent": f"{care_n} krt/vk",
                                  "baseline": "2–3 krt/vk", "change_pct": None,
                                  "enough_data": True, "bonus": f"+{bonus}"})
    result["care_sessions_week"] = care_n
    result["has_data"] = bool(result["factors"])

    # Deload-suositus: matalat valmiuspisteet TAI selvä kuormapiikki
    spike = acwr is not None and acwr > 1.5
    low = result["has_data"] and result["score"] < 55
    if spike or low:
        reason = ("kuormapiikki (ACWR " + str(acwr) + ")") if spike else "matalat palautumismittarit"
        result["deload_recommended"] = True
        result["deload_message"] = (
            f"Harkitse kevennysviikkoa — {reason}. Pudota kuormaa ~40–50 % tai sarjoja "
            "puoleen 5–7 päiväksi, pidä liikkeet samoina. Keho palautuu ja tulokset usein hyppäävät kevennyksen jälkeen.")
    else:
        result["deload_recommended"] = False
    return result


def _nutrition_deficit(db: Session, profile_id: int, today: date):
    """Keskimääräinen kalorivajaus (osuus tarpeesta) viim. 14 pv, ja montako
    päivää ruokaa on kirjattu. Vajaus vain jos dataa on tarpeeksi säännöllisesti."""
    logs = (db.query(models.FoodLog)
            .filter(models.FoodLog.profile_id == profile_id,
                    models.FoodLog.entry_date >= today - timedelta(days=13),
                    models.FoodLog.entry_date <= today).all())
    by_date: dict = {}
    for fl in logs:
        by_date[fl.entry_date] = by_date.get(fl.entry_date, 0.0) + (fl.food.kcal * fl.grams / 100.0)
    n = len(by_date)
    if n < 5:
        return None, n
    avg_intake = sum(by_date.values()) / n
    # Karkea tarve: paino * 30 (ei kriittinen tarkkuus, vain vajauksen suunta)
    bw = _latest_bodyweight(db, profile_id) or 75
    need = bw * 32
    deficit = max(0.0, (need - avg_intake) / need)
    return round(deficit, 2), n


@router.get("/train-today")
def train_today(profile_id: int = Query(...), sore: bool = Query(False),
                db: Session = Depends(get_db)):
    """Kannattaako tänään treenata? Arvio kerätystä datasta (valmiuspisteet,
    kuorma, uni) + käyttäjän ilmoitus lihasten kipeydestä. Rehellinen siitä,
    kuinka paljon dataa arvion takana on."""
    rd = readiness(profile_id, db)
    score = rd.get("score", 0)
    has_data = rd.get("has_data", False)

    # Tuoreimmat lihasryhmät: mitä EI ole treenattu lähipäivinä -> ehdotus
    fresh = []
    try:
        from .stats import coverage as _coverage
        cov = _coverage(profile_id, db)
        fresh = [g["group"] for g in cov["groups"]
                 if g["days_since"] is None or g["days_since"] >= 2][:3]
    except Exception:  # noqa: BLE001
        pass

    data_note = None
    if not has_data:
        data_note = ("Palautumisdataa (uni/HRV/leposyke) on vielä vähän — arvio on karkea. "
                     "Kirjaa näitä säännöllisesti, niin arvio tarkentuu.")

    if sore:
        if has_data and score < 55:
            verdict, level = "Lepopäivä tai vain lihashuolto", "rest"
            detail = ("Lihakset kipeät JA palautumismittarit matalalla — keho ei ole valmis. "
                      "Kevyt kävely, venyttely tai foam roll auttaa palautumista enemmän kuin treeni.")
        elif has_data and score >= 75:
            verdict, level = "Voit treenata — eri lihasryhmä", "light"
            detail = ("Palautumismittarit ovat hyvät, joten kipeys on paikallista. Treenaa lihasryhmää "
                      "jota EI kipeytetty" + (f" (esim. {', '.join(fresh)})" if fresh else "") +
                      " tai tee kevyt tekniikkatreeni. Älä kuormita kipeitä lihaksia raskaasti.")
        else:
            verdict, level = "Kevyt treeni eri lihasryhmälle tai lihashuolto", "light"
            detail = ("Lihakset kipeät — jos treenaat, valitse eri lihasryhmä ja kevennä ~20 %. "
                      "Kova kipu = lepoa; lievä jäykkyys usein helpottaa kevyellä liikkeellä.")
    else:
        if has_data and score >= 80:
            verdict, level = "Hyvä päivä treenata", "go"
            detail = ("Keho on palautunut hyvin — voit treenata täysillä. Jos treeni tuntuu helpolta, "
                      "uskalla nostaa painoa: nyt on hyvä päivä progressiolle.")
        elif has_data and score < 55:
            verdict, level = "Kevennä tai lepää", "rest"
            detail = ("Palautumismittarit ovat matalalla vaikka lihakset eivät ole kipeät — kuormitus tai "
                      "univaje painaa. Kevyt treeni (-30 %) tai lepopäivä on parempi sijoitus kuin väkisin veto.")
        else:
            verdict, level = "Treenaa normaalisti", "go"
            detail = "Ei estettä treenille. Kuuntele tuntumaa lämmittelysarjoissa ja säädä sen mukaan."

    return {"verdict": verdict, "level": level, "detail": detail,
            "readiness_score": score if has_data else None,
            "suggest_groups": fresh, "data_note": data_note}


# ---------- Palautumismittarien suunta ja henkilökohtainen taso ----------

# Leposykkeen yleiset tasot (aikuinen, levossa). HRV:lle EI ole yleistä
# asteikkoa — se on hyvin yksilöllinen (laite, ikä, genetiikka), joten HRV:tä
# verrataan aina vain omaan pitkän ajan tasoon.
RHR_GENERAL_LEVELS = [
    (50, "urheilijataso"), (60, "erinomainen"), (70, "hyvä"),
    (80, "kohtalainen (koholla)"), (999, "korkea — syytä seurata"),
]


def _median(vals: list[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


@router.get("/insights")
def recovery_insights(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Unen/HRV:n/leposykkeen suunta, oma normaalitaso ja hälytykset.

    Oma normaalitaso = pitkän jakson (7-42 pv) mediaani; siihen verrataan
    tuoretta 7 pv keskiarvoa. Hälytysrajat samat kuin valmiuspisteissä
    (HRV -8 %, leposyke +5 %), ja ne annetaan vain kun dataa on tarpeeksi
    (vähintään 10 pitkän jakson ja 3 tuoreen jakson havaintoa).
    """
    today = date.today()
    entries = (db.query(models.BodyEntry)
               .filter(models.BodyEntry.profile_id == profile_id)
               .order_by(models.BodyEntry.entry_date).all())

    def _vals(key, d_from, d_to):
        return [getattr(e, key) for e in entries if getattr(e, key) is not None
                and d_from <= (today - e.entry_date).days < d_to]

    metrics = []
    alerts = []
    good = bad = 0

    specs = [
        # (kenttä, nimi, yksikkö, isompi parempi)
        ("hrv", "HRV", "ms", True),
        ("resting_hr", "Leposyke", "bpm", False),
        ("sleep_hours", "Uni", "h", True),
    ]
    for key, label, unit, higher_better in specs:
        base = _vals(key, 7, 42)
        recent = _vals(key, 0, 7)
        if not base and not recent:
            continue
        enough = len(base) >= engine.READINESS_MIN_BASE and len(recent) >= engine.READINESS_MIN_RECENT
        baseline = round(_median(base), 1) if base else None
        recent_avg = round(sum(recent) / len(recent), 1) if recent else None
        change_pct = (round((recent_avg - baseline) / baseline * 100, 1)
                      if (baseline and recent_avg is not None) else None)

        status, note = "neutral", None
        if enough and change_pct is not None:
            if key == "hrv":
                if change_pct <= -8:
                    status = "alert"
                    note = (f"HRV on laskenut {abs(change_pct)} % omasta normaalitasostasi (~{baseline} {unit}) "
                            "— kertynyttä stressiä/väsymystä. Kevennä ja nuku.")
                elif change_pct >= 5:
                    status, note = "good", "HRV omaa tasoa korkeammalla — palautuminen kunnossa."
                else:
                    status, note = "ok", "Omalla normaalitasolla."
            elif key == "resting_hr":
                if change_pct >= 5:
                    status = "alert"
                    note = (f"Leposyke on noussut {change_pct} % omasta tasostasi (~{baseline} {unit}) "
                            "— keho ei ole palautunut (tai alkava sairastuminen).")
                elif change_pct <= -3:
                    status, note = "good", "Leposyke omaa tasoa matalampi — hyvä kunto-/palautumismerkki."
                else:
                    status, note = "ok", "Omalla normaalitasolla."
            else:  # uni
                if recent_avg is not None and recent_avg < 6.5:
                    status, note = "alert", f"Uni jäänyt lyhyeksi (~{recent_avg} h/yö) — tavoittele 7–9 h."
                elif recent_avg is not None and recent_avg >= 7:
                    status, note = "good", "Unimäärä hyvällä tasolla (suositus 7–9 h)."
                else:
                    status, note = "ok", "Hieman alle suosituksen (7–9 h)."
        elif not enough:
            note = "Kerää dataa säännöllisesti, niin oma normaalitaso ja hälytysrajat tarkentuvat."

        # Yleistaso: leposykkeelle on olemassa yleinen asteikko, HRV:lle ei
        general = None
        if key == "resting_hr" and recent_avg is not None:
            general = next(lbl for lim, lbl in RHR_GENERAL_LEVELS if recent_avg < lim)
        elif key == "hrv":
            general = "yksilöllinen — vertaa vain omaan tasoon"
        elif key == "sleep_hours":
            general = "suositus 7–9 h/yö"

        if status == "alert":
            bad += 1
            alerts.append(note)
        elif status == "good":
            good += 1
        metrics.append({
            "key": key, "label": label, "unit": unit,
            "baseline": baseline, "recent": recent_avg, "change_pct": change_pct,
            "n_base": len(base), "n_recent": len(recent), "enough_data": enough,
            "status": status, "note": note, "general_level": general,
            # Hälytysraja näkyviin: mistä lukemasta häly laukeaisi
            "alert_at": (round(baseline * 0.92, 1) if (key == "hrv" and baseline) else
                         round(baseline * 1.05, 1) if (key == "resting_hr" and baseline) else
                         6.5 if key == "sleep_hours" else None),
            "alert_direction": "alle" if higher_better else "yli",
        })

    if not metrics:
        return {"available": False,
                "note": "Kirjaa unta, HRV:tä ja leposykettä Keho-välilehdellä, niin näet suunnan ja oman tasosi."}
    if bad:
        verdict, verdict_label = "declining", "Suunta heikkenevä — kevennä ja panosta uneen"
    elif good >= 2:
        verdict, verdict_label = "improving", "Suunta hyvä — palautuminen toimii"
    elif good:
        verdict, verdict_label = "stable", "Vakaa, osin paranee"
    else:
        verdict, verdict_label = "stable", "Vakaa"
    return {"available": True, "metrics": metrics, "alerts": alerts,
            "verdict": verdict, "verdict_label": verdict_label}
