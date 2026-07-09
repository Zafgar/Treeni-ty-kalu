"""Kehon seuranta: paino, rasva-%, hyvinvointi (uni/HRV/syke/kcal) ja
ympärysmitat. Sisältää kehon koostumusarvion ja aikasarjat graafeja varten.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import engine, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/body", tags=["body"])


def _area_strength_trend(db: Session, profile_id: int, categories: list[str]) -> float | None:
    """Alueen voimakehitys prosenttia/viikko: mediaani liikkeiden arvioidun 1RM:n
    normalisoidusta tahdista annetuissa kategorioissa. Skaalaton (median % ),
    joten eri painoiset liikkeet (jalkaprässi vs. jalkakoukistus) vertautuvat.
    Positiivinen = alue vahvistuu."""
    from .stats import _exercise_session_points
    exs = (db.query(models.Exercise)
           .filter(models.Exercise.category.in_(categories)).all())
    norm_rates = []
    for ex in exs:
        pts = _exercise_session_points(db, ex.id, profile_id)
        hist = [(p["date"], p["estimated_1rm"]) for p in pts if p["estimated_1rm"] > 0]
        if len(hist) < 2:
            continue
        rate = engine.recent_rate_per_week(hist)
        cur = hist[-1][1]
        if rate is not None and cur > 0:
            norm_rates.append(rate / cur)
    if not norm_rates:
        return None
    norm_rates.sort()
    med = norm_rates[len(norm_rates) // 2]
    return round(med * 100, 2)


@router.get("/measurement-guide")
def measurement_guide():
    """Ohjeet mittaamiseen: milloin, miten ja mistä kohtaa mitataan."""
    return {
        "general": engine.MEASUREMENT_GENERAL_GUIDE,
        "sites": engine.MEASUREMENT_SITE_GUIDE,
        "cadence": "Kerran viikossa riittää — päivittäinen mittaus näyttää vain kohinaa.",
        "weight": ("Punnitse aamulla vessakäynnin jälkeen, ennen syömistä. Käytä 7 päivän "
                   "keskiarvoa: yksittäinen aamu voi heilahtaa 1–1,5 kg pelkästä nesteestä ja ruoasta."),
    }


# ---------- Päiväkohtainen kehodata ----------
@router.get("/entries", response_model=list[schemas.BodyEntryOut])
def list_entries(profile_id: int = Query(...), db: Session = Depends(get_db)):
    return (
        db.query(models.BodyEntry)
        .filter(models.BodyEntry.profile_id == profile_id)
        .order_by(models.BodyEntry.entry_date.desc())
        .all()
    )


@router.post("/entries", response_model=schemas.BodyEntryOut, status_code=201)
def create_entry(profile_id: int, payload: schemas.BodyEntryCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["entry_date"] = data.get("entry_date") or date.today()
    # Kun paino kirjataan ilman rasva-%:a ja laitemittaus (InBody tms.) on
    # olemassa, täytä rasva-% automaattisesti siitä johdettuna arviona.
    # Laiteankkuri ohittaa käsin arvaillut lukemat.
    if data.get("bodyweight") and not data.get("body_fat_pct"):
        est = bia_estimate_for(db, profile_id, data["bodyweight"], data["entry_date"])
        if est:
            data["body_fat_pct"] = est["bf_pct"]
    entry = models.BodyEntry(profile_id=profile_id, **data)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/entries/{entry_id}", response_model=schemas.BodyEntryOut)
def update_entry(entry_id: int, payload: schemas.BodyEntryCreate, db: Session = Depends(get_db)):
    entry = db.get(models.BodyEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Merkintää ei löytynyt.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(entry, key, value)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(models.BodyEntry, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Merkintää ei löytynyt.")
    db.delete(entry)
    db.commit()


# ---------- Ympärysmitat ----------
@router.get("/measurements", response_model=list[schemas.MeasurementOut])
def list_measurements(profile_id: int = Query(...), db: Session = Depends(get_db)):
    return (
        db.query(models.Measurement)
        .filter(models.Measurement.profile_id == profile_id)
        .order_by(models.Measurement.entry_date.desc())
        .all()
    )


@router.post("/measurements", response_model=schemas.MeasurementOut, status_code=201)
def create_measurement(profile_id: int, payload: schemas.MeasurementCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["entry_date"] = data.get("entry_date") or date.today()
    m = models.Measurement(profile_id=profile_id, **data)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.delete("/measurements/{measurement_id}", status_code=204)
def delete_measurement(measurement_id: int, db: Session = Depends(get_db)):
    m = db.get(models.Measurement, measurement_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mittausta ei löytynyt.")
    db.delete(m)
    db.commit()


# ---------- Yhteenveto + koostumus + aikasarjat ----------
@router.get("/summary")
def body_summary(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Viimeisin paino/rasva-%, koostumusarvio ja aikasarjat graafeja varten."""
    profile = db.get(models.Profile, profile_id)
    entries = (
        db.query(models.BodyEntry)
        .filter(models.BodyEntry.profile_id == profile_id)
        .order_by(models.BodyEntry.entry_date)
        .all()
    )
    weight_series = [
        {"date": e.entry_date.isoformat(), "value": e.bodyweight}
        for e in entries if e.bodyweight is not None
    ]
    bf_series = [
        {"date": e.entry_date.isoformat(), "value": e.body_fat_pct}
        for e in entries if e.body_fat_pct is not None
    ]

    # Viimeisin koostumusarvio
    composition = None
    latest_w = next((e for e in reversed(entries) if e.bodyweight is not None), None)
    latest_bf = next((e for e in reversed(entries) if e.body_fat_pct is not None), None)
    physique = None
    height = profile.height_cm if profile else None
    creatine = bool(profile.creatine) if profile else False
    sex = profile.sex if profile else None

    # Rasva-%:n lähdehierarkia: laitemittaus (InBody tms.) ohittaa omat
    # arviot; ilman kumpaakaan arvioidaan ympärysmitoista (Navy-kaava).
    bf_pct = latest_bf.body_fat_pct if latest_bf else None
    bf_estimated = False
    bf_source = "entry" if bf_pct is not None else None
    # Laitemittaus kumoaa käsin syötetyt arviot aina kun sellainen on olemassa
    bia = _latest_bia(db, profile_id)
    if bia:
        est = bia_estimate_for(db, profile_id,
                               latest_w.bodyweight if latest_w else bia.weight_kg)
        if est:
            bf_pct = est["bf_pct"]
            bf_estimated = est["basis"] != "anchor"
            bf_source = "bia"
    if bf_pct is None:
        def _latest_site(site):
            m = (db.query(models.Measurement)
                 .filter(models.Measurement.profile_id == profile_id, models.Measurement.site == site)
                 .order_by(models.Measurement.entry_date.desc()).first())
            return m.value_cm if m else None
        est = engine.body_fat_navy(sex, height, _latest_site("kaula"),
                                   _latest_site("vyötärö"), _latest_site("lantio"))
        if est is not None:
            bf_pct = est
            bf_estimated = True
            bf_source = "navy"

    if latest_w and bf_pct is not None:
        composition = engine.body_composition(latest_w.bodyweight, bf_pct, height, creatine=creatine)
        composition["bodyweight"] = latest_w.bodyweight
        composition["body_fat_pct"] = bf_pct
        composition["body_fat_estimated"] = bf_estimated
        composition["body_fat_source"] = bf_source
        composition["creatine"] = creatine
        # Fysiikkataso (aloittelija → IFBB Pro) FFMI:stä
        physique = engine.physique_level(composition.get("ffmi"), sex)

    # Mitta-aikasarjat kohdittain
    measurements = (
        db.query(models.Measurement)
        .filter(models.Measurement.profile_id == profile_id)
        .order_by(models.Measurement.entry_date)
        .all()
    )
    by_site: dict[str, list[dict]] = {}
    raw_by_site: dict[str, list] = {}
    for m in measurements:
        by_site.setdefault(m.site, []).append({"date": m.entry_date.isoformat(), "value": m.value_cm})
        raw_by_site.setdefault(m.site, []).append((m.entry_date, m.value_cm))

    # Painon ja vyötärön trendit ennusteen tulkintaa varten
    height = profile.height_cm if profile else None
    sex = profile.sex if profile else None
    weight_hist = [(e.entry_date, e.bodyweight) for e in entries if e.bodyweight is not None]
    bw_trend = engine.recent_rate_per_week(weight_hist) if len(weight_hist) >= 2 else None
    waist_trend = (engine.recent_rate_per_week(raw_by_site["vyötärö"])
                   if len(raw_by_site.get("vyötärö", [])) >= 2 else None)

    # Mittojen kasvun/laskun ennuste (omasta historiasta) + tulkinta.
    # Data edellä; pituuspohjainen pehmeä katto/pohja; adaptoituu omaan tahtiin.
    from .stats import _calibration_for_key, _snapshot_forecast
    measurement_forecasts: dict[str, list] = {}
    measurement_insights: dict[str, dict] = {}
    cur_weight = latest_w.bodyweight if latest_w else None
    for site, hist in raw_by_site.items():
        conf = engine.forecast_confidence(len(hist), (hist[-1][0] - hist[0][0]).days)
        ceiling = engine.measurement_ceiling(site, height, sex)
        floor = engine.measurement_floor(site, height)
        calib = _calibration_for_key(db, profile_id, "measurement", site, hist)
        fc = engine.forecast_measurement(
            hist, 52, conf, ceiling=ceiling, floor=floor, rate_calibration=calib,
            bodyweight_trend_per_week=bw_trend or 0.0, bodyweight=cur_weight,
            body_fat_pct=bf_pct, site=site)
        if fc:
            measurement_forecasts[site] = fc
            _snapshot_forecast(db, profile_id, "measurement", site, hist[-1][1], fc)
        rate = engine.recent_rate_per_week(hist)
        current = hist[-1][1]
        note = engine.measurement_insight(site, rate, current, ceiling, bw_trend, waist_trend)
        # Kohina-/kadenssitietoinen suunta (ei säikäytä yksittäisistä muutoksista)
        reading = engine.measurement_reading(site, hist)
        # Voima–koko-yhteys: vahvistuuko alue samalla kun mitta muuttuu?
        strength_link = None
        link = engine.SITE_TRAINING_LINK.get(site)
        if link and reading and reading["status"] != "need_more":
            friendly, cats = link
            st = _area_strength_trend(db, profile_id, cats)
            strength_link = engine.strength_measurement_link(site, reading["status"], st, friendly)
        if note or ceiling or reading:
            measurement_insights[site] = {
                "note": note, "ceiling": ceiling, "current": current,
                "rate_per_week": round(rate, 2) if rate is not None else None,
                "reading": reading, "strength_link": strength_link,
            }

    # Painon opastus: 7 pv keskiarvo + luonnollinen heilahtelu (ei säikäytetä
    # yksittäisestä aamupainosta) + suunta vasta kun dataa on tarpeeksi.
    weight_guidance = None
    if weight_hist:
        wsorted = sorted(weight_hist, key=lambda p: p[0])
        latest_date = wsorted[-1][0]
        avg7 = engine.weekly_average(wsorted, latest_date, 7)
        n_w = len(wsorted)
        direction = None
        if bw_trend is not None and n_w >= 4:
            if abs(bw_trend) < 0.1:
                direction = "vakaa"
            elif bw_trend > 0:
                direction = f"nousee ~{round(bw_trend, 2)} kg/vk"
            else:
                direction = f"laskee ~{round(abs(bw_trend), 2)} kg/vk"
        weight_guidance = {
            "avg7": avg7, "latest": round(wsorted[-1][1], 1),
            "trend_kg_per_week": round(bw_trend, 2) if bw_trend is not None else None,
            "noise_band_kg": engine.WEIGHT_NOISE_KG, "direction": direction,
            "enough_data": n_w >= 4,
            "message": ("Seuraa 7 päivän keskiarvoa, ei yksittäistä aamua. Paino voi heilahtaa "
                        f"±{engine.WEIGHT_NOISE_KG} kg pelkästä nesteestä, suolasta ja ruoasta — se ei ole rasvaa. "
                        "Punnitse aamulla vessakäynnin jälkeen, ennen syömistä."),
        }

    return {
        "weight_series": weight_series,
        "body_fat_series": bf_series,
        "composition": composition,
        "physique": physique,
        "height_cm": height,
        "sex": sex,
        "creatine": bool(profile.creatine) if profile else False,
        "measurement_sites": by_site,
        "measurement_forecasts": measurement_forecasts,
        "measurement_insights": measurement_insights,
        "weight_guidance": weight_guidance,
    }


# ---------- BIA-kehonkoostumusmittaus (InBody tms.) ----------
def _latest_bia(db: Session, profile_id: int) -> models.BiaMeasurement | None:
    return (db.query(models.BiaMeasurement)
            .filter(models.BiaMeasurement.profile_id == profile_id)
            .order_by(models.BiaMeasurement.entry_date.desc(),
                      models.BiaMeasurement.id.desc())
            .first())


def _waist_near(db: Session, profile_id: int, target: date, max_days: int = 21) -> float | None:
    """Vyötärömitta lähimpänä annettua päivää (±max_days)."""
    rows = (db.query(models.Measurement)
            .filter(models.Measurement.profile_id == profile_id,
                    models.Measurement.site == "vyötärö").all())
    best, best_gap = None, max_days + 1
    for m in rows:
        gap = abs((m.entry_date - target).days)
        if gap < best_gap:
            best, best_gap = m.value_cm, gap
    return best


def bia_estimate_for(db: Session, profile_id: int, weight: float | None,
                     on_date: date | None = None) -> dict | None:
    """BIA-ankkuroitu rasva-%-arvio annetulle painolle/päivälle."""
    bia = _latest_bia(db, profile_id)
    if not bia:
        return None
    on_date = on_date or date.today()
    profile = db.get(models.Profile, profile_id)
    sex = profile.sex if profile else None
    anchor_w = bia.weight_kg
    if anchor_w is None:
        # Laitteen painoa ei kirjattu -> käytä lähintä omaa painokirjausta
        e = (db.query(models.BodyEntry)
             .filter(models.BodyEntry.profile_id == profile_id,
                     models.BodyEntry.bodyweight.isnot(None))
             .order_by(models.BodyEntry.entry_date.desc(),
                       models.BodyEntry.id.desc()).first())
        anchor_w = e.bodyweight if e else None
    waist_anchor = _waist_near(db, profile_id, bia.entry_date)
    waist_now = _waist_near(db, profile_id, on_date)
    waist_delta = (waist_now - waist_anchor) if (waist_anchor is not None and waist_now is not None
                                                 and waist_anchor != waist_now) else (
        0.0 if (waist_anchor is not None and waist_now is not None) else None)
    est = engine.bf_from_bia_anchor(bia.body_fat_pct, anchor_w, weight, waist_delta, sex)
    if not est:
        return None
    days_since = (on_date - bia.entry_date).days
    basis_txt = {"anchor": "suoraan laitemittauksesta",
                 "weight": "painonmuutoksesta",
                 "waist": "vyötärönmuutoksesta",
                 "weight+waist": "painon ja vyötärön muutoksesta"}[est["basis"]]
    return {
        **est,
        "anchor_date": bia.entry_date.isoformat(),
        "anchor_bf_pct": bia.body_fat_pct,
        "anchor_weight": anchor_w,
        "days_since_anchor": days_since,
        "waist_delta_cm": round(waist_delta, 1) if waist_delta is not None else None,
        "note": (f"Arvio johdettu {bia.entry_date.isoformat()} laitemittauksesta "
                 f"({bia.body_fat_pct} %) {basis_txt}." +
                 (" Mittaus alkaa olla vanha — uusi laitemittaus tarkentaisi."
                  if days_since > 120 else "")),
    }


@router.get("/bia", response_model=list[schemas.BiaOut])
def list_bia(profile_id: int = Query(...), db: Session = Depends(get_db)):
    return (db.query(models.BiaMeasurement)
            .filter(models.BiaMeasurement.profile_id == profile_id)
            .order_by(models.BiaMeasurement.entry_date.desc()).all())


@router.post("/bia", response_model=schemas.BiaOut, status_code=201)
def create_bia(profile_id: int, payload: schemas.BiaCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["entry_date"] = data.get("entry_date") or date.today()
    m = models.BiaMeasurement(profile_id=profile_id, **data)
    db.add(m)
    # Laitemittaus ohittaa omat arviot: päivitä saman päivän (tai uudempien
    # ilman uudempaa laitemittausta olevien) kirjausten rasva-% laitteen mukaan.
    same_day = (db.query(models.BodyEntry)
                .filter(models.BodyEntry.profile_id == profile_id,
                        models.BodyEntry.entry_date == data["entry_date"]).first())
    if same_day:
        same_day.body_fat_pct = data["body_fat_pct"]
        if data.get("weight_kg") and not same_day.bodyweight:
            same_day.bodyweight = data["weight_kg"]
    db.commit()
    db.refresh(m)
    return m


@router.delete("/bia/{bia_id}", status_code=204)
def delete_bia(bia_id: int, db: Session = Depends(get_db)):
    m = db.get(models.BiaMeasurement, bia_id)
    if not m:
        raise HTTPException(status_code=404, detail="Mittausta ei löytynyt.")
    db.delete(m)
    db.commit()


@router.get("/bia/estimate")
def bia_estimate(profile_id: int = Query(...), weight: float | None = Query(None),
                 db: Session = Depends(get_db)):
    """Tämänhetkinen rasva-%-arvio viimeisimmästä laitemittauksesta johdettuna."""
    w = weight
    if w is None:
        e = (db.query(models.BodyEntry)
             .filter(models.BodyEntry.profile_id == profile_id,
                     models.BodyEntry.bodyweight.isnot(None))
             .order_by(models.BodyEntry.entry_date.desc(),
                       models.BodyEntry.id.desc()).first())
        w = e.bodyweight if e else None
    est = bia_estimate_for(db, profile_id, w)
    if not est:
        return {"available": False,
                "note": "Ei laitemittauksia — kirjaa InBody-tyyppinen mittaus, niin "
                        "rasva-%-arvio ankkuroituu siihen."}
    return {"available": True, "weight": w, **est}
