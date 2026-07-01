"""Varmuuskopio: koko datan vienti ja palautus JSON-muodossa.

Vie kaikki taulut (profiilit, treenit, ohjelmat, keho, ruoka, kardio…) yhteen
tiedostoon, jonka voi tallentaa talteen tai siirtää toiselle koneelle. Palautus
korvaa nykyisen datan varmuuskopiolla. Toimii yleisesti kaikille tauluille
(myös tuleville), koska se nojaa tietokannan skeemaan.
"""
import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import Base, get_db

router = APIRouter(prefix="/api/backup", tags=["backup"])

BACKUP_VERSION = 1


def _serialize(value):
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return value


@router.get("/export")
def export_all(db: Session = Depends(get_db)):
    """Vie kaikki data JSON-muodossa (yksi tiedosto = koko varmuuskopio)."""
    tables = {}
    for table in Base.metadata.sorted_tables:
        rows = db.execute(text(f"SELECT * FROM {table.name}")).mappings().all()
        tables[table.name] = [{k: _serialize(v) for k, v in row.items()} for row in rows]
    return {
        "version": BACKUP_VERSION,
        "created_at": _dt.datetime.utcnow().isoformat(),
        "tables": tables,
    }


@router.post("/import")
def import_all(payload: dict, db: Session = Depends(get_db)):
    """Palauta varmuuskopio: KORVAA nykyisen datan tuodulla. Kaikki taulut
    tyhjennetään ja täytetään varmuuskopiosta (id:t säilyvät -> viitteet ehjät)."""
    if not isinstance(payload, dict) or "tables" not in payload:
        raise HTTPException(status_code=400, detail="Virheellinen varmuuskopiotiedosto.")
    data = payload["tables"]
    ordered = list(Base.metadata.sorted_tables)  # vanhemmat ensin
    valid_names = {t.name for t in ordered}
    for name in data:
        if name not in valid_names:
            raise HTTPException(status_code=400, detail=f"Tuntematon taulu varmuuskopiossa: {name}")

    # Lapset poistetaan ensin (käänteinen järjestys), vanhemmat lisätään ensin
    # -> viite-eheys säilyy ilman FK-pragmojen kikkailua.
    try:
        for table in reversed(ordered):
            db.execute(text(f"DELETE FROM {table.name}"))
        counts = {}
        for table in ordered:
            rows = data.get(table.name, [])
            counts[table.name] = len(rows)
            if not rows:
                continue
            cols = [c.name for c in table.columns]
            for row in rows:
                use = {k: row.get(k) for k in cols if k in row}
                if not use:
                    continue
                keys = ", ".join(use.keys())
                params = ", ".join(f":{k}" for k in use.keys())
                db.execute(text(f"INSERT INTO {table.name} ({keys}) VALUES ({params})"), use)
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Palautus epäonnistui: {e}")
    return {"status": "ok", "restored": counts}
