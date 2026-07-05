"""Yhteisö-välilehti: PT-viesti, jäsenet ja Hall of Fame.

Tämä on tarkoituksella JAETTU näkymä: kaikki sovelluksen käyttäjät näkevät
toistensa perustiedot (nimi, ikä, treenikerrat, liittynyt) ja jaetut
saavutukset. Yksityinen data (treenit, ruoka, mitat) pysyy silti profiililukon
takana — täällä näytetään vain se, minkä kukin haluaa jakaa.

Roolit:
  - admin (PT): asettaa PT-viestin, voi piilottaa/poistaa mitä tahansa.
  - käyttäjä: näkee kaikki, voi jakaa omia saavutuksiaan ja oman statusrivinsä.
Kun profiililukko ei ole päällä (paikallinen yksinkäyttö), käyttäjä on admin.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import engine, models
from ..database import get_db
from . import auth

router = APIRouter(prefix="/api/community", tags=["community"])

PT_MESSAGE_KEY = "pt_message"


def _viewer(db: Session, request: Request) -> tuple[str, int | None]:
    """Palauttaa (role, profile_id). Ilman lukkoa katsoja on admin."""
    if not auth.lock_enabled(db):
        return "admin", None
    payload = auth.current_payload(db, request)
    if not payload:
        return "guest", None
    return payload.get("role", "guest"), payload.get("pid")


def _require_admin(db: Session, request: Request) -> None:
    role, _ = _viewer(db, request)
    if role != "admin":
        raise HTTPException(status_code=403, detail="Vaatii admin-oikeudet.")


class PTMessageIn(BaseModel):
    message: str | None = None


class HallIn(BaseModel):
    profile_id: int
    title: str
    body: str | None = None


class HallPatchIn(BaseModel):
    hidden: bool | None = None
    pinned: bool | None = None


class PublicNoteIn(BaseModel):
    profile_id: int
    note: str | None = None
    hide_from_community: bool | None = None


def _member_row(db: Session, p: models.Profile) -> dict:
    workouts = (db.query(models.WorkoutSession)
                .filter(models.WorkoutSession.profile_id == p.id,
                        models.WorkoutSession.status == "completed").count())
    last = (db.query(models.WorkoutSession)
            .filter(models.WorkoutSession.profile_id == p.id)
            .order_by(models.WorkoutSession.session_date.desc()).first())
    return {
        "id": p.id, "name": p.name, "color": p.color,
        "age": engine.age_from_birthdate(p.birthdate, date.today()),
        "sex": p.sex,
        "workouts": workouts,
        "joined": p.created_at.date().isoformat() if p.created_at else None,
        "last_workout": last.session_date.isoformat() if last and last.session_date else None,
        "public_note": p.public_note,
    }


@router.get("/overview")
def overview(request: Request, db: Session = Depends(get_db)):
    """Yhteisönäkymä: PT-viesti, jäsenet ja Hall of Fame. Näkyy kaikille
    kirjautuneille (ei sidottu omaan profiiliin — tämä on jaettu näkymä)."""
    role, pid = _viewer(db, request)
    is_admin = role == "admin"

    pt_row = db.get(models.AppSetting, PT_MESSAGE_KEY)
    pt_message = pt_row.value if pt_row else None
    pt_at = pt_row.updated_at.isoformat() if pt_row and pt_row.updated_at else None

    members = [
        _member_row(db, p)
        for p in db.query(models.Profile).order_by(models.Profile.name).all()
        # Piiloutuneet eivät näy muille, mutta admin ja oma profiili näkevät itsensä.
        if is_admin or not p.hide_from_community or p.id == pid
    ]

    hof_q = db.query(models.HallOfFameEntry)
    if not is_admin:
        hof_q = hof_q.filter(models.HallOfFameEntry.hidden.is_(False))
    hof = hof_q.order_by(models.HallOfFameEntry.pinned.desc(),
                         models.HallOfFameEntry.created_at.desc()).all()
    names = {p.id: p.name for p in db.query(models.Profile).all()}
    colors = {p.id: p.color for p in db.query(models.Profile).all()}
    hall = [
        {
            "id": e.id, "profile_id": e.profile_id,
            "author": names.get(e.profile_id, "?"), "color": colors.get(e.profile_id),
            "title": e.title, "body": e.body,
            "hidden": e.hidden, "pinned": e.pinned,
            "created_at": e.created_at.date().isoformat() if e.created_at else None,
            "can_edit": is_admin or e.profile_id == pid,
        }
        for e in hof
    ]
    return {
        "role": role, "profile_id": pid, "is_admin": is_admin,
        "pt_message": pt_message, "pt_message_at": pt_at,
        "members": members, "hall_of_fame": hall,
    }


@router.post("/pt-message")
def set_pt_message(payload: PTMessageIn, request: Request, db: Session = Depends(get_db)):
    """Aseta tai tyhjennä PT-viesti (vain admin)."""
    _require_admin(db, request)
    row = db.get(models.AppSetting, PT_MESSAGE_KEY)
    msg = (payload.message or "").strip() or None
    if row is None:
        row = models.AppSetting(key=PT_MESSAGE_KEY, value=msg)
        db.add(row)
    else:
        row.value = msg
        from datetime import datetime
        row.updated_at = datetime.utcnow()
    db.commit()
    return {"pt_message": msg}


@router.post("/hall", status_code=201)
def add_hall(payload: HallIn, request: Request, db: Session = Depends(get_db)):
    """Jaa saavutus Hall of Fameen. Käyttäjä jakaa omalla profiilillaan
    (profiililukko varmistaa ettei toisen nimissä voi jakaa)."""
    p = db.get(models.Profile, payload.profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profiilia ei löytynyt.")
    title = (payload.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Otsikko puuttuu.")
    e = models.HallOfFameEntry(profile_id=p.id, title=title,
                               body=(payload.body or "").strip() or None)
    db.add(e)
    db.commit()
    db.refresh(e)
    return {"id": e.id}


@router.patch("/hall/{entry_id}")
def patch_hall(entry_id: int, payload: HallPatchIn, request: Request, db: Session = Depends(get_db)):
    """Piilota tai kiinnitä merkintä (vain admin)."""
    _require_admin(db, request)
    e = db.get(models.HallOfFameEntry, entry_id)
    if not e:
        raise HTTPException(status_code=404, detail="Merkintää ei löytynyt.")
    if payload.hidden is not None:
        e.hidden = payload.hidden
    if payload.pinned is not None:
        e.pinned = payload.pinned
    db.commit()
    return {"id": e.id, "hidden": e.hidden, "pinned": e.pinned}


@router.delete("/hall/{entry_id}", status_code=204)
def delete_hall(entry_id: int, request: Request, db: Session = Depends(get_db)):
    """Poista merkintä: tekijä itse tai admin."""
    e = db.get(models.HallOfFameEntry, entry_id)
    if not e:
        raise HTTPException(status_code=404, detail="Merkintää ei löytynyt.")
    role, pid = _viewer(db, request)
    if role != "admin" and e.profile_id != pid:
        raise HTTPException(status_code=403, detail="Ei oikeutta poistaa tätä.")
    db.delete(e)
    db.commit()


@router.post("/public-note")
def set_public_note(payload: PublicNoteIn, request: Request, db: Session = Depends(get_db)):
    """Aseta oma jaettava statusrivi ja/tai piiloudu yhteisöstä.
    Profiililukko varmistaa että vain oman profiilin voi muokata."""
    p = db.get(models.Profile, payload.profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profiilia ei löytynyt.")
    if payload.note is not None:
        p.public_note = (payload.note or "").strip()[:200] or None
    if payload.hide_from_community is not None:
        p.hide_from_community = payload.hide_from_community
    db.commit()
    return {"public_note": p.public_note, "hide_from_community": p.hide_from_community}
