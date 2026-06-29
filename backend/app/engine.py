"""Laskentamoottori.

Sisältää voimaharjoittelun perusmatematiikan:
  - arvioidun maksimin (1RM) laskenta toteutuneesta sarjasta
  - paino tietylle toisto/varasto-tavoitteelle
  - sarjaohjelman konversio (esim. 4x5 -> 4x8): mille painolle pitäisi vaihtaa
  - lajitotalin (esim. voimanosto) arvio ala- ja ylärajoineen

Kaava: Epley-pohjainen, mutta varasto (RIR, reps in reserve) huomioiden.
Idea: jos teet 5 toistoa ja varastoa on 2, todellinen "uupumustoistomäärä" on 7.
Tällöin painonvaihdoksen laskenta vastaa sitä, millä todella pitäisi pystyä
suoriutumaan uudesta tavoitteesta samalla rasituksella.
"""
from dataclasses import dataclass

# Painon pyöristys lähimpään levyn realistiseen porrastukseen.
DEFAULT_INCREMENT = 2.5


def _effective_reps(reps: int, rir: float | None) -> float:
    """Toistot uupumukseen = tehdyt toistot + jäljelle jäänyt varasto."""
    return reps + (rir if rir is not None else 0.0)


def estimate_1rm(weight: float, reps: int, rir: float | None = None) -> float:
    """Arvioi yhden toiston maksimin Epleyn kaavalla varasto huomioiden.

    1RM = w * (1 + toistot_uupumukseen / 30)
    """
    eff = _effective_reps(reps, rir)
    if weight <= 0:
        return 0.0
    if eff <= 1:
        return weight
    return weight * (1.0 + eff / 30.0)


def weight_for_reps(
    one_rm: float, target_reps: int, target_rir: float | None = None
) -> float:
    """Laske paino, jolla annettu toistotavoite onnistuu halutulla varastolla.

    Käänteinen Epley: w = 1RM / (1 + toistot_uupumukseen / 30)
    """
    eff = _effective_reps(target_reps, target_rir)
    if one_rm <= 0:
        return 0.0
    return one_rm / (1.0 + eff / 30.0)


def round_to_increment(weight: float, increment: float = DEFAULT_INCREMENT) -> float:
    """Pyöristä lähimpään realistiseen painoon (oletus 2.5 kg)."""
    if increment <= 0:
        return round(weight, 1)
    return round(weight / increment) * increment


@dataclass
class SchemeConversion:
    """Tulos sarjaohjelman konversiolle (esim. 4x5 -> 4x8)."""

    estimated_1rm: float
    current_weight: float
    suggested_weight: float
    suggested_weight_rounded: float
    from_scheme: str
    to_scheme: str
    note: str


def convert_scheme(
    current_weight: float,
    current_sets: int,
    current_reps: int,
    target_sets: int,
    target_reps: int,
    current_rir: float | None = None,
    target_rir: float | None = None,
    increment: float = DEFAULT_INCREMENT,
) -> SchemeConversion:
    """Laske paino uudelle sarjaohjelmalle saman rasituksen säilyttämiseksi.

    Esim. tehtiin 4x5 painolla 100 kg täysillä (kaikki sarjat menivät),
    halutaan vaihtaa 4x8 -> mikä paino vastaa samaa suhteellista kuormaa.

    Jos varastoa ei anneta, oletetaan että moninkertaisessa sarjaohjelmassa
    ekoissa sarjoissa on varaa: oletusvarasto skaalautuu toistomäärän mukaan.
    """
    # Oletusvarasto: useamman sarjan ohjelmassa viimeinen sarja on lähinnä
    # uupumusta, mutta ekoissa on varaa. Käytetään maltillista oletusta.
    if current_rir is None:
        current_rir = 2.0
    if target_rir is None:
        target_rir = current_rir

    one_rm = estimate_1rm(current_weight, current_reps, current_rir)
    suggested = weight_for_reps(one_rm, target_reps, target_rir)
    rounded = round_to_increment(suggested, increment)

    direction = "kevyemmäksi" if target_reps > current_reps else "raskaammaksi"
    return SchemeConversion(
        estimated_1rm=round(one_rm, 1),
        current_weight=current_weight,
        suggested_weight=round(suggested, 1),
        suggested_weight_rounded=rounded,
        from_scheme=f"{current_sets}x{current_reps}",
        to_scheme=f"{target_sets}x{target_reps}",
        note=(
            f"Arvioitu 1RM {round(one_rm, 1)} kg (varasto {current_rir}). "
            f"Tavoitteelle {target_sets}x{target_reps} paino muuttuu {direction}: "
            f"~{rounded} kg (varasto {target_rir})."
        ),
    )


def body_composition(bodyweight: float, body_fat_pct: float, height_cm: float | None = None) -> dict:
    """Arvioi kehon koostumus painosta ja rasvaprosentista.

    Palauttaa rasvamassan, rasvattoman massan (lihakset+luut+vesi), FFMI:n
    (rasvattoman massan indeksi, jos pituus annettu) ja BMI:n.
    """
    fat_mass = round(bodyweight * body_fat_pct / 100.0, 1)
    lean_mass = round(bodyweight - fat_mass, 1)
    out = {"fat_mass_kg": fat_mass, "lean_mass_kg": lean_mass}
    if height_cm and height_cm > 0:
        h_m = height_cm / 100.0
        out["bmi"] = round(bodyweight / (h_m * h_m), 1)
        # FFMI = rasvaton massa / pituus^2 (vakioidaan 1.8 m pituuteen)
        ffmi = lean_mass / (h_m * h_m)
        out["ffmi"] = round(ffmi + 6.1 * (1.8 - h_m), 1)
    return out


def age_from_birthdate(birthdate, today) -> int | None:
    """Laske ikä vuosina syntymäpäivästä."""
    if not birthdate:
        return None
    years = today.year - birthdate.year
    if (today.month, today.day) < (birthdate.month, birthdate.day):
        years -= 1
    return years


def best_1rm_from_sets(sets: list[dict]) -> dict | None:
    """Palauta paras arvioitu 1RM joukosta sarjoja.

    sets: [{"weight": .., "reps": .., "rir": .. , "completed": bool}, ...]
    Vain suoritetut (completed) ja toistoja sisältävät sarjat huomioidaan.
    """
    best = None
    for s in sets:
        if not s.get("completed", True):
            continue
        reps = int(s.get("reps", 0))
        weight = float(s.get("weight", 0))
        if reps <= 0 or weight <= 0:
            continue
        e = estimate_1rm(weight, reps, s.get("rir"))
        if best is None or e > best["estimated_1rm"]:
            best = {
                "estimated_1rm": round(e, 1),
                "weight": weight,
                "reps": reps,
                "rir": s.get("rir"),
            }
    return best


def parse_scheme(text_value: str | None) -> list[float]:
    """Jäsennä sarjamalli listaksi.

    Tukee muotoja:
      "12,10,8"   -> [12, 10, 8]   (per sarja)
      "5x5"       -> [5, 5, 5, 5, 5]
      "4x8,10,12" -> [8, 10, 12, ...]  (ensimmäinen luku jätetään huomiotta,
                     jos sen jälkeen tulee pilkkulista; muuten 4x8 -> 8,8,8,8)
    """
    if not text_value:
        return []
    text_value = text_value.strip().lower().replace(" ", "")
    # Muoto "NxM" ilman pilkkuja -> N sarjaa M toistoa
    if "x" in text_value and "," not in text_value:
        try:
            n, m = text_value.split("x")
            return [float(m)] * int(n)
        except ValueError:
            return []
    # Muoto "Nx8,10,12" -> pilkkulista ratkaisee (N vain vihje)
    if "x" in text_value:
        text_value = text_value.split("x", 1)[1]
    out = []
    for part in text_value.split(","):
        if part:
            try:
                out.append(float(part))
            except ValueError:
                continue
    return out


@dataclass
class TotalEstimate:
    """Lajitotalin arvio (esim. voimanosto: kyykky + penkki + mave)."""

    total_low: float
    total_mid: float
    total_high: float
    per_lift: dict[str, dict[str, float]]


def estimate_total(
    lifts: dict[str, dict],
) -> TotalEstimate:
    """Arvioi lajitotalin nostokohtaisista parhaista sarjoista.

    lifts: { "kyykky": {"weight": 200, "reps": 5, "rir": 1}, ... }

    Jokaiselle nostolle lasketaan arvioitu 1RM. Ala-/yläraja syntyy varaston
    epävarmuudesta: alaraja olettaa pienemmän varaston, yläraja suuremman.
    """
    per_lift: dict[str, dict[str, float]] = {}
    low = mid = high = 0.0
    for name, d in lifts.items():
        w = float(d.get("weight", 0))
        reps = int(d.get("reps", 1))
        rir = d.get("rir")
        rir_val = 1.0 if rir is None else float(rir)
        # Keskiarvio annetulla varastolla; haarukka +/- 1 toisto varastoa.
        e_mid = estimate_1rm(w, reps, rir_val)
        e_low = estimate_1rm(w, reps, max(0.0, rir_val - 1))
        e_high = estimate_1rm(w, reps, rir_val + 1)
        per_lift[name] = {
            "low": round(e_low, 1),
            "mid": round(e_mid, 1),
            "high": round(e_high, 1),
        }
        low += e_low
        mid += e_mid
        high += e_high
    return TotalEstimate(
        total_low=round(low, 1),
        total_mid=round(mid, 1),
        total_high=round(high, 1),
        per_lift=per_lift,
    )
