"""Valmentaja: seuraa kehitystä ja hälyttää ongelmista.

Tarkkailee pääliikkeiden kehitystä ja jos se pysähtyy, tutkii mahdollisia syitä
(uni, paino, palautuminen, kuormitus, volyymi, progressio) ja ehdottaa
korjausliikkeitä. Kaikki huomiot annetaan vain kun dataa on tarpeeksi — muuten
arvaus olisi epäluotettava. Toimii sekä aloittelijalle että kokeneelle.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import engine, models
from ..database import get_db
from .stats import (DEFAULT_WINDOW_DAYS, _exercise_session_points,
                    _latest_bodyweight, _records_for_exercise)

router = APIRouter(prefix="/api/coach", tags=["coach"])


def _avg_body(entries, key, days_from, days_to, today):
    vals = [getattr(e, key) for e in entries if getattr(e, key) is not None
            and days_from <= (today - e.entry_date).days < days_to]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


@router.get("/notices")
def coach_notices(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Palauta valmentajan huomiot (pop-up-tyyliset) prioriteettijärjestyksessä."""
    today = date.today()
    profile = db.get(models.Profile, profile_id)
    sex = profile.sex if profile else None
    bw = _latest_bodyweight(db, profile_id)
    notices = []

    entries = (db.query(models.BodyEntry).filter(models.BodyEntry.profile_id == profile_id)
               .order_by(models.BodyEntry.entry_date).all())
    weight_hist = [(e.entry_date, e.bodyweight) for e in entries if e.bodyweight is not None]
    bw_trend = engine.weight_trend(weight_hist, max(d for d, _ in weight_hist)) if len(weight_hist) >= 2 else None
    sleep_avg, sleep_n = _avg_body(entries, "sleep_hours", 0, 14, today)

    # Onko tavoite voima/massa (vaikuttaa tulkintaan): aktiivisen ohjelman goal
    active_prog = (db.query(models.Program).filter(models.Program.profile_id == profile_id,
                   models.Program.is_active.is_(True)).first())
    goal = (active_prog.goal or "").lower() if active_prog else ""
    strength_focus = any(k in goal for k in ("voima", "voimanosto", "maksimivoima"))

    # ---- Pääliikkeiden pysähtyminen + syyanalyysi ----
    stalled = []
    near_ceiling = []
    for ex in db.query(models.Exercise).filter(models.Exercise.is_main_lift.is_(True)).all():
        points = _exercise_session_points(db, ex.id, profile_id)
        valid = [p for p in points if p["estimated_1rm"] > 0]
        if len(valid) < 4:
            continue  # ei tarpeeksi dataa luotettavaan päätelmään
        span = (valid[-1]["date"] - valid[0]["date"]).days
        if span < 42:
            continue
        # Lähitrendi (viim. ~56 pv)
        base = valid[0]["date"]
        recent = [((p["date"] - base).days, p["estimated_1rm"]) for p in valid
                  if (valid[-1]["date"] - p["date"]).days <= 56]
        if len(recent) < 3:
            continue
        rate_wk = engine._linear_rate(recent) * 7
        last_trained_days = (today - valid[-1]["date"]).days
        if last_trained_days > 28:
            continue  # tauolla -> paluu-logiikka hoitaa (comeback), ei "pysähdys"
        rec = _records_for_exercise(points, DEFAULT_WINDOW_DAYS)
        # Lähellä luonnollista kattoa?
        lk = engine.classify_lift(ex.name)
        ceiling = engine.natural_ceiling(lk, bw, sex) if (lk and bw) else None
        if ceiling and rec and rec["current_1rm"] >= ceiling * 0.92:
            near_ceiling.append(ex.name)
            continue
        if rate_wk < 0.15:  # käytännössä tasaista tai laskua
            stalled.append(ex.name)

    if stalled:
        factors = []
        if sleep_n >= 4 and sleep_avg is not None and sleep_avg < 7:
            factors.append(f"uni on jäänyt lyhyeksi (~{round(sleep_avg,1)} h/yö) — palautuminen kärsii")
        if bw_trend is not None and bw_trend < -0.1 and "cut" not in goal:
            factors.append(f"paino laskee ({bw_trend:+.1f} kg/vk) — voiman kasvu vaatii yleensä riittävästi energiaa ja hieman painoa")
        # Palautuminen / kuormitus
        try:
            from .recovery import readiness as _readiness
            rd = _readiness(profile_id, db)
            if rd.get("has_data") and rd["score"] < 60:
                factors.append("palautumismittarit ovat matalalla (HRV/leposyke/uni/kuorma) — harkitse kevennysviikkoa")
            elif rd.get("acwr") and rd["acwr"]["acwr"] > 1.5:
                factors.append("treenikuorma on piikissä — liiallinen kuormitus voi estää kehityksen")
        except Exception:  # noqa: BLE001
            pass
        # Progressio: eikö painot nouse?
        factors.append("varmista progressio: nosta painoa 1.25–2.5 kg kun sarjat menevät (autoprogressio ohjelmassa auttaa)")

        msg = ("Pääliikkeiden kehitys on pysähtynyt (" + ", ".join(stalled) + "). "
               "Mahdollisia syitä ja korjauksia: " + "; ".join(factors) + ".")
        notices.append({
            "id": "stall", "level": "warn", "category": "kehitys",
            "title": "Kehitys pysähtynyt — tarkista nämä",
            "message": msg,
        })

    if near_ceiling:
        notices.append({
            "id": "ceiling", "level": "info", "category": "kehitys",
            "title": "Lähellä luonnollista kattoa",
            "message": ("Liikkeissä " + ", ".join(near_ceiling) + " olet lähellä naturaalinostajan "
                        "realistista kattoa — kehitys hidastuu tästä eteenpäin, ja se on normaalia. "
                        "Keskity tekniikkaan, apuliikkeisiin ja pitkäjänteisyyteen; parin kilon vuosinousu "
                        "on tällä tasolla hyvä tulos."),
        })

    # ---- Palautuminen: deload ----
    try:
        from .recovery import readiness as _readiness2
        rd = _readiness2(profile_id, db)
        if rd.get("deload_recommended"):
            notices.append({
                "id": "deload", "level": "alert", "category": "palautuminen",
                "title": "Kevennysviikko suositeltu", "message": rd.get("deload_message", ""),
            })
    except Exception:  # noqa: BLE001
        pass

    # ---- Koko kehon kate: puuttuvat lihasryhmät ----
    try:
        from .stats import coverage as _coverage
        cov = _coverage(profile_id, db)
        if cov["missing"]:
            notices.append({
                "id": "coverage", "level": "info", "category": "tasapaino",
                "title": "Osa kehosta jää treenaamatta",
                "message": ("Viimeisen ~10 pv aikana ei ole treenattu: " + ", ".join(cov["missing"]) +
                            ". Lisää nämä ohjelmaan tasapainon ja loukkaantumisten ehkäisyn vuoksi."),
            })
    except Exception:  # noqa: BLE001
        pass

    # ---- Paluu vanhoihin tuloksiin ----
    try:
        from .stats import comeback as _comeback
        cb = _comeback(profile_id, db)
        if cb["comebacks"]:
            top = cb["comebacks"][0]
            notices.append({
                "id": "comeback", "level": "info", "category": "kehitys",
                "title": "Liikkeitä palautettavaksi",
                "message": (f"Et ole tehnyt liikettä {top['exercise_name']} hetkeen (ennätys {top['best_ever_1rm']} kg). "
                            f"Aloita ~{top['suggested_start_kg']} kg — paluu huippuun on nopeaa (lihasmuisti). "
                            "Ks. 'Paluu vanhoihin tuloksiin' Kehitys-välilehdellä."),
            })
    except Exception:  # noqa: BLE001
        pass

    order = {"alert": 0, "warn": 1, "info": 2}
    notices.sort(key=lambda n: order.get(n["level"], 3))
    return {"notices": notices, "count": len(notices)}
