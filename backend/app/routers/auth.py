"""Profiililukko: valinnainen pääsynhallinta yhteiskäyttöiselle instanssille.

Kun PT (admin) asettaa admin-PINin, lukko menee päälle:
  - admin (PT) näkee ja hallinnoi kaikkia profiileja,
  - tavallinen käyttäjä pääsee vain omaan profiiliinsa (oma PIN),
  - tarkoitus ennen kaikkea: kukaan ei vahingossa kirjaa väärälle profiilille.

Ennen admin-PINin asettamista lukko on POIS päältä eikä mikään muutu — paikallinen
yksinkäyttö toimii kuten ennen. Tokenit ja PINit hoituvat pelkällä stdlibillä
(katso security.py).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, security
from ..database import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

ADMIN_KEY = "admin_pin_hash"
SECRET_KEY = "token_secret"


def _get_setting(db: Session, key: str) -> str | None:
    row = db.get(models.AppSetting, key)
    return row.value if row else None


def _set_setting(db: Session, key: str, value: str | None) -> None:
    row = db.get(models.AppSetting, key)
    if row is None:
        row = models.AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


def get_secret(db: Session) -> str:
    """Token-allekirjoitusavain kannasta; luodaan kerran jos puuttuu."""
    secret = _get_setting(db, SECRET_KEY)
    if not secret:
        secret = security.new_secret()
        _set_setting(db, SECRET_KEY, secret)
    return secret


def lock_enabled(db: Session) -> bool:
    """Lukko on päällä vain jos admin-PIN on asetettu."""
    return bool(_get_setting(db, ADMIN_KEY))


def current_payload(db: Session, request: Request) -> dict | None:
    """Lue ja vahvista pyynnön Authorization: Bearer -token."""
    auth = request.headers.get("authorization", "")
    token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    return security.read_token(get_secret(db), token)


def require_admin(request: Request, db: Session) -> None:
    payload = current_payload(db, request)
    if not payload or payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Vaatii admin-oikeudet.")


# --- Skeemat ---------------------------------------------------------------

class SetupIn(BaseModel):
    admin_pin: str


class LoginIn(BaseModel):
    mode: str  # "admin" | "profile"
    profile_id: int | None = None
    pin: str | None = None


class ProfilePinIn(BaseModel):
    profile_id: int
    pin: str | None = None  # tyhjä/None poistaa profiilin PINin


# --- Reitit ----------------------------------------------------------------

@router.get("/status")
def status(db: Session = Depends(get_db)):
    """Kertoo onko lukko päällä ja listaa profiilit (nimi + onko PIN).
    Lukitusnäyttö käyttää tätä: käyttäjä valitsee profiilinsa ja syöttää PINin."""
    enabled = lock_enabled(db)
    profiles = db.query(models.Profile).order_by(models.Profile.name).all()
    return {
        "enabled": enabled,
        "profiles": [
            {"id": p.id, "name": p.name, "has_pin": bool(p.pin_hash)}
            for p in profiles
        ],
    }


@router.post("/setup")
def setup(payload: SetupIn, db: Session = Depends(get_db)):
    """Aseta admin-PIN ja ota lukko käyttöön. Sallittu vain kun lukkoa ei vielä
    ole (muuten käytä profiili-PINien hallintaa admin-tokenilla)."""
    if lock_enabled(db):
        raise HTTPException(status_code=400, detail="Lukko on jo käytössä.")
    pin = (payload.admin_pin or "").strip()
    if len(pin) < 4:
        raise HTTPException(status_code=400, detail="Admin-PINin oltava vähintään 4 merkkiä.")
    _set_setting(db, ADMIN_KEY, security.hash_pin(pin))
    secret = get_secret(db)
    return {"token": security.make_token(secret, role="admin", profile_id=None), "role": "admin"}


@router.post("/login")
def login(payload: LoginIn, db: Session = Depends(get_db)):
    """Kirjaudu adminina (koko instanssi) tai profiilina (vain oma profiili)."""
    if not lock_enabled(db):
        raise HTTPException(status_code=400, detail="Lukko ei ole käytössä.")
    secret = get_secret(db)
    if payload.mode == "admin":
        if not security.verify_pin((payload.pin or "").strip(), _get_setting(db, ADMIN_KEY)):
            raise HTTPException(status_code=401, detail="Väärä admin-PIN.")
        return {"token": security.make_token(secret, role="admin", profile_id=None),
                "role": "admin", "profile_id": None}

    if payload.mode == "profile":
        p = db.get(models.Profile, payload.profile_id) if payload.profile_id else None
        if not p:
            raise HTTPException(status_code=404, detail="Profiilia ei löytynyt.")
        # Jos profiililla on PIN, se vaaditaan. Jos ei, profiili on avoin
        # (PT voi jättää PINin asettamatta osalle).
        if p.pin_hash and not security.verify_pin((payload.pin or "").strip(), p.pin_hash):
            raise HTTPException(status_code=401, detail="Väärä PIN.")
        return {"token": security.make_token(secret, role="profile", profile_id=p.id),
                "role": "profile", "profile_id": p.id}

    raise HTTPException(status_code=400, detail="Tuntematon kirjautumistapa.")


@router.post("/profile-pin")
def set_profile_pin(payload: ProfilePinIn, request: Request, db: Session = Depends(get_db)):
    """Aseta tai poista profiilin PIN (vain admin)."""
    require_admin(request, db)
    p = db.get(models.Profile, payload.profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profiilia ei löytynyt.")
    pin = (payload.pin or "").strip()
    if pin:
        if len(pin) < 4:
            raise HTTPException(status_code=400, detail="PINin oltava vähintään 4 merkkiä.")
        p.pin_hash = security.hash_pin(pin)
    else:
        p.pin_hash = None
    db.commit()
    return {"profile_id": p.id, "has_pin": bool(p.pin_hash)}


@router.post("/change-admin-pin")
def change_admin_pin(payload: SetupIn, request: Request, db: Session = Depends(get_db)):
    """Vaihda admin-PIN (vain admin)."""
    require_admin(request, db)
    pin = (payload.admin_pin or "").strip()
    if len(pin) < 4:
        raise HTTPException(status_code=400, detail="Admin-PINin oltava vähintään 4 merkkiä.")
    _set_setting(db, ADMIN_KEY, security.hash_pin(pin))
    return {"ok": True}


@router.post("/disable")
def disable(request: Request, db: Session = Depends(get_db)):
    """Poista lukko käytöstä (vain admin): tyhjentää admin-PINin ja kaikki
    profiili-PINit. Instanssi palaa avoimeen yksinkäyttöön."""
    require_admin(request, db)
    _set_setting(db, ADMIN_KEY, None)
    for p in db.query(models.Profile).all():
        p.pin_hash = None
    db.commit()
    return {"enabled": False}
