"""Laitesynkronointi: puhelin ja PC yhdistävät datansa samassa lähiverkossa.

Ei erillistä pilviserveriä — kaksi sovelluskopiota (esim. puhelin ja PC, tai
valmentajan kone ja asiakkaan laite) yhdistävät tietonsa kun ne linkitetään.
Yhdistäminen on ADDITIIVINEN: jäljessä oleva laite saa puuttuvat treenit,
merkinnät ja ohjelmat — mitään ei pyyhitä. Kirjasto (liikkeet/ruoat) mäpätään
nimellä, joten laitteiden eri sisäiset id:t eivät haittaa.

Idempotentti: saman datan synkronointi uudelleen ei tuota kaksoiskappaleita.
"""
import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import Base, get_db

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _tables_in_order():
    return list(Base.metadata.sorted_tables)


def _serialize(v):
    if isinstance(v, (_dt.date, _dt.datetime)):
        return v.isoformat()
    return v


def export_bundle(db: Session, profile_id: int | None = None) -> dict:
    """Kokoa siirrettävä paketti (kaikki tai yhden profiilin data + kirjasto)."""
    tables = {}
    for table in _tables_in_order():
        rows = db.execute(text(f"SELECT * FROM {table.name}")).mappings().all()
        data = [{k: _serialize(v) for k, v in row.items()} for row in rows]
        if profile_id is not None and "profile_id" in table.columns:
            data = [r for r in data if r.get("profile_id") == profile_id]
        if profile_id is not None and table.name == "profiles":
            data = [r for r in data if r.get("id") == profile_id]
        tables[table.name] = data
    return {"version": 1, "created_at": _dt.datetime.utcnow().isoformat(), "tables": tables}


# Taulukohtainen yhdistämisstrategia:
#  - "name": kirjasto/profiili -> mäppää nimellä (ei duplikaattia)
#  - "day":  yksi rivi per päivä -> yhdistä päivämäärän mukaan (täytä puuttuvat)
#  - "day_site": yksi per päivä+kohta (mitat)
#  - None:   täysi signatuuri remapatuista sarakkeista (logit, treenit)
_STRATEGY = {
    "exercises": "name", "foods": "name", "profiles": "name",
    "body_entries": "day", "measurements": "day_site",
}
_SKIP = {"forecast_logs"}  # sisäinen, uudelleengeneroituva -> ei synkronoida


def _sig(table_name, row, fk_cols):
    """Rivin signatuuri (jättää id:n ja created_at:n pois; FK:t jo remapattu)."""
    items = []
    for k in sorted(row.keys()):
        if k in ("id", "created_at"):
            continue
        items.append((k, row[k]))
    return (table_name, tuple(items))


def merge_bundle(db: Session, bundle: dict) -> dict:
    """Yhdistä paketti nykyiseen kantaan additiivisesti. Palauttaa lisätyt määrät."""
    data = bundle.get("tables") if isinstance(bundle, dict) else None
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Virheellinen synkronointipaketti.")
    idmap: dict[tuple, int] = {}  # (taulu, etä-id) -> paikallinen id
    added = {}

    def local_fk(target_table, remote_id):
        if remote_id is None:
            return None
        return idmap.get((target_table, remote_id), remote_id)

    for table in _tables_in_order():
        tname = table.name
        if tname in _SKIP:
            continue
        rows = data.get(tname, [])
        cols = [c.name for c in table.columns]
        fk_cols = {c.name: list(c.foreign_keys)[0].column.table.name
                   for c in table.columns if c.foreign_keys}
        strat = _STRATEGY.get(tname)
        added[tname] = 0

        # Esilaske paikalliset signatuurit/avaimet
        local_by_name, local_by_day, local_by_daysite, local_sigs = {}, {}, {}, {}
        local_rows = db.execute(text(f"SELECT * FROM {tname}")).mappings().all()
        for lr in local_rows:
            lr = dict(lr)
            if strat == "name":
                local_by_name[str(lr.get("name", "")).lower()] = lr["id"]
            elif strat == "day":
                local_by_day[(lr.get("profile_id"), str(lr.get("entry_date")))] = lr
            elif strat == "day_site":
                local_by_daysite[(lr.get("profile_id"), str(lr.get("entry_date")), lr.get("site"))] = lr["id"]
            else:
                rr = {k: lr[k] for k in cols}
                local_sigs[_sig(tname, rr, fk_cols)] = lr["id"]

        for row in rows:
            # Remap FK:t paikallisiksi
            newrow = {}
            for c in cols:
                if c == "id":
                    continue
                v = row.get(c)
                if c in fk_cols:
                    v = local_fk(fk_cols[c], v)
                newrow[c] = v

            if strat == "name":
                key = str(newrow.get("name", "")).lower()
                if key in local_by_name:
                    idmap[(tname, row["id"])] = local_by_name[key]
                    continue
            elif strat == "day":
                key = (newrow.get("profile_id"), str(newrow.get("entry_date")))
                if key in local_by_day:
                    # Täytä puuttuvat kentät olemassa olevaan päivämerkintään
                    ex = local_by_day[key]
                    fills = {c: newrow[c] for c in cols
                             if c not in ("id", "created_at") and ex.get(c) in (None, "")
                             and newrow.get(c) not in (None, "")}
                    if fills:
                        sets = ", ".join(f"{c} = :{c}" for c in fills)
                        db.execute(text(f"UPDATE {tname} SET {sets} WHERE id = :id"),
                                   {**fills, "id": ex["id"]})
                    idmap[(tname, row["id"])] = ex["id"]
                    continue
            elif strat == "day_site":
                key = (newrow.get("profile_id"), str(newrow.get("entry_date")), newrow.get("site"))
                if key in local_by_daysite:
                    idmap[(tname, row["id"])] = local_by_daysite[key]
                    continue
            else:
                sig = _sig(tname, {**newrow, "id": None}, fk_cols)
                if sig in local_sigs:
                    idmap[(tname, row["id"])] = local_sigs[sig]
                    continue

            # Lisää uusi rivi
            keys = ", ".join(newrow.keys())
            params = ", ".join(f":{k}" for k in newrow.keys())
            res = db.execute(text(f"INSERT INTO {tname} ({keys}) VALUES ({params})"), newrow)
            new_id = res.lastrowid
            idmap[(tname, row["id"])] = new_id
            added[tname] += 1
            if strat == "day":
                local_by_day[(newrow.get("profile_id"), str(newrow.get("entry_date")))] = {**newrow, "id": new_id}
            elif strat == "day_site":
                local_by_daysite[(newrow.get("profile_id"), str(newrow.get("entry_date")), newrow.get("site"))] = new_id
            elif strat == "name":
                local_by_name[str(newrow.get("name", "")).lower()] = new_id
            else:
                local_sigs[_sig(tname, {**newrow, "id": None}, fk_cols)] = new_id

    db.commit()
    total = sum(added.values())
    return {"added_total": total, "added": {k: v for k, v in added.items() if v}}


@router.get("/export")
def sync_export(profile_id: int | None = None, db: Session = Depends(get_db)):
    """Vie koko data (tai yksi profiili) synkronointia varten."""
    return export_bundle(db, profile_id)


@router.post("/merge")
def sync_merge(bundle: dict, db: Session = Depends(get_db)):
    """Yhdistä saatu paketti tähän laitteeseen (additiivinen, ei pyyhi)."""
    return merge_bundle(db, bundle)


class PullIn(BaseModel):
    url: str          # toisen laitteen osoite, esim. http://192.168.1.20:8000
    profile_id: int | None = None
    push_back: bool = True   # lähetä myös oma data takaisin -> molemmat täsmää


@router.post("/pull")
def sync_pull(payload: PullIn, db: Session = Depends(get_db)):
    """Hae toisen laitteen data ja yhdistä (valinnaisesti myös takaisin, jolloin
    molemmat laitteet päätyvät samaan tilaan). Laitteet samassa lähiverkossa."""
    # httpx tuodaan vasta tässä, jotta sovellus käynnistyy vaikka pakettia ei
    # olisi asennettu. Vain automaattinen laitehaku tarvitsee sen — manuaalinen
    # Vie/Yhdistä-synkronointi (QR) toimii ilmankin.
    try:
        import httpx
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail=("Automaattinen laitehaku vaatii httpx-paketin. Asenna: "
                    "pip install httpx — tai käytä manuaalista Vie/Yhdistä-synkronointia."))
    base = payload.url.rstrip("/")
    q = f"?profile_id={payload.profile_id}" if payload.profile_id is not None else ""
    try:
        with httpx.Client(timeout=30.0) as client:
            remote = client.get(f"{base}/api/sync/export{q}").json()
            result = merge_bundle(db, remote)
            pushed = None
            if payload.push_back:
                mine = export_bundle(db, payload.profile_id)
                r = client.post(f"{base}/api/sync/merge", json=mine)
                pushed = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"Yhteys toiseen laitteeseen epäonnistui: {e}")
    return {"pulled": result, "pushed": pushed,
            "message": ("Synkronointi valmis — laitteet ovat nyt samassa tilassa."
                        if payload.push_back else "Data haettu ja yhdistetty tähän laitteeseen.")}
