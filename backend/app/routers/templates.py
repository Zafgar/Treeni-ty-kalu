"""Valmiit ohjelmapohjat.

Pohjat rakentavat ohjelman perusparametreista. Voimajaksoissa lähtöpaino
lasketaan prosentteina tämänhetkisestä arvioidusta 1RM:stä (percent_scheme),
joten treenin generointi täyttää painot automaattisesti. Jokainen pohja
sisältää ohjeet (miten ja miksi), jotta käyttäjä tietää miten jakso ajetaan.
Käyttäjä voi myös tehdä täysin omia ohjelmia — pohjat ovat vain lähtökohta.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db

router = APIRouter(prefix="/api/templates", tags=["templates"])


# Jokainen pohja kuvaa treenipäivän liikemallin pääliikkeille.
TEMPLATES = {
    "voima_5x5": {
        "name": "Voima 5×5",
        "goal": "voima",
        "schedule_type": "cycle",
        "rep_scheme": "5,5,5,5,5",
        "percent_scheme": "75,80,82.5,82.5,82.5",
        "rest_seconds": 180,
        "guidance": (
            "Klassinen lineaarinen voimajakso. Tee 5 sarjaa 5 toistoa pääliikkeellä. "
            "Lähtöpaino lasketaan prosentteina tämänhetkisestä arvioidusta 1RM:stä. "
            "MIKSI: matala toistomäärä raskaalla painolla kehittää maksimivoimaa "
            "hermostollisesti. Lisää painoa 2.5 kg kun kaikki 5×5 menee puhtaasti."
        ),
    },
    "maksimivoima_prosentti": {
        "name": "Maksimivoima (prosenttipohjainen)",
        "goal": "maksimivoima",
        "schedule_type": "cycle",
        "rep_scheme": "5,3,2,1",
        "percent_scheme": "80,87.5,92.5,95",
        "rest_seconds": 240,
        "guidance": (
            "Nousujohteinen kuormitus kohti ykkösnostoa. Sarjat kevenevät toistoissa "
            "ja raskenevat painossa (5-3-2-1). MIKSI: valmistaa hermoston maksimaaliseen "
            "ponnistukseen. Aja jakso useita viikkoja ja nosta prosentteja vasta kun "
            "ykkösnosto tuntuu varmalta. Pidä viimeinen sarja 1-2 varastolla (ei reeniin "
            "uupumukseen joka kerta)."
        ),
    },
    "pyramidi_hypertrofia": {
        "name": "Pyramidi (lihasmassa)",
        "goal": "hypertrofia",
        "schedule_type": "cycle",
        "rep_scheme": "12,10,8,6",
        "percent_scheme": "60,67.5,72.5,77.5",
        "rest_seconds": 120,
        "guidance": (
            "Nouseva pyramidi: paino kasvaa ja toistot laskevat (12-10-8-6). "
            "MIKSI: kerää volyymiä useilla toistoalueilla -> hyvä lihaskasvulle. "
            "Tavoittele 1-3 varastoa per sarja. Lisää painoa kun yläpään toistot menevät helposti."
        ),
    },
}


class TemplateBuild(BaseModel):
    template_id: str
    exercise_ids: list[int]
    profile_id: int | None = None
    name: str | None = None
    accessory_ids: list[int] = []  # lisäliikkeet (oletustavoittein)


@router.get("")
def list_templates():
    """Listaa pohjat ohjeineen."""
    return [
        {"id": tid, **{k: v for k, v in t.items()}}
        for tid, t in TEMPLATES.items()
    ]


@router.post("/build")
def build_program(payload: TemplateBuild, db: Session = Depends(get_db)):
    """Rakenna konkreettinen ohjelma pohjasta valituille pääliikkeille."""
    tpl = TEMPLATES.get(payload.template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Pohjaa ei löytynyt.")
    if not payload.exercise_ids:
        raise HTTPException(status_code=400, detail="Valitse vähintään yksi pääliike.")

    program = models.Program(
        name=payload.name or tpl["name"],
        profile_id=payload.profile_id,
        schedule_type=tpl["schedule_type"],
        goal=tpl["goal"],
        description=tpl["guidance"],
        is_active=True,
    )
    # Yksi treenipäivä per pääliike (liike + valinnaiset lisäliikkeet).
    for i, ex_id in enumerate(payload.exercise_ids):
        ex = db.get(models.Exercise, ex_id)
        if not ex:
            continue
        day = models.ProgramDay(order_index=i, day_type="train", label=f"{ex.name}-päivä")
        day.exercises.append(models.ProgramExercise(
            exercise_id=ex_id, order_index=0,
            target_sets=len(tpl["rep_scheme"].split(",")),
            target_reps=int(float(tpl["rep_scheme"].split(",")[0])),
            rep_scheme=tpl["rep_scheme"], percent_scheme=tpl["percent_scheme"],
            rest_seconds=tpl["rest_seconds"], target_rir=2,
            notes=tpl["guidance"],
        ))
        for j, acc_id in enumerate(payload.accessory_ids):
            day.exercises.append(models.ProgramExercise(
                exercise_id=acc_id, order_index=j + 1,
                target_sets=3, target_reps=10, target_rir=2,
            ))
        program.days.append(day)
    db.add(program)
    db.commit()
    db.refresh(program)
    return {"program_id": program.id, "name": program.name}
