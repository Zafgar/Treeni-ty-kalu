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
    "huippuunajo": {
        "name": "Huippuunajo (peaking)",
        "goal": "maksimivoima",
        "schedule_type": "cycle",
        "rep_scheme": "3,2,1,1",
        "percent_scheme": "85,90,95,100",
        "rest_seconds": 300,
        "guidance": (
            "Lyhyt huippuunajo ennen testiä tai kisaa. Sarjat nousevat aina "
            "ykkösnostoon (jopa 100 % nykyisestä arvioidusta 1RM:stä). MIKSI: terävöittää "
            "hermoston maksimisuoritukseen. Käytä vain 1-3 viikkoa, lepää hyvin ja "
            "vähennä apuliikkeiden määrää tällä jaksolla."
        ),
    },
    "volyymivoima_6x6": {
        "name": "Volyymivoima 6×6",
        "goal": "voima",
        "schedule_type": "cycle",
        "rep_scheme": "6,6,6,6,6,6",
        "percent_scheme": "72,72,72,72,72,72",
        "rest_seconds": 150,
        "guidance": (
            "Kuusi tasaista sarjaa kohtuukuormalla (~72 % 1RM). MIKSI: kerää paljon "
            "laadukasta volyymiä voiman ja lihasmassan pohjaksi ilman jatkuvaa "
            "uupumista. Hyvä perusjakso ennen raskaampia voimajaksoja. Lisää painoa "
            "kun kaikki 6×6 menee 1-2 varastolla."
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


# =================== KOKO-OHJELMAN GENERAATTORI ===================
# Valitse laji + treenikerrat/viikko -> järjestelmä rakentaa valmiin
# viikko-ohjelman liikkeineen (haetaan kirjastosta) ja sarjoineen.
# Pääliikkeissä on percent_scheme -> painot lasketaan 1RM:stä automaattisesti.

# Päivämallit. main = pääliike percent_schemellä, acc = lisäliike (kategoria).
def _M(name, sets, reps_scheme, pct):
    return {"name": name, "sets": sets, "rep_scheme": reps_scheme, "percent_scheme": pct}


def _A(name, sets, reps):
    return {"name": name, "sets": sets, "reps": reps}


_PUSH = {"label": "Työntö (rinta/olka/ojentaja)", "items": [
    _M("penkkipunnerrus", 4, "6,6,6,6", "72,75,77,77"),
    _A("vinopenkki", 3, 10), _A("pystypunnerrus", 3, 10),
    _A("sivunostot", 3, 15), _A("taljapunnerrus", 3, 12)]}
_PULL = {"label": "Veto (selkä/hauis)", "items": [
    _M("maastaveto", 3, "5,5,5", "72,77,80"),
    _A("leuanveto", 3, 8), _A("alatalja soutu", 3, 10),
    _A("ylätalja", 3, 12), _A("hauiskääntö tanko", 3, 12)]}
_LEGS = {"label": "Jalat", "items": [
    _M("takakyykky", 4, "6,6,6,6", "72,75,77,77"),
    _A("jalkaprässi", 3, 12), _A("romanialainen maastaveto", 3, 10),
    _A("jalkojen koukistus", 3, 12), _A("pohjenousu", 4, 15)]}
_UPPER = {"label": "Yläkroppa", "items": [
    _M("penkkipunnerrus", 4, "6,6,6,6", "72,75,77,77"),
    _A("tankosoutu", 4, 8), _A("pystypunnerrus", 3, 10),
    _A("ylätalja", 3, 12), _A("hauiskääntö tanko", 3, 12), _A("taljapunnerrus", 3, 12)]}
_LOWER = {"label": "Alakroppa", "items": [
    _M("takakyykky", 4, "6,6,6,6", "72,75,77,77"),
    _A("romanialainen maastaveto", 3, 10), _A("jalkaprässi", 3, 12),
    _A("jalkojen koukistus", 3, 12), _A("pohjenousu", 4, 15)]}

# Voimanosto
_PL_SQUAT = {"label": "Kyykkypäivä", "items": [
    _M("takakyykky", 5, "5,5,5,3,3", "75,80,82,85,85"),
    _A("etukyykky", 3, 6), _A("jalkaprässi", 3, 10), _A("jalkojen koukistus", 3, 12)]}
_PL_BENCH = {"label": "Penkkipäivä", "items": [
    _M("penkkipunnerrus", 5, "5,5,5,3,3", "75,80,82,85,85"),
    _A("kapea penkki", 3, 8), _A("pystypunnerrus", 3, 8), _A("taljapunnerrus", 3, 12)]}
_PL_DL = {"label": "Maastavetopäivä", "items": [
    _M("maastaveto", 5, "5,3,3,2,2", "75,82,85,88,88"),
    _A("romanialainen maastaveto", 3, 8), _A("tankosoutu", 3, 8), _A("ylätalja", 3, 10)]}
_PL_BENCH_VOL = {"label": "Penkki (volyymi)", "items": [
    _M("penkkipunnerrus", 5, "8,8,8,8,8", "68,68,68,68,68"),
    _A("vinopenkki", 3, 10), _A("taljaristikko", 3, 12), _A("sivunostot", 3, 15)]}

# Olympia (oikeat olympianostojen apuliikkeet)
_OL_SNATCH = {"label": "Tempauspäivä", "items": [
    _M("tempaus", 6, "3,3,2,2,1,1", "70,75,80,82,85,85"),
    _A("tempauskyykky", 4, 4), _A("tempausveto", 4, 3), _A("etukyykky", 3, 4)]}
_OL_CJ = {"label": "Rinnalleveto & työntö", "items": [
    _M("rinnalleveto ja työntö", 6, "2,2,1,1,1,1", "70,75,80,82,85,85"),
    _A("rinnallevedon veto", 4, 3), _A("etukyykky", 4, 3), _A("työntö telineestä", 3, 2)]}
_OL_SQUAT = {"label": "Kyykky & vedot", "items": [
    _M("takakyykky", 5, "4,4,3,3,2", "75,80,82,85,87"),
    _A("etukyykky", 4, 4), _A("tempausveto", 3, 3), _A("pohjenousu", 4, 15)]}

PLAN_BLUEPRINTS = {
    "bodaus": {
        "goal": "hypertrofia",
        "guidance": ("Lihasmassaohjelma. Pääliikkeissä lähtöpaino lasketaan 1RM:stä; "
                     "lisäliikkeissä valitse paino jolla viimeiset toistot ovat haastavia "
                     "(1–2 varastoa). Lisää painoa tai toistoja kun liike etenee."),
        "days": {3: [_PUSH, _PULL, _LEGS], 4: [_UPPER, _LOWER, _UPPER, _LOWER],
                 5: [_PUSH, _PULL, _LEGS, _UPPER, _LOWER], 6: [_PUSH, _PULL, _LEGS, _PUSH, _PULL, _LEGS]},
    },
    "voimanosto": {
        "goal": "voima",
        "guidance": ("Voimanosto-ohjelma kyykylle, penkille ja maastavedolle. Pääliikkeet "
                     "raskaina (% 1RM:stä), apuliikkeet tukevat. Nosta prosentteja varovasti "
                     "kun nostot menevät varmasti ja puhtaasti."),
        "days": {3: [_PL_SQUAT, _PL_BENCH, _PL_DL], 4: [_PL_SQUAT, _PL_BENCH, _PL_DL, _PL_BENCH_VOL]},
    },
    "olympia": {
        "goal": "olympia",
        "guidance": ("Olympianosto-ohjelma (tempaus ja rinnalleveto & työntö). Tekniikka "
                     "edellä: matalat toistot, pitkät palautukset, laatu ennen kuormaa. "
                     "Etukyykky ja vedot tukevat nostoja."),
        "days": {3: [_OL_SNATCH, _OL_CJ, _OL_SQUAT], 4: [_OL_SNATCH, _OL_CJ, _OL_SQUAT, _OL_SNATCH]},
    },
}


class GenerateIn(BaseModel):
    plan: str  # bodaus | voimanosto | olympia
    days_per_week: int = 3
    profile_id: int | None = None
    name: str | None = None


def _find_exercise(db: Session, keyword: str):
    """Etsi liike kirjastosta nimen perusteella (sisältää avainsanan)."""
    kw = keyword.lower()
    matches = [e for e in db.query(models.Exercise).order_by(models.Exercise.name).all()
               if kw in e.name.lower()]
    return matches[0] if matches else None


@router.get("/plans")
def list_plans():
    """Listaa generoitavat ohjelmatyypit ja niiden tuetut treenikerrat/viikko."""
    return [
        {"id": pid, "goal": b["goal"], "guidance": b["guidance"],
         "days_options": sorted(b["days"].keys())}
        for pid, b in PLAN_BLUEPRINTS.items()
    ]


@router.post("/generate")
def generate_program(payload: GenerateIn, db: Session = Depends(get_db)):
    """Rakenna valmis viikko-ohjelma lajista ja treenikerroista/viikko."""
    bp = PLAN_BLUEPRINTS.get(payload.plan)
    if not bp:
        raise HTTPException(status_code=404, detail="Ohjelmatyyppiä ei löytynyt.")
    # Valitse lähin tuettu treenikertamäärä
    options = sorted(bp["days"].keys())
    days_n = min(options, key=lambda x: abs(x - payload.days_per_week))
    day_blueprints = bp["days"][days_n]

    plan_names = {"bodaus": "Lihasmassa", "voimanosto": "Voimanosto", "olympia": "Olympianosto"}
    program = models.Program(
        name=payload.name or f"{plan_names.get(payload.plan, payload.plan)} {days_n}x/vk",
        profile_id=payload.profile_id, schedule_type="weekly",
        goal=bp["goal"], description=bp["guidance"], is_active=True,
    )
    missing = set()
    for di, dbp in enumerate(day_blueprints):
        day = models.ProgramDay(order_index=di, day_type="train", label=dbp["label"])
        oi = 0
        for item in dbp["items"]:
            ex = _find_exercise(db, item["name"])
            if not ex:
                missing.add(item["name"])
                continue
            if "percent_scheme" in item:
                day.exercises.append(models.ProgramExercise(
                    exercise_id=ex.id, order_index=oi,
                    target_sets=item["sets"], target_reps=int(float(item["rep_scheme"].split(",")[0])),
                    rep_scheme=item["rep_scheme"], percent_scheme=item["percent_scheme"],
                    rest_seconds=180, target_rir=2))
            else:
                day.exercises.append(models.ProgramExercise(
                    exercise_id=ex.id, order_index=oi,
                    target_sets=item["sets"], target_reps=item["reps"],
                    rest_seconds=90, target_rir=2))
            oi += 1
        program.days.append(day)
    db.add(program)
    db.commit()
    db.refresh(program)
    return {"program_id": program.id, "name": program.name, "days": days_n,
            "missing_exercises": sorted(missing)}
