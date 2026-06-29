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


# Energiatiheys: rasvakudoksen muutos ~7700 kcal / kg
KCAL_PER_KG = 7700.0

# Voimatasot (8 porrasta). Kynnykset ovat 1RM / kehon paino -kertoimia
# miehille; naisille kerrotaan FEMALE_FACTORilla. Liikekohtaiset standardit.
STRENGTH_LEVELS = [
    "Aloittelija", "Harrastaja", "Keskitaso", "Edistynyt",
    "Kokenut", "Alueellinen (piiri)", "Kansallinen (SM)", "Maailmanluokka (EM/MM)",
]
FEMALE_FACTOR = 0.72

# (matala -> korkea) kahdeksan kynnyksen kertoimet per liiketyyppi
STRENGTH_STANDARDS = {
    "squat":    [0.75, 1.0, 1.25, 1.5, 1.75, 2.1, 2.5, 3.0],
    "bench":    [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.3],
    "deadlift": [1.0, 1.25, 1.5, 1.75, 2.1, 2.5, 3.0, 3.5],
    "ohp":      [0.35, 0.5, 0.65, 0.8, 0.95, 1.1, 1.3, 1.5],
}


def classify_lift(name: str) -> str | None:
    """Tunnista liike voimastandardiksi nimen perusteella."""
    n = (name or "").lower()
    if "kyykky" in n:
        return "squat"
    if "penkki" in n and "kapea" not in n:
        return "bench"
    if "maasta" in n or "mave" in n:
        return "deadlift"
    if "pystypunnerrus" in n or " pp" in n:
        return "ohp"
    return None


def strength_level(lift_key: str, one_rm: float, bodyweight: float, sex: str | None = None) -> dict | None:
    """Luokittele 1RM voimatasolle kehon painoon suhteutettuna.

    Palauttaa tason, suhdeluvun ja seuraavan tason kynnyksen (kg).
    """
    if lift_key not in STRENGTH_STANDARDS or not bodyweight or bodyweight <= 0 or one_rm <= 0:
        return None
    factor = FEMALE_FACTOR if (sex or "").lower().startswith("nain") else 1.0
    thresholds = [t * factor for t in STRENGTH_STANDARDS[lift_key]]
    ratio = one_rm / bodyweight
    level_idx = 0
    for i, t in enumerate(thresholds):
        if ratio >= t:
            level_idx = i
    # Onko ylittänyt ensimmäisenkin kynnyksen?
    reached_first = ratio >= thresholds[0]
    next_threshold_kg = None
    if level_idx < len(thresholds) - 1:
        next_threshold_kg = round(thresholds[level_idx + 1] * bodyweight, 1)
    return {
        "lift": lift_key,
        "level_index": level_idx if reached_first else -1,
        "level": STRENGTH_LEVELS[level_idx] if reached_first else "Alle aloittelija",
        "ratio": round(ratio, 2),
        "next_level": STRENGTH_LEVELS[level_idx + 1] if level_idx < len(STRENGTH_LEVELS) - 1 else None,
        "next_threshold_kg": next_threshold_kg,
        "ceiling_kg": round(thresholds[-1] * bodyweight, 1),
    }


# Fysiikkatasot (8) rasvattoman massan indeksin (FFMI) mukaan. Miesten asteikko;
# naisille kynnyksiä lasketaan FEMALE_FFMI_OFFSETilla.
PHYSIQUE_LEVELS = [
    "Aloittelija", "Harrastaja", "Keskitaso", "Edistynyt",
    "Kokenut", "Eliitti (natural-huippu)", "Kilpataso", "IFBB Pro -luokka",
]
FFMI_THRESHOLDS = [18.0, 20.0, 22.0, 23.5, 25.0, 26.5, 28.0]  # 7 kynnystä -> 8 tasoa
FEMALE_FFMI_OFFSET = 3.5


def physique_level(ffmi: float | None, sex: str | None = None) -> dict | None:
    """Luokittele fysiikan kehitysaste FFMI:n perusteella (aloittelija → IFBB Pro)."""
    if not ffmi or ffmi <= 0:
        return None
    offset = FEMALE_FFMI_OFFSET if (sex or "").lower().startswith("nain") else 0.0
    thresholds = [t - offset for t in FFMI_THRESHOLDS]
    level_idx = 0
    for i, t in enumerate(thresholds):
        if ffmi >= t:
            level_idx = i + 1
    next_threshold = thresholds[level_idx] if level_idx < len(thresholds) else None
    return {
        "ffmi": round(ffmi, 1),
        "level_index": level_idx,
        "level": PHYSIQUE_LEVELS[level_idx],
        "next_level": PHYSIQUE_LEVELS[level_idx + 1] if level_idx < len(PHYSIQUE_LEVELS) - 1 else None,
        "next_ffmi": round(next_threshold, 1) if next_threshold else None,
        "levels": PHYSIQUE_LEVELS,
    }


def _linear_rate(points: list[tuple]) -> float:
    """Lineaarisen sovituksen kulmakerroin (y-yksikköä / päivä). points: [(ordinal_day, value)]."""
    n = len(points)
    if n < 2:
        return 0.0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom


def forecast_progress(
    history: list[tuple], horizon_weeks: int = 26, ceiling: float | None = None
) -> list[dict]:
    """Ennusta kehitys realistisesti vähenevällä tuotolla.

    history: [(date, value)] (esim. arvioitu 1RM). Lähihistoriasta lasketaan
    viikkotahti, jota vaimennetaan kun arvo lähestyy kattoa (fysiologinen raja).
    Palauttaa viikoittaiset pisteet keski-, ala- ja yläennusteineen.
    """
    valid = [(d, v) for d, v in history if v and v > 0]
    if len(valid) < 2:
        return []
    valid.sort(key=lambda p: p[0])
    base_date = valid[0][0]
    pts = [((d - base_date).days, v) for d, v in valid]
    # Käytä korkeintaan viimeistä ~84 päivää tahdin arviointiin
    last_day = pts[-1][0]
    recent = [p for p in pts if p[0] >= last_day - 84] or pts
    rate_per_day = max(0.0, _linear_rate(recent))  # ei ennusteta laskua
    rate_per_week = rate_per_day * 7

    current = valid[-1][1]
    if ceiling is None or ceiling <= current:
        ceiling = current * 1.5  # ilman standardia oletetaan 50 % varaa

    from datetime import timedelta

    out = []
    value = current
    for w in range(1, horizon_weeks + 1):
        # Vähenevä tuotto: tahti hidastuu kattoa lähestyttäessä
        damp = max(0.1, 1 - (value / ceiling))
        value = min(ceiling, value + rate_per_week * damp)
        gain = value - current
        # Epävarmuus kasvaa ajan myötä
        spread = max(0.5, 0.35 * gain) + 0.015 * current * (w ** 0.5)
        out.append({
            "date": (valid[-1][0] + timedelta(weeks=w)).isoformat(),
            "mid": round(value, 1),
            "low": round(value - spread, 1),
            "high": round(value + spread, 1),
        })
    return out


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearsonin korrelaatiokerroin kahden sarjan välillä."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    if sx == 0 or sy == 0:
        return None
    cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    return round(cov / (sx * sy), 2)


def weekly_average(points: list[tuple], end_date, days: int = 7) -> float | None:
    """Keskimääräinen paino [end_date-days, end_date] -ikkunassa.

    points: [(date, value), ...]. Viikkokeskiarvo vaimentaa päivän heilahdukset,
    jolloin trendi ja korjaukset osuvat oikeaan suuntaan.
    """
    from datetime import timedelta

    start = end_date - timedelta(days=days - 1)
    window = [v for d, v in points if start <= d <= end_date and v is not None]
    if not window:
        return None
    return round(sum(window) / len(window), 2)


def weight_trend(points: list[tuple], today) -> float | None:
    """Painon muutos kg/viikko vertaamalla tämän ja edellisen viikon keskiarvoja."""
    from datetime import timedelta

    this_week = weekly_average(points, today, 7)
    last_week = weekly_average(points, today - timedelta(days=7), 7)
    if this_week is None or last_week is None:
        return None
    return round(this_week - last_week, 2)


def adaptive_tdee(avg_intake_kcal: float, weight_change_kg: float, days: int) -> float | None:
    """Arvioi ylläpitokalorit (TDEE) toteutuneesta syönnistä ja painomuutoksesta.

    Jos paino nousi enemmän kuin syönti selittäisi -> TDEE pienempi, ja päinvastoin.
    TDEE = keskisyönti - (painomuutos * 7700 / päivät)
    """
    if not avg_intake_kcal or days <= 0:
        return None
    return round(avg_intake_kcal - (weight_change_kg * KCAL_PER_KG / days), 0)


def macro_targets(bodyweight: float, goal: str, tdee: float, target_rate: float) -> dict:
    """Laske kcal- ja makrotavoitteet kehon painosta, tavoitteesta ja tahdista.

    target_rate kg/viikko -> päivittäinen energiavaje/ylijäämä = rate*7700/7.
    Proteiini painotetaan korkeaksi etenkin dieetillä lihasten säilyttämiseksi.
    """
    daily_delta = target_rate * KCAL_PER_KG / 7.0
    kcal = max(1200.0, tdee + daily_delta)
    protein_per_kg = {"cut": 2.2, "maintain": 1.8, "bulk": 2.0}.get(goal, 1.8)
    protein_g = round(bodyweight * protein_per_kg)
    fat_g = round(bodyweight * 0.8)
    carbs_g = round(max(0.0, (kcal - protein_g * 4 - fat_g * 9) / 4))
    return {
        "kcal": round(kcal),
        "protein_g": protein_g,
        "fat_g": fat_g,
        "carbs_g": carbs_g,
        "tdee": round(tdee),
        "daily_delta": round(daily_delta),
    }


def diet_recommendation(goal: str, target_rate: float, actual_rate: float | None,
                        current_kcal: float | None, targets: dict) -> str:
    """Tuota suositus: pitäisikö kaloreita nostaa/laskea jotta tahti vastaa tavoitetta."""
    if actual_rate is None:
        return "Kirjaa painoa ja ruokaa noin viikon ajan, niin saat tarkan suosituksen."
    diff = actual_rate - target_rate  # positiivinen = nousee liikaa / laskee liian hitaasti
    tgt = targets["kcal"]
    if abs(diff) <= 0.15:
        return f"Tahti on tavoitteessa ({actual_rate:+.2f} kg/vk). Pidä noin {tgt} kcal/pv."
    # Karkea korjaus: 0.1 kg/vk ~ 110 kcal/pv
    adjust = round(-diff * KCAL_PER_KG / 7.0 / 10) * 10
    suunta = "nosta" if adjust > 0 else "laske"
    if goal == "maintain":
        return (f"Paino muuttuu {actual_rate:+.2f} kg/vk vaikka tavoite on ylläpito. "
                f"{suunta.capitalize()} kaloreita ~{abs(adjust)} kcal/pv (kohti {tgt + adjust} kcal).")
    return (f"Tahti {actual_rate:+.2f} kg/vk vs. tavoite {target_rate:+.2f} kg/vk. "
            f"{suunta.capitalize()} kaloreita ~{abs(adjust)} kcal/pv (kohti {tgt + adjust} kcal).")


def day_targets(targets: dict, training_days: int, workout_kcal_avg: float | None = None) -> dict:
    """Jaa viikon kalorit treeni- ja lepopäiville (hiilarisyklitys).

    Viikkokeskiarvo pysyy tavoitteessa: treenipäivinä syödään enemmän
    (lisäkalorit hiileinä suorituskykyä varten), lepopäivinä vähemmän.
    Proteiini pidetään vakiona, rasva hieman korkeampana lepopäivinä.
    """
    daily = targets["kcal"]
    protein = targets["protein_g"]
    training_days = max(0, min(7, training_days))
    rest_days = 7 - training_days
    weekly = daily * 7

    if training_days == 0 or rest_days == 0:
        # Ei syklitystä jos kaikki päivät samanlaisia
        return {
            "training_days_per_week": training_days,
            "train_day": targets, "rest_day": targets, "cycled": False,
        }

    # Treenipäivän lisä: puolet poltetuista kaloreista, max 20 % päivätavoitteesta
    if workout_kcal_avg:
        delta = min(workout_kcal_avg * 0.5, daily * 0.2)
    else:
        delta = daily * 0.12
    train_kcal = daily + delta
    # Pidä viikkosumma vakiona -> lepopäivät kompensoivat
    rest_kcal = (weekly - train_kcal * training_days) / rest_days

    def macros(kcal):
        fat = round(targets["fat_g"])  # rasva vakaa
        carbs = round(max(0.0, (kcal - protein * 4 - fat * 9) / 4))
        return {"kcal": round(kcal), "protein_g": protein, "fat_g": fat, "carbs_g": carbs}

    # Rasva hieman korkeampi lepopäivänä, matalampi treenipäivänä
    train = macros(train_kcal)
    rest = macros(rest_kcal)
    train["fat_g"] = round(targets["fat_g"] * 0.85)
    train["carbs_g"] = round(max(0.0, (train_kcal - protein * 4 - train["fat_g"] * 9) / 4))
    rest["fat_g"] = round(targets["fat_g"] * 1.15)
    rest["carbs_g"] = round(max(0.0, (rest_kcal - protein * 4 - rest["fat_g"] * 9) / 4))
    return {
        "training_days_per_week": training_days,
        "train_day": train, "rest_day": rest, "cycled": True,
    }


def weekly_review(target_daily_kcal: float, actual_avg_kcal: float | None,
                  target_rate: float, actual_rate: float | None) -> dict:
    """Viikkoyhteenveto: kalorien noudattaminen ja tahdin osuvuus tavoitteeseen."""
    out = {"target_weekly_kcal": round(target_daily_kcal * 7)}
    if actual_avg_kcal is not None:
        out["actual_weekly_kcal"] = round(actual_avg_kcal * 7)
        adherence = round(100 - abs(actual_avg_kcal - target_daily_kcal) / target_daily_kcal * 100)
        out["adherence_pct"] = max(0, adherence)
    if actual_rate is not None:
        diff = actual_rate - target_rate
        if abs(diff) <= 0.15:
            out["verdict"] = "Tahti tavoitteessa — jatka samaan malliin."
        elif diff > 0:
            out["verdict"] = "Paino nousee tavoitetta nopeammin / laskee hitaammin — tarkista kalorit."
        else:
            out["verdict"] = "Paino laskee tavoitetta nopeammin — harkitse kalorien nostoa."
    return out


def waist_assessment(waist_cm: float | None, height_cm: float | None, goal: str) -> dict | None:
    """Bulkin vyötärö-raja-arvio. Vyötärö/pituus -suhde on hyvä terveysmittari.

    > 0.55 alkaa olla koholla, > 0.58 korkea -> bulkkaaminen kannattaa lopettaa.
    """
    if not waist_cm:
        return None
    out = {"waist_cm": waist_cm}
    if height_cm and height_cm > 0:
        ratio = round(waist_cm / height_cm, 3)
        out["waist_height_ratio"] = ratio
        if ratio >= 0.58:
            level, msg = "korkea", "Vyötärö on jo korkealla — lopeta bulkki ja harkitse dieettiä."
        elif ratio >= 0.55:
            level, msg = "koholla", "Vyötärö alkaa olla koholla — bulkkia kannattaa hidastaa pian."
        else:
            level, msg = "ok", "Vyötärö järkevällä tasolla bulkkiin."
        out["level"] = level
        out["message"] = msg if goal == "bulk" else f"Vyötärö/pituus {ratio} ({level})."
    return out


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
