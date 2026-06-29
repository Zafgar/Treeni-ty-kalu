"""Kehon seuranta: paino, rasva-%, hyvinvointi (uni/HRV/syke/kcal) ja
ympärysmitat. Sisältää kehon koostumusarvion ja aikasarjat graafeja varten.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import engine, models, schemas
from ..database import get_db

router = APIRouter(prefix="/api/body", tags=["body"])


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
    if latest_w and latest_bf:
        height = profile.height_cm if profile else None
        composition = engine.body_composition(latest_w.bodyweight, latest_bf.body_fat_pct, height)
        composition["bodyweight"] = latest_w.bodyweight
        composition["body_fat_pct"] = latest_bf.body_fat_pct
        # Fysiikkataso (aloittelija → IFBB Pro) FFMI:stä
        physique = engine.physique_level(composition.get("ffmi"), profile.sex if profile else None)

    # Mitta-aikasarjat kohdittain
    measurements = (
        db.query(models.Measurement)
        .filter(models.Measurement.profile_id == profile_id)
        .order_by(models.Measurement.entry_date)
        .all()
    )
    by_site: dict[str, list[dict]] = {}
    for m in measurements:
        by_site.setdefault(m.site, []).append({"date": m.entry_date.isoformat(), "value": m.value_cm})

    return {
        "weight_series": weight_series,
        "body_fat_series": bf_series,
        "composition": composition,
        "physique": physique,
        "measurement_sites": by_site,
    }
