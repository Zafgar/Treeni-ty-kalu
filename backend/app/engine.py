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


# Naturaalinostajan realistinen huippu (1RM / kehon paino) pääliikkeissä.
# Käytetään ennusteen kattona, jotta kehityskaari noudattaa luonnollista
# nostajaa (lähestyy asymptoottisesti, ei lupaa eliittikertoimia).
NATURAL_CEILINGS = {"squat": 2.4, "bench": 1.8, "deadlift": 2.8, "ohp": 1.15}


def natural_ceiling(lift_key: str, bodyweight: float, sex: str | None = None) -> float | None:
    """Naturaalinostajan realistinen 1RM-katto liikkeelle (kg)."""
    if lift_key not in NATURAL_CEILINGS or not bodyweight or bodyweight <= 0:
        return None
    factor = FEMALE_FACTOR if (sex or "").lower().startswith("nain") else 1.0
    return round(NATURAL_CEILINGS[lift_key] * factor * bodyweight, 1)


# Väestön keskiarvo (treenamaton aikuinen): 1RM / kehon paino, miehet.
POPULATION_AVG = {"squat": 0.9, "bench": 0.75, "deadlift": 1.1, "ohp": 0.45}


def population_average(lift_key: str, bodyweight: float, sex: str | None = None) -> float | None:
    """Arvio mitä keskimääräinen (treenamaton) ihminen nostaa omassa painossaan."""
    if lift_key not in POPULATION_AVG or not bodyweight or bodyweight <= 0:
        return None
    factor = FEMALE_FACTOR if (sex or "").lower().startswith("nain") else 1.0
    return round(POPULATION_AVG[lift_key] * factor * bodyweight, 1)


def value_near(series: list[tuple], target_date, tol_days: int = 18) -> float | None:
    """Palauta sarjan arvo lähimmältä päivältä target_daten ympärillä (tol sisällä)."""
    best = None
    best_diff = None
    for d, v in series:
        if v is None:
            continue
        diff = abs((d - target_date).days)
        if diff <= tol_days and (best_diff is None or diff < best_diff):
            best, best_diff = v, diff
    return best


def calibration_factor(matured: list[dict]) -> float:
    """Laske kalibrointikerroin aiemmista toteutuneista ennusteista.

    matured: [{"base", "predicted", "actual"}]. Vertaa ennustettua ja
    toteutunutta muutosta -> kerroin tuleville ennusteille (rajattu 0.6–1.4).
    """
    ratios = []
    for m in matured:
        pred_gain = m["predicted"] - m["base"]
        act_gain = m["actual"] - m["base"]
        if abs(pred_gain) < 0.5:  # liian pieni ennustettu muutos -> ohita
            continue
        ratios.append(act_gain / pred_gain)
    if len(ratios) < 2:
        return 1.0
    ratios.sort()
    mid = ratios[len(ratios) // 2]  # mediaani robustiksi
    return max(0.6, min(1.4, round(mid, 2)))


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


def estimate_workout_kcal(bodyweight: float, duration_min: float, tonnage: float = 0.0) -> int | None:
    """Arvioi treenin kulutus jos älykellodataa ei ole annettu.

    Voimaharjoittelu ~5 MET: kcal/min ≈ paino * 0.0875. Lisäksi pieni lisä
    siirretyn kokonaisraudan mukaan. Suuntaa antava, ei tarkka.
    """
    if not bodyweight or not duration_min or duration_min <= 0:
        return None
    base = bodyweight * 0.0875 * duration_min
    extra = tonnage * 0.0008  # ~0.8 kcal per tonni
    return int(round(base + extra))


def proportion_score(measurements: dict, height_cm: float | None, sex: str | None = None) -> dict | None:
    """Kehon suhdepisteet (0–100) ympärysmitoista ja pituudesta.

    Hyödyntää klassisia esteettisiä suhteita:
      - vyötärö/pituus (matala parempi, ihanne ~0.45)
      - hartia/vyötärö (V-malli, ihanne ~1.6)
      - rintakehä/vyötärö (ihanne ~1.4)
    Laskee vain saatavilla olevista mitoista — mitä enemmän mittoja, sen parempi.
    """
    waist = measurements.get("vyötärö")
    shoulder = measurements.get("hartia")
    chest = measurements.get("rintakehä")
    parts = []
    breakdown = {}

    if waist and height_cm:
        whtr = waist / height_cm
        s = 100 if whtr <= 0.45 else (40 if whtr >= 0.55 else round(100 - (whtr - 0.45) * 600))
        s = max(15, min(100, s))
        parts.append(s)
        breakdown["vyötärö/pituus"] = {"ratio": round(whtr, 3), "score": s}
    if shoulder and waist:
        r = shoulder / waist
        s = max(20, min(100, round(100 - abs(r - 1.6) * 120)))
        parts.append(s)
        breakdown["hartia/vyötärö"] = {"ratio": round(r, 2), "score": s}
    if chest and waist:
        r = chest / waist
        s = max(20, min(100, round(100 - abs(r - 1.4) * 120)))
        parts.append(s)
        breakdown["rintakehä/vyötärö"] = {"ratio": round(r, 2), "score": s}

    if not parts:
        return None
    return {"score": round(sum(parts) / len(parts)), "breakdown": breakdown, "metrics_used": len(parts)}


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


def forecast_confidence(n_points: int, span_days: int) -> float:
    """Ennusteen luottamus 0–1 datan määrästä ja kestosta. Mitä enemmän
    treenikertoja ja pidempi seurantajakso, sitä kapeampi haarukka."""
    by_count = min(1.0, n_points / 12.0)
    by_span = min(1.0, span_days / 84.0)
    return round(0.5 * by_count + 0.5 * by_span, 2)


def forecast_progress(
    history: list[tuple], horizon_weeks: int = 26, ceiling: float | None = None,
    bodyweight_trend_per_week: float = 0.0, confidence: float = 1.0,
    rate_calibration: float = 1.0,
) -> list[dict]:
    """Ennusta kehitys realistisesti vähenevällä tuotolla (data + malli).

    history: [(date, value)] (esim. arvioitu 1RM). Lähihistoriasta lasketaan
    viikkotahti (DATA), jota vaimennetaan kun arvo lähestyy fysiologista kattoa
    (MALLI/tutkimus). Painon lasku hidastaa tahtia ja laskee kattoa (max
    potentiaali skaalautuu painon mukaan). Pienempi data -> leveämpi haarukka.
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
    # Kalibrointi: aiemman osuvuuden mukaan (jos ennusteet ovat aliarvioineet
    # -> nostetaan tahtia, jos yliarvioineet -> lasketaan). Rajattu maltilliseksi.
    rate_per_week = rate_per_day * 7 * max(0.6, min(1.4, rate_calibration))

    current = valid[-1][1]
    if ceiling is None or ceiling <= current:
        ceiling = current * 1.5  # ilman standardia oletetaan 50 % varaa

    # Painon lasku (dieetti) hidastaa kehitystä ja laskee max potentiaalia
    if bodyweight_trend_per_week < 0:
        rate_per_week *= max(0.4, 1.0 + bodyweight_trend_per_week * 0.3)
        ceiling *= max(0.85, 1.0 + bodyweight_trend_per_week * 0.05)
        ceiling = max(ceiling, current)

    # Datan niukkuus levittää haarukkaa (vähemmän dataa = epävarmempi)
    spread_mult = 1.6 - 0.6 * max(0.0, min(1.0, confidence))

    from datetime import timedelta

    out = []
    value = current
    for w in range(1, horizon_weeks + 1):
        # Vähenevä tuotto: tahti hidastuu kattoa lähestyttäessä
        damp = max(0.1, 1 - (value / ceiling))
        value = min(ceiling, value + rate_per_week * damp)
        gain = value - current
        # Epävarmuus kasvaa ajan myötä ja datan niukkuuden mukaan
        spread = (max(0.5, 0.35 * gain) + 0.015 * current * (w ** 0.5)) * spread_mult
        out.append({
            "date": (valid[-1][0] + timedelta(weeks=w)).isoformat(),
            "mid": round(value, 1),
            "low": round(value - spread, 1),
            "high": round(value + spread, 1),
        })
    return out


# Ympärysmittojen luonnolliset kattokertoimet (pituuteen suhteutettuna,
# miehet). Pehmeä raja — ei absoluuttinen; genetiikka/aineet voivat ylittää,
# ja jos oma data jo ylittää, kattoa nostetaan datan mukaan. Vyötärölle ei
# kasvukattoa (matalampi parempi) vaan pohja.
MEAS_CEILING_MULT = {
    "hauis": 0.25, "rintakehä": 0.68, "reisi": 0.38, "pohje": 0.235,
    "hartia": 0.72, "kyynärvarsi": 0.19, "forkku": 0.19,
}
FEMALE_MEAS_FACTOR = 0.85


def measurement_ceiling(site: str, height_cm: float | None, sex: str | None = None) -> float | None:
    """Arvioitu luonnollinen kattomitta (cm) pituuden mukaan. Vyötärölle None."""
    if not height_cm:
        return None
    mult = MEAS_CEILING_MULT.get((site or "").lower())
    if mult is None:
        return None
    factor = FEMALE_MEAS_FACTOR if (sex or "").lower().startswith("nain") else 1.0
    return round(height_cm * mult * factor, 1)


def measurement_floor(site: str, height_cm: float | None) -> float | None:
    """Pehmeä alaraja (cm): vyötärö ei laske loputtomiin, raaja ei kutistu mitättömäksi."""
    if not height_cm:
        return None
    s = (site or "").lower()
    if s == "vyötärö":
        return round(height_cm * 0.42, 1)
    mult = MEAS_CEILING_MULT.get(s)
    return round(height_cm * mult * 0.6, 1) if mult else None


def recent_rate_per_week(history: list[tuple], window_days: int = 84) -> float | None:
    """Lähihistorian muutostahti (yksikköä/viikko). Voi olla negatiivinen."""
    valid = sorted([(d, v) for d, v in history if v is not None], key=lambda p: p[0])
    if len(valid) < 2:
        return None
    base = valid[0][0]
    pts = [((d - base).days, v) for d, v in valid]
    last = pts[-1][0]
    recent = [p for p in pts if p[0] >= last - window_days] or pts
    return _linear_rate(recent) * 7


def forecast_measurement(history: list[tuple], horizon_weeks: int = 26,
                         confidence: float = 1.0, ceiling: float | None = None,
                         floor: float | None = None, rate_calibration: float = 1.0) -> list[dict]:
    """Ennusta ympärysmitan kehitys datavetoisesti (kasvu JA lasku).

    Perustuu ENSISIJAISESTI omaan lähitrendiin (adaptoituu: jos esim. reisi
    kasvaa odotettua nopeammin, ennuste seuraa sitä; jos hidastuu, mitoittuu
    uudelleen seuraavalla kerralla). Kasvu tasaantuu pehmeästi kohti
    pituuspohjaista luonnollista kattoa, lasku kohti pohjaa. Aineet/genetiikka:
    jos data jo ylittää mallinnetun katon, katto nostetaan datan mukaan.
    """
    valid = [(d, v) for d, v in history if v and v > 0]
    if len(valid) < 3:  # mitalle tarvitaan hieman enemmän dataa
        return []
    valid.sort(key=lambda p: p[0])
    base = valid[0][0]
    pts = [((d - base).days, v) for d, v in valid]
    last_day = pts[-1][0]
    recent = [p for p in pts if p[0] >= last_day - 84] or pts
    rate_per_week = _linear_rate(recent) * 7 * max(0.6, min(1.4, rate_calibration))  # voi olla negatiivinen
    current = valid[-1][1]
    spread_mult = 1.6 - 0.6 * max(0.0, min(1.0, confidence))

    # Pehmeä katto: ei rajoita jos data jo ylittää sen (huomioi geneettisesti
    # lahjakkaat / aineet). Pieni puskuri jotta ennuste ei jää heti seinään.
    if ceiling is not None:
        ceiling = max(ceiling, current * 1.03)

    from datetime import timedelta
    out = []
    value = current
    for w in range(1, horizon_weeks + 1):
        step = rate_per_week * (0.96 ** w)  # tasaantuu ajan myötä
        if step > 0 and ceiling:
            # Kasvu hidastuu lähestyttäessä kattoa (vähenevä tuotto)
            room = max(0.0, ceiling - value)
            step *= min(1.0, room / (ceiling * 0.1))
            value = min(ceiling, value + step)
        elif step < 0 and floor:
            room = max(0.0, value - floor)
            step *= min(1.0, room / (floor * 0.1 + 1))
            value = max(floor, value + step)
        else:
            value += step
        spread = (0.3 + 0.04 * abs(value - current) + 0.01 * (w ** 0.5)) * spread_mult
        out.append({
            "date": (valid[-1][0] + timedelta(weeks=w)).isoformat(),
            "mid": round(value, 1),
            "low": round(value - spread, 1),
            "high": round(value + spread, 1),
        })
    return out


def measurement_insight(site: str, rate_per_week: float | None, current: float | None,
                        ceiling: float | None, bw_trend: float | None,
                        waist_trend: float | None) -> str:
    """Tulkitse mitan kehitys suhteessa painoon, vyötäröön ja kattoon.

    Tunnistaa mm.: rasvavetoinen kasvu (paino+vyötärö nousee), lihaskasvu
    (paino/vyötärö ei nouse), vakaa dieetillä (lihas säilyy), lähellä kattoa.
    """
    if rate_per_week is None or current is None:
        return ""
    s = (site or "").lower()
    notes = []
    bw = bw_trend or 0.0
    waist = waist_trend or 0.0
    if ceiling and current >= ceiling * 0.95 and rate_per_week > 0:
        notes.append("lähellä arvioitua luonnollista kattoa — kasvu hidastuu")
    if s != "vyötärö":
        if rate_per_week > 0.05 and bw > 0.1 and waist > 0.1:
            notes.append("kasvu todennäköisesti osin rasvaa (paino ja vyötärö nousevat)")
        elif rate_per_week > 0.05 and bw <= 0.05 and waist <= 0.05:
            notes.append("lihaskasvua — paino/vyötärö ei nouse")
        elif abs(rate_per_week) < 0.03 and bw < -0.1:
            notes.append("pysyy vakaana dieetillä — lihas säilyy hyvin")
        elif rate_per_week < -0.05 and bw < -0.1:
            notes.append("pienenee painonpudotuksen myötä")
    else:  # vyötärö
        if rate_per_week < -0.05 and bw < -0.05:
            notes.append("kapenee dieetillä — rasva vähenee")
        elif rate_per_week > 0.05 and bw > 0.05:
            notes.append("kasvaa painon noustessa — seuraa ettei rasvaa kerry liikaa")
    return "; ".join(notes)


def volume_verdict(sets_week: int, sets_prev: int) -> dict:
    """Arvioi lihasryhmän viikkovolyymi ja anna ehdotus.

    Yleinen hypertrofiasuositus on ~10–20 laadukasta työsarjaa lihasryhmää
    kohden viikossa. Tämän alle voi kasvattaa, reilusti yli voi keventää.
    """
    if sets_week == 0:
        return {"status": "none", "suggestion": "Ei treenattu tällä viikolla — lisää vähintään muutama sarja."}
    if sets_week < 8:
        return {"status": "low",
                "suggestion": f"Matala volyymi ({sets_week} sarjaa). Harkitse 2–4 sarjan lisäystä kasvun tueksi."}
    if sets_week > 22:
        return {"status": "high",
                "suggestion": f"Korkea volyymi ({sets_week} sarjaa). Voit keventää jos palautuminen tai voima kärsii."}
    note = ""
    if sets_prev and sets_week <= sets_prev - 5:
        note = f" Volyymi laski edellisestä viikosta ({sets_prev} → {sets_week})."
    return {"status": "ok", "suggestion": f"Hyvällä tasolla ({sets_week} sarjaa).{note}"}


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


def macro_targets(bodyweight: float, goal: str, tdee: float, target_rate: float,
                  low_carb: bool = False) -> dict:
    """Laske kcal- ja makrotavoitteet kehon painosta, tavoitteesta ja tahdista.

    target_rate kg/viikko -> päivittäinen energiavaje/ylijäämä = rate*7700/7.
    Proteiini painotetaan korkeaksi etenkin dieetillä lihasten säilyttämiseksi.
    low_carb: nostaa rasvaa ja pudottaa hiilihydraatit minimiin.
    """
    daily_delta = target_rate * KCAL_PER_KG / 7.0
    kcal = max(1200.0, tdee + daily_delta)
    protein_per_kg = {"cut": 2.2, "maintain": 1.8, "bulk": 2.0}.get(goal, 1.8)
    protein_g = round(bodyweight * protein_per_kg)
    # Low carb: rasva korkeammaksi, loput hiilareina (jää matalaksi)
    fat_g = round(bodyweight * (1.3 if low_carb else 0.8))
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


def _parse_clock(s: str | None, default_min: int) -> int:
    """Muunna 'HH:MM' minuuteiksi keskiyöstä."""
    if not s:
        return default_min
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return default_min


def _fmt_clock(minutes: int) -> str:
    minutes = max(0, min(24 * 60 - 1, int(round(minutes))))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _meal_label(idx: int, total: int) -> str:
    """Anna aterialle järkevä nimi sijainnin ja määrän mukaan."""
    if idx == 0:
        return "Aamupala"
    if idx == total - 1:
        return "Iltapala" if total >= 4 else "Päivällinen"
    # Keskimmäiset: lounas ja päivällinen pääaterioina, muut välipaloja
    mid = total // 2
    if idx == mid:
        return "Lounas"
    if idx == total - 2 and total >= 4:
        return "Päivällinen"
    return "Välipala"


def meal_schedule(targets: dict, meals: int, wake: str | None = None,
                  sleep: str | None = None, training: str | None = None,
                  fasting_16_8: bool = False) -> list[dict]:
    """Jaksota päivän makrot aterioille kellonaikojen ja treenin mukaan.

    - Proteiini jaetaan tasaisesti (paras lihasten kannalta).
    - Hiilarit painottuvat treenin ympärille (ennen/jälkeen treenin enemmän).
    - Rasva painottuu treenistä kauempana oleviin aterioihin.
    - 16:8: syönti-ikkuna rajataan 8 tuntiin.
    """
    meals = max(2, min(8, meals))
    wake_min = _parse_clock(wake, 7 * 60)
    sleep_min = _parse_clock(sleep, 23 * 60)

    if fasting_16_8:
        eat_start = wake_min + 5 * 60   # esim. herää 7 -> syönti alkaa 12
        eat_end = eat_start + 8 * 60
    else:
        eat_start = wake_min + 60
        eat_end = sleep_min - 60
    if eat_end <= eat_start:
        eat_end = eat_start + 8 * 60

    # Ateria-ajat tasaisin välein syönti-ikkunassa
    if meals == 1:
        times = [(eat_start + eat_end) // 2]
    else:
        step = (eat_end - eat_start) / (meals - 1)
        times = [round(eat_start + step * i) for i in range(meals)]

    training_min = _parse_clock(training, None) if training else None

    # Hiilaripainot: treenin ympärillä isommat
    carb_w = [1.0] * meals
    pre_idx = post_idx = None
    if training_min is not None:
        before = [(i, t) for i, t in enumerate(times) if t <= training_min]
        after = [(i, t) for i, t in enumerate(times) if t >= training_min]
        if before:
            pre_idx = max(before, key=lambda x: x[1])[0]
            carb_w[pre_idx] = 1.6
        if after:
            post_idx = min(after, key=lambda x: x[1])[0]
            carb_w[post_idx] = 1.8

    carb_w_sum = sum(carb_w)
    # Rasvapainot: hiilaripainojen käänteisarvo (rasvaa pois treeniaterioista)
    fat_w = [1.0 / w for w in carb_w]
    fat_w_sum = sum(fat_w)

    total_p = targets["protein_g"]
    total_c = targets["carbs_g"]
    total_f = targets["fat_g"]

    plan = []
    for i in range(meals):
        p = round(total_p / meals)
        c = round(total_c * carb_w[i] / carb_w_sum)
        f = round(total_f * fat_w[i] / fat_w_sum)
        kcal = round(p * 4 + c * 4 + f * 9)
        note = ""
        if i == pre_idx:
            note = "ennen treeniä — enemmän hiilaria"
        elif i == post_idx:
            note = "treenin jälkeen — palautushiilarit + proteiini"
        plan.append({
            "time": _fmt_clock(times[i]),
            "label": _meal_label(i, meals),
            "kcal": kcal, "protein_g": p, "carbs_g": c, "fat_g": f,
            "note": note,
        })
    return plan


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
