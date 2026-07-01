"""Edistymiskuvat: päivätyt valokuvat kehon kehityksen seurantaan.

Kuvat vastaanotetaan base64-muodossa (ei erillistä multipart-riippuvuutta),
tallennetaan levylle data/photos ja tarjoillaan takaisin kuvana.
"""
import base64
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import PHOTOS_DIR, get_db

router = APIRouter(prefix="/api/photos", tags=["photos"])

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class PhotoIn(BaseModel):
    entry_date: date | None = None
    image_base64: str            # muodossa "data:image/jpeg;base64,...." tai pelkkä base64
    mime: str | None = None
    notes: str | None = None


@router.get("")
def list_photos(profile_id: int = Query(...), db: Session = Depends(get_db)):
    rows = (db.query(models.ProgressPhoto)
            .filter(models.ProgressPhoto.profile_id == profile_id)
            .order_by(models.ProgressPhoto.entry_date.desc(), models.ProgressPhoto.id.desc()).all())
    return [{"id": p.id, "entry_date": p.entry_date.isoformat(), "notes": p.notes,
             "url": f"/api/photos/{p.id}/image"} for p in rows]


@router.post("", status_code=201)
def create_photo(payload: PhotoIn, profile_id: int = Query(...), db: Session = Depends(get_db)):
    raw = payload.image_base64
    mime = payload.mime
    if raw.startswith("data:"):
        header, _, raw = raw.partition(",")
        if not mime and ";" in header:
            mime = header[5:header.index(";")]
    try:
        data = base64.b64decode(raw)
    except Exception:
        raise HTTPException(status_code=400, detail="Virheellinen kuvadata.")
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Kuva on liian suuri (max 12 MB).")
    ext = _EXT.get(mime or "", ".jpg")
    fname = f"{uuid.uuid4().hex}{ext}"
    (PHOTOS_DIR / fname).write_bytes(data)
    photo = models.ProgressPhoto(
        profile_id=profile_id,
        entry_date=payload.entry_date or date.today(),
        filename=fname,
        notes=payload.notes,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return {"id": photo.id, "entry_date": photo.entry_date.isoformat(),
            "url": f"/api/photos/{photo.id}/image", "notes": photo.notes}


@router.get("/{photo_id}/image")
def get_image(photo_id: int, db: Session = Depends(get_db)):
    photo = db.get(models.ProgressPhoto, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Kuvaa ei löytynyt.")
    path = PHOTOS_DIR / photo.filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Kuvatiedostoa ei löytynyt.")
    return FileResponse(path)


@router.delete("/{photo_id}", status_code=204)
def delete_photo(photo_id: int, db: Session = Depends(get_db)):
    photo = db.get(models.ProgressPhoto, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Kuvaa ei löytynyt.")
    try:
        (PHOTOS_DIR / photo.filename).unlink(missing_ok=True)
    except OSError:
        pass
    db.delete(photo)
    db.commit()
