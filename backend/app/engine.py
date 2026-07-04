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


def progression_increment(name: str | None = None, equipment: str | None = None,
                          category: str | None = None, is_main_lift: bool = False,
                          per_hand: bool = False) -> float:
    """Realistinen korotusaskel liikkeelle. Isoissa moninivelisissä ~2.5 kg,
    eristävissä ja pienissä liikkeissä ~1 kg — ei valtavia hyppyjä.

    Käsipainoliikkeissä (paino per käsi) askel on pienempi, koska käsipainot
    kasvavat usein 1–2 kg välein per käsi.
    """
    n = (name or "").lower()
    ISOLATION = ("hauis", "kääntö", "curl", "ojentaja", "sivunosto", "vipunosto",
                 "pohje", "pohkeet", "face", "prikaati", "drag", "flyes", "fly",
                 "lähennys", "loitonnus", "reisiojennus", "takareisikoukistus",
                 "kohotus", "puristus", "kyynärvarsi", "delt", "olkapää")
    if per_hand:
        return 1.0
    if any(k in n for k in ISOLATION):
        return 1.0
    # Isot moniniveliset / pääliikkeet
    if is_main_lift or any(k in n for k in ("kyykky", "penkki", "maasta", "mave",
                                            "pystypunnerrus", "soutu", "prässi",
                                            "jalkaprässi", "dippi", "leuanveto",
                                            "tempaus", "rinnalleveto")):
        return 2.5
    # Muut (koneet, taljat, keskikokoiset) — maltillinen askel
    return 1.25


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


def body_fat_navy(sex: str | None, height_cm: float | None, neck_cm: float | None,
                  waist_cm: float | None, hip_cm: float | None = None) -> float | None:
    """Arvioi rasva-% ympärysmitoista (U.S. Navy -kaava). Käytetään kun mitattua
    rasva-%:a ei ole annettu. Miehillä tarvitaan kaula + vyötärö + pituus,
    naisilla lisäksi lantio.
    """
    import math
    if not height_cm or not neck_cm or not waist_cm:
        return None
    female = (sex or "").lower().startswith("nain")
    try:
        if female:
            if not hip_cm:
                return None
            val = (495 / (1.29579 - 0.35004 * math.log10(waist_cm + hip_cm - neck_cm)
                          + 0.22100 * math.log10(height_cm)) - 450)
        else:
            if waist_cm <= neck_cm:
                return None
            val = (495 / (1.0324 - 0.19077 * math.log10(waist_cm - neck_cm)
                          + 0.15456 * math.log10(height_cm)) - 450)
    except (ValueError, ZeroDivisionError):
        return None
    if val <= 0 or val > 70:
        return None
    return round(val, 1)


def creatine_water_kg(bodyweight: float) -> float:
    """Kreatiinin sitoman lihasveden arvio (kg). ~1.1 % kehonpainosta, rajattu
    0.7–1.6 kg. Tämä on vettä lihaksissa — EI rasvaa — joten se kuuluu
    rasvattomaan massaan, ei rasvamassaan."""
    if not bodyweight or bodyweight <= 0:
        return 0.0
    return round(max(0.7, min(1.6, bodyweight * 0.011)), 2)


def body_composition(bodyweight: float, body_fat_pct: float, height_cm: float | None = None,
                     creatine: bool = False) -> dict:
    """Arvioi kehon koostumus painosta ja rasvaprosentista.

    Palauttaa rasvamassan, rasvattoman massan (lihakset+luut+vesi), FFMI:n
    (rasvattoman massan indeksi, jos pituus annettu) ja BMI:n.

    creatine: jos kreatiini on käytössä, osa painosta on lihasten sitomaa vettä.
    Se EI ole rasvaa, joten rasvamassa lasketaan painosta josta vesi on poistettu
    ja vesi luetaan rasvattomaan massaan. Näin rasva-% ei näytä turhaan huonommalta.
    """
    cre = creatine_water_kg(bodyweight) if creatine else 0.0
    fat_mass = round((bodyweight - cre) * body_fat_pct / 100.0, 1)
    lean_mass = round(bodyweight - fat_mass, 1)
    out = {"fat_mass_kg": fat_mass, "lean_mass_kg": lean_mass}
    if creatine:
        out["creatine_water_kg"] = cre
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
    "Kokenut", "Piirimestaritaso", "SM-taso (kansallinen)", "Maailmanluokka (EM/MM)",
]
# Lyhyt selitys jokaiselle tasolle: mitä se käytännössä tarkoittaa.
LEVEL_MEANINGS = [
    "Vasta-alkaja: tekniikka opettelussa, voima nousee nopeasti.",
    "Säännöllinen treenaaja: perusvoima rakentunut, yli täysin treenamattoman.",
    "Keskitason harjoittelija: selvästi keskivertoa vahvempi.",
    "Edistynyt: vuosien johdonmukaisen treenin tulos, vahva tavallisessa salissa.",
    "Kokenut: erittäin vahva, lähestyy kilpatasoa omassa painoluokassaan.",
    "Piirimestaritaso: pärjäisi alueellisissa (piirin) kisoissa.",
    "SM-taso: kansallisen tason kilpailija.",
    "Maailmanluokka: EM/MM-tason nostaja, lähellä lajin huippua.",
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


def acwr_status(acute: float, chronic: float) -> dict | None:
    """Akuutti:krooninen kuormasuhde (ACWR). Vertaa kuluvan viikon kuormaa
    edeltävien viikkojen keskiarvoon. 'Sweet spot' ~0.8–1.3; yli 1.5 =
    kuormapiikki (kohonnut rasitus-/loukkaantumisriski), alle 0.8 = kevennys.
    """
    if not chronic or chronic <= 0:
        return None
    ratio = round(acute / chronic, 2)
    if ratio > 1.5:
        zone = "korkea"
    elif ratio < 0.8:
        zone = "matala"
    else:
        zone = "optimaalinen"
    return {"acwr": ratio, "zone": zone}


# Kuinka monta havaintoa tarvitaan ennen kuin tekijästä annetaan VAROITUS.
# Nojataan pitkän ajan keskiarvoon: yksittäinen huono päivä ei hälytä.
READINESS_MIN_BASE = 10   # HRV/leposyke: pitkän ajan vertailujakson havainnot
READINESS_MIN_RECENT = 3  # tuoreen jakson havainnot (ei yksittäistä päivää)


def readiness(hrv_recent=None, hrv_base=None, hrv_base_n=0, hrv_recent_n=0,
              rhr_recent=None, rhr_base=None, rhr_base_n=0, rhr_recent_n=0,
              sleep_recent=None, sleep_n=0, acwr: float | None = None,
              neg_feeling_ratio=None, feeling_n=0,
              nutrition_deficit_pct=None, nutrition_n=0) -> dict:
    """Palautumis-/valmiuspisteet (0–100) ja varoitukset ylikuormituksesta.

    Yhdistää sykevälivaihtelun (HRV), leposykkeen, unen, treenikuorman (ACWR),
    treenifiiliksen ja ravinnon. TÄRKEÄÄ: hälytys annetaan vain kun tekijällä on
    tarpeeksi pitkän ajan vertailudataa — yksittäinen huono päivä tai ohut data
    ei laukaise varoitusta. Vähäisellä datalla lasketaan pehmeämmin ja kehotetaan
    keräämään lisää.
    """
    score = 100.0
    warnings: list[str] = []
    factors: list[dict] = []
    thin = False  # onko jokin tekijä liian ohutdataista luotettavaan hälytykseen

    def enough(base_n, recent_n):
        return base_n >= READINESS_MIN_BASE and recent_n >= READINESS_MIN_RECENT

    if hrv_base and hrv_recent:
        pct = (hrv_recent - hrv_base) / hrv_base
        ok = enough(hrv_base_n, hrv_recent_n)
        if pct < 0:
            score -= min(30.0, -pct * 120) * (1.0 if ok else 0.4)
        if pct <= -0.08 and ok:
            warnings.append(f"HRV laskenut {round(-pct*100)}% pitkän ajan tasosta — merkki kertyneestä stressistä.")
        if not ok:
            thin = True
        factors.append({"name": "HRV", "recent": round(hrv_recent, 1), "baseline": round(hrv_base, 1),
                        "change_pct": round(pct * 100, 1), "enough_data": ok})

    if rhr_base and rhr_recent:
        pct = (rhr_recent - rhr_base) / rhr_base
        ok = enough(rhr_base_n, rhr_recent_n)
        if pct > 0:
            score -= min(25.0, pct * 100 * 2.5) * (1.0 if ok else 0.4)
        if pct >= 0.05 and ok:
            warnings.append(f"Leposyke koholla (+{round(pct*100)}%) pitkän ajan tasosta — keho ei ehkä ole palautunut.")
        if not ok:
            thin = True
        factors.append({"name": "Leposyke", "recent": round(rhr_recent, 1), "baseline": round(rhr_base, 1),
                        "change_pct": round(pct * 100, 1), "enough_data": ok})

    if sleep_recent is not None and sleep_n > 0:
        ok = sleep_n >= 4
        if sleep_recent < 7:
            score -= min(25.0, (7 - sleep_recent) * 10) * (1.0 if ok else 0.5)
        if sleep_recent < 6.5 and ok:
            warnings.append(f"Uni jäänyt lyhyeksi (~{round(sleep_recent,1)} h/yö) — palautuminen kärsii.")
        factors.append({"name": "Uni", "recent": round(sleep_recent, 1), "baseline": 8.0,
                        "change_pct": None, "enough_data": ok})

    if acwr is not None:
        if acwr > 1.5:
            score -= min(30.0, (acwr - 1.3) * 40)
            warnings.append(f"Treenikuorma piikissä (ACWR {acwr}) — kova nousu edellisviikkoihin nähden. "
                            "Harkitse kevennystä.")
        elif acwr > 1.3:
            score -= (acwr - 1.3) * 20
        factors.append({"name": "Kuormasuhde (ACWR)", "recent": acwr, "baseline": 1.0,
                        "change_pct": None, "enough_data": True})

    # Treenifiilis: usein huono fiilis auttaa datan keruussa (ei tarvitse muita mittareita)
    if neg_feeling_ratio is not None and feeling_n >= 3:
        score -= min(20.0, neg_feeling_ratio * 30)
        if neg_feeling_ratio >= 0.4:
            warnings.append(f"Treenifiilis ollut usein huono viime aikoina ({round(neg_feeling_ratio*100)}% treeneistä) "
                            "— kuuntele kehoa.")
        factors.append({"name": "Treenifiilis", "recent": f"{round(neg_feeling_ratio*100)}% huono",
                        "baseline": "0%", "change_pct": None, "enough_data": True})

    # Ravinto: vain jos dataa on tarpeeksi (moni ei kirjaa joka päivä)
    if nutrition_deficit_pct is not None and nutrition_n >= 5:
        if nutrition_deficit_pct > 0.10:
            score -= min(20.0, (nutrition_deficit_pct - 0.10) * 120)
        if nutrition_deficit_pct >= 0.25:
            warnings.append(f"Ravinto jäänyt selvästi tarpeen alle (~{round(nutrition_deficit_pct*100)}% vajaus) "
                            "— liian vähäinen syönti heikentää palautumista.")
        factors.append({"name": "Ravinto", "recent": f"−{round(nutrition_deficit_pct*100)}% tarpeesta",
                        "baseline": "tarve", "change_pct": None, "enough_data": True})

    score = int(max(0, min(100, round(score))))
    if not factors:
        status = "ei dataa"
    elif score >= 80:
        status = "hyvä"
    elif score >= 60:
        status = "kohtalainen"
    else:
        status = "varo — kohonnut ylikuormitusriski"
    return {"score": score, "status": status, "warnings": warnings, "factors": factors,
            "thin_data": thin}


def detrained_1rm(best_ever_1rm: float, weeks_since: float) -> float:
    """Arvioi realistinen tämänhetkinen 1RM kun liikettä ei ole tehty hetkeen.

    Voima säilyy hyvin ~2 viikkoa, sitten laskee vähitellen. Lihasmuisti pitää
    paljon tallessa, joten lasku ei ole rajaton — mutta hyvin pitkällä (vuosien)
    tauolla pohja laskee edelleen maltillisesti.
      ~2 vk: 100 %, ~10 vk: ~90 %, ~½ v: ~71 %, ~1 v: ~62 %, ~2 v: ~60 %,
      ~5 v: ~52 %, ~9 v: ~45 % (pohja).
    """
    if not best_ever_1rm or best_ever_1rm <= 0:
        return 0.0
    # Ensimmäinen vaihe: nopeahko lasku kohti ~60 % kahden vuoden aikana
    factor = max(0.6, min(1.0, 1.0 - 0.012 * max(0.0, weeks_since - 2)))
    # Toinen vaihe: hyvin pitkä tauko (yli ~2 v) painaa pohjaa vielä alas, pohja 0.45
    if weeks_since > 104:
        factor = max(0.45, factor - 0.0005 * (weeks_since - 104))
    return round(best_ever_1rm * factor, 1)


def comeback_plan(best_ever_1rm: float, weeks_since: float) -> dict | None:
    """Paluusuunnitelma vanhaan ennätykseen: realistinen lähtöpaino ja arvio
    kuinka kauan huipun saavuttaminen uudelleen kestää (lihasmuisti nopeuttaa,
    mutta mitä isompi menetys ja pidempi tauko, sitä pidempi paluu).
    """
    if not best_ever_1rm or best_ever_1rm <= 0:
        return None
    current = detrained_1rm(best_ever_1rm, weeks_since)
    # Aloita maltillisesti: ~5 toiston työpaino varastolla 3 (ei maksimeja heti)
    start = round_to_increment(weight_for_reps(current, 5, 3) * 0.97)
    lost_pct = round((1 - current / best_ever_1rm) * 100)
    # Paluuaika: skaalautuu menetetyn osuuden mukaan (lihasmuisti nopeuttaa,
    # mutta ison menetyksen takaisin saaminen vie kuukausia). 4–52 vk.
    regain_weeks = int(max(4, min(52, round(lost_pct * 1.4))))
    return {
        "best_ever_1rm": round(best_ever_1rm, 1),
        "weeks_since": round(weeks_since, 1),
        "years_since": round(weeks_since / 52.0, 1),
        "estimated_current_1rm": current,
        "lost_pct": lost_pct,
        "suggested_start_kg": start,
        "regain_weeks": regain_weeks,
    }


def natural_ceiling(lift_key: str, bodyweight: float, sex: str | None = None) -> float | None:
    """Naturaalinostajan realistinen 1RM-katto liikkeelle (kg)."""
    if lift_key not in NATURAL_CEILINGS or not bodyweight or bodyweight <= 0:
        return None
    factor = FEMALE_FACTOR if (sex or "").lower().startswith("nain") else 1.0
    return round(NATURAL_CEILINGS[lift_key] * factor * bodyweight, 1)


# Väestön keskiarvo (TÄYSIN treenamaton aikuinen mies): 1RM / kehon paino.
# Maltilliset luvut: treenamaton ~80 kg mies vetää maasta ~65–70 kg, ei yli 100.
POPULATION_AVG = {"squat": 0.7, "bench": 0.5, "deadlift": 0.85, "ohp": 0.35}


def population_average(lift_key: str, bodyweight: float, sex: str | None = None) -> float | None:
    """Arvio mitä keskimääräinen (treenamaton) ihminen nostaa omassa painossaan."""
    if lift_key not in POPULATION_AVG or not bodyweight or bodyweight <= 0:
        return None
    factor = FEMALE_FACTOR if (sex or "").lower().startswith("nain") else 1.0
    return round(POPULATION_AVG[lift_key] * factor * bodyweight, 1)


# ---------- Kilpailutaso: yhteistulos, painoluokka, paikallinen→MM ----------
# IPF-tyyliset painoluokat (kg). Viimeinen = ylin luokka (yli edellisen).
WEIGHT_CLASSES_M = [59, 66, 74, 83, 93, 105, 120]
WEIGHT_CLASSES_F = [47, 52, 57, 63, 69, 76, 84]
COMP_LEVELS = ["Paikallinen", "SM (kansallinen)", "EM (Euroopan)", "MM (maailma)"]

# Yhteistulos / kehonpaino -kerroin kullakin tasolla, viitepainossa 83 kg.
# Raskaammilla kerroin pienenee (allometrinen skaalaus) — kuten oikeasti.
COMP_TOTAL_MULT = {
    # Voimanosto raw: kyykky + penkki + maastaveto (yhteistulos)
    "voimanosto": [5.5, 7.0, 8.0, 9.0],
    # Olympianostot: tempaus + rinnalleveto & työntö
    "olympia": [3.1, 3.9, 4.4, 4.8],
}
COMP_REF_BW = 83.0


def weight_class(bodyweight: float, sex: str | None = None) -> str | None:
    """Palauta IPF-tyylinen painoluokka (esim. '-83 kg' tai '+120 kg')."""
    if not bodyweight or bodyweight <= 0:
        return None
    classes = WEIGHT_CLASSES_F if (sex or "").lower().startswith("nain") else WEIGHT_CLASSES_M
    for c in classes:
        if bodyweight <= c:
            return f"-{c} kg"
    return f"+{classes[-1]} kg"


def competition_assessment(sport: str, total_kg: float, bodyweight: float,
                           sex: str | None = None) -> dict | None:
    """Arvioi yhteistuloksen kilpailutaso: painoluokka ja taso paikallisesta
    MM-tasoon, sekä kunkin tason rajatulos kiloina tällä kehonpainolla.

    Kertoimet skaalataan kehonpainon mukaan (raskaammilla pienempi total/kp).
    """
    mult = COMP_TOTAL_MULT.get(sport)
    if not mult or not bodyweight or bodyweight <= 0 or total_kg <= 0:
        return None
    female = (sex or "").lower().startswith("nain")
    sex_factor = FEMALE_FACTOR if female else 1.0
    # Allometrinen korjaus: kevyemmillä korkeampi total/kp, raskaammilla matalampi
    bw = max(50.0, min(170.0, bodyweight))
    scale = (COMP_REF_BW / bw) ** 0.33
    thresholds = [round(mn * sex_factor * scale * bodyweight, 1) for mn in mult]

    level_idx = -1
    for i, t in enumerate(thresholds):
        if total_kg >= t:
            level_idx = i
    level = COMP_LEVELS[level_idx] if level_idx >= 0 else "Harrastaja (alle kilpatason)"
    next_threshold = thresholds[level_idx + 1] if level_idx + 1 < len(thresholds) else None
    next_level = COMP_LEVELS[level_idx + 1] if level_idx + 1 < len(COMP_LEVELS) else None
    return {
        "sport": sport,
        "total_kg": round(total_kg, 1),
        "bodyweight": bodyweight,
        "weight_class": weight_class(bodyweight, sex),
        "level": level,
        "level_index": level_idx,
        "levels": COMP_LEVELS,
        "thresholds_kg": thresholds,
        "next_level": next_level,
        "next_threshold_kg": next_threshold,
        "to_next_kg": round(next_threshold - total_kg, 1) if next_threshold else None,
    }


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
        "level_meaning": LEVEL_MEANINGS[level_idx] if reached_first else "Alle aloittelijatason — jatka treeniä, taso nousee pian.",
        "ratio": round(ratio, 2),
        "next_level": STRENGTH_LEVELS[level_idx + 1] if level_idx < len(STRENGTH_LEVELS) - 1 else None,
        "next_threshold_kg": next_threshold_kg,
        "ceiling_kg": round(thresholds[-1] * bodyweight, 1),
        # Jokaisen 8 tason raja kiloina tällä kehonpainolla -> palkin asteikko
        "thresholds_kg": [round(t * bodyweight, 1) for t in thresholds],
    }


# Fysiikkatasot (8) rasvattoman massan indeksin (FFMI) mukaan. Miesten asteikko;
# naisille kynnyksiä lasketaan FEMALE_FFMI_OFFSETilla.
PHYSIQUE_LEVELS = [
    "Aloittelija", "Harrastaja", "Keskitaso", "Edistynyt",
    "Kokenut", "Eliitti (natural-huippu)", "Kilpataso", "IFBB Pro -luokka",
    "Mr. Olympia -taso",
]
# 8 kynnystä -> 9 tasoa. Viimeinen (Mr. Olympia) on huvin vuoksi lähes
# saavuttamaton naturaalisti — FFMI ~30+ nähdään vain lajin huipulla.
FFMI_THRESHOLDS = [18.0, 20.0, 22.0, 23.5, 25.0, 26.5, 28.0, 30.5]
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


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def backtest_forecast(history: list[tuple]) -> dict:
    """Walk-forward-taustatesti: käy data läpi pisteestä pisteeseen, ennusta
    joka kohdassa SEURAAVA piste vain siihenastisesta datasta ja mittaa osuiko.

    Kokoaa kahdesta virhejoukosta:
      - rate_ratio: kuinka lähelle mallin ennustama muutos osui todelliseen
        (mediaani toteuma/ennuste). >1 = malli aliarvioi (esim. geneettinen
        vaste), <1 = yliarvioi (plataa/hidas). Näin kaava oppii juuri tämän
        henkilön kehityksen luonteen.
      - error_scale: tyypillinen yhden askeleen ennustevirhe (kg per √viikko).
        Antaa EMPIIRISEN haarukan tulevaan: pienet ja tasaiset virheet -> kapea
        haarukka, iso hajonta -> leveä. Kapenee kun dataa on enemmän ja se on
        johdonmukaista.

    Vaatii vähintään ~4 pistettä ollakseen luotettava; muuten palauttaa neutraalin.
    """
    valid = sorted([(d, v) for d, v in history if v and v > 0], key=lambda p: p[0])
    if len(valid) < 4:
        return {"rate_ratio": 1.0, "error_scale": None, "n": 0}
    base = valid[0][0]
    pts = [((d - base).days, v) for d, v in valid]
    ratios, norm_errors = [], []
    for i in range(3, len(pts)):
        hist = pts[:i]
        last_day, last_v = hist[-1]
        recent = [p for p in hist if p[0] >= last_day - 84] or hist
        rate = max(0.0, _linear_rate(recent))  # per päivä, siihenastisesta datasta
        adx, adv = pts[i]
        dt = adx - last_day
        if dt <= 0:
            continue
        pred = last_v + rate * dt
        pg, ag = pred - last_v, adv - last_v
        if abs(pg) > 0.5:
            ratios.append(ag / pg)
        # Virhe normalisoituna √aikaan (satunnaiskulku): vertailukelpoinen per √vk
        norm_errors.append((adv - pred) / ((dt / 7.0) ** 0.5))
    rate_ratio = 1.0
    if len(ratios) >= 2:
        rate_ratio = max(0.5, min(1.6, round(_median(ratios), 2)))
    error_scale = None
    if len(norm_errors) >= 3:
        med = _median(norm_errors)
        mad = _median([abs(e - med) for e in norm_errors])
        error_scale = round(1.4826 * mad, 2) or round(_median([abs(e) for e in norm_errors]), 2)
    return {"rate_ratio": rate_ratio, "error_scale": error_scale, "n": len(norm_errors)}


def forecast_progress(
    history: list[tuple], horizon_weeks: int = 26, ceiling: float | None = None,
    bodyweight_trend_per_week: float = 0.0, confidence: float = 1.0,
    rate_calibration: float = 1.0, prior_best: float | None = None,
    error_scale: float | None = None,
) -> list[dict]:
    """Ennusta kehitys realistisesti vähenevällä tuotolla (data + malli).

    history: [(date, value)] (esim. arvioitu 1RM). Lähihistoriasta lasketaan
    viikkotahti (DATA), jota vaimennetaan kun arvo lähestyy fysiologista kattoa
    (MALLI/tutkimus). Painon lasku hidastaa tahtia ja laskee kattoa (max
    potentiaali skaalautuu painon mukaan). Pienempi data -> leveämpi haarukka.

    prior_best: aiempi henkilökohtainen huippu. Jos nykyinen on sen alle
    (paluu tauolta), paluu vanhaan huippuun on NOPEAA (lihasmuisti) ja vasta
    huipun ylityksen jälkeen haaste kasvaa (vähenevä tuotto kohti kattoa).
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

    # TÄRKEÄÄ: vähällä datalla / lyhyellä jaksolla lyhyt jyrkkä pätkä ei saa
    # ekstrapoloitua järjettömäksi. Kutista tahtia luottamuksen mukaan (enemmän
    # dataa & pidempi seuranta -> lähempänä todellista keskimääräistä tahtia) ja
    # rajaa realistiseen viikkokattoon (myös aloittelijalla on rajansa).
    rate_per_week *= (0.35 + 0.65 * max(0.0, min(1.0, confidence)))
    rate_cap = max(1.5, current * 0.04)  # ~4 %/vk tai väh. 1.5 kg/vk
    rate_per_week = min(rate_per_week, rate_cap)

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
        if prior_best and value < prior_best:
            # Lihasmuisti: paluu vanhaan huippuun on nopeaa (vain lievä vaimennus)
            step = rate_per_week * max(0.7, 1 - value / (prior_best * 1.15))
            value = min(prior_best, value + step)
        else:
            # Huipun ylityksen jälkeen: vähenevä tuotto kohti fysiologista kattoa
            damp = max(0.1, 1 - (value / ceiling))
            value = min(ceiling, value + rate_per_week * damp)
        gain = value - current
        if error_scale is not None:
            # EMPIIRINEN haarukka: taustatestin virheistä, kasvaa √ajan mukaan
            # (satunnaiskulku). Pohja mittauskohinalle. Johdonmukainen data ->
            # pieni error_scale -> kapea haarukka. Ei riipu heuristiikasta.
            spread = max(error_scale * (w ** 0.5), 0.02 * current, 0.12 * gain)
        else:
            # Ilman riittävää taustadataa: heuristiikka + datan niukkuus
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


# Kehon osien tasot (7 porrasta) ympärysmitta/pituus -suhteena. Kasvukohdille
# nouseva (isompi = parempi), vyötärölle käänteinen (pienempi = parempi).
BODYPART_LEVELS = [
    "Keskiverto", "Harrastaja", "Keskitaso", "Edistynyt",
    "Kokenut", "Eliitti (natural-huippu)", "IFBB Pro -luokka",
]
BODYPART_STANDARDS = {  # kasvukohdat: pituuskerroin nousevasti
    "hauis": [0.18, 0.20, 0.215, 0.23, 0.245, 0.26, 0.28],
    "rintakehä": [0.55, 0.59, 0.62, 0.65, 0.68, 0.71, 0.74],
    "reisi": [0.30, 0.32, 0.34, 0.36, 0.38, 0.40, 0.42],
    "pohje": [0.19, 0.205, 0.215, 0.225, 0.235, 0.245, 0.255],
    "hartia": [0.60, 0.63, 0.66, 0.69, 0.72, 0.75, 0.78],
    "kyynärvarsi": [0.155, 0.165, 0.175, 0.185, 0.195, 0.205, 0.215],
    "forkku": [0.155, 0.165, 0.175, 0.185, 0.195, 0.205, 0.215],
}
WAIST_STANDARD = [0.52, 0.50, 0.48, 0.46, 0.44, 0.42, 0.40]  # vyötärö: pienempi parempi

# Kuinka herkästi ympärysmitta paisuu rasvasta (0–1). Vyötärö/lantio eniten,
# raajat vähemmän. Käytetään "rasvakorjattu mitta" -arvioon.
SITE_FAT_SENS = {
    "hauis": 0.32, "rintakehä": 0.55, "reisi": 0.5, "pohje": 0.28,
    "hartia": 0.45, "kyynärvarsi": 0.22, "forkku": 0.22, "lantio": 0.7,
}
LEAN_REF_BF = {"m": 12.0, "f": 20.0}   # vertailurasva-% jolla mitta on "lihasta"


def fat_inflation_cm(site: str, value_cm: float, body_fat_pct: float | None,
                     sex: str | None = None) -> float:
    """Arvio kuinka monta cm ympärysmitasta on YLIMÄÄRÄISTÄ rasvaa (yli lean-
    viitearvon). Karkea anthropometrinen arvio — ei korvaa mittausta."""
    if not body_fat_pct or not value_cm:
        return 0.0
    female = (sex or "").lower().startswith("nain")
    ref = LEAN_REF_BF["f"] if female else LEAN_REF_BF["m"]
    sens = SITE_FAT_SENS.get((site or "").lower())
    if sens is None:
        return 0.0
    excess = max(0.0, body_fat_pct - ref)
    return round(value_cm * sens * (excess / 100.0), 1)


def bodypart_level(site: str, value_cm: float, height_cm: float | None,
                   sex: str | None = None, body_fat_pct: float | None = None) -> dict | None:
    """Luokittele kehon osa väestön keskiarvosta IFBB Pro -luokkaan pituuteen
    suhteutettuna. Vyötärö käänteisesti (pienempi vyötärö = korkeampi taso).

    body_fat_pct: jos annettu, arvioidaan kuinka paljon mitasta on rasvaa ja
    lasketaan "rasvakorjattu" taso — koska korkealla rasva-%:lla iso mitta ei
    tarkoita yhtä paljon lihasta (esim. leveä hartia/rinta voi olla rasvaa)."""
    if not height_cm or height_cm <= 0 or not value_cm:
        return None
    s = (site or "").lower()
    ratio = value_cm / height_cm
    female = (sex or "").lower().startswith("nain")

    if s == "vyötärö":
        thresholds = WAIST_STANDARD
        idx = -1
        for i, t in enumerate(thresholds):
            if ratio <= t:
                idx = i
        reached = ratio <= thresholds[0]
        avg_cm = round(thresholds[0] * height_cm, 1)
        top_cm = round(thresholds[-1] * height_cm, 1)
    elif s in BODYPART_STANDARDS:
        factor = FEMALE_FACTOR if female else 1.0  # naisilla pienemmät kerrat
        # huom: vain lievä skaalaus, ei yhtä jyrkkä kuin voimassa
        factor = 0.9 if female else 1.0
        thresholds = [t * factor for t in BODYPART_STANDARDS[s]]
        idx = -1
        for i, t in enumerate(thresholds):
            if ratio >= t:
                idx = i
        reached = ratio >= thresholds[0]
        avg_cm = round(thresholds[0] * height_cm, 1)
        top_cm = round(thresholds[-1] * height_cm, 1)
    else:
        return None

    out = {
        "site": site,
        "value_cm": value_cm,
        "level_index": idx if reached else -1,
        "level": BODYPART_LEVELS[idx] if reached else ("Yli keskiarvon (paljon vyötäröä)" if s == "vyötärö" else "Alle keskiarvon"),
        "ratio": round(ratio, 3),
        "population_avg_cm": avg_cm,
        "elite_cm": top_cm,
        "levels": BODYPART_LEVELS,
        "reversed": s == "vyötärö",
    }

    # Rasvakorjaus kasvukohdille: paljonko mitasta on rasvaa ja mikä taso olisi
    # rasvakorjatulla mitalla (rehellisempi lihasmäärän kuva korkealla rasva-%:lla)
    if s in BODYPART_STANDARDS and body_fat_pct:
        fat_cm = fat_inflation_cm(site, value_cm, body_fat_pct, sex)
        if fat_cm >= 0.2:
            lean_val = value_cm - fat_cm
            lean_ratio = lean_val / height_cm
            lidx = -1
            for i, t in enumerate(thresholds):
                if lean_ratio >= t:
                    lidx = i
            out["fat_inflation_cm"] = fat_cm
            out["lean_adjusted_cm"] = round(lean_val, 1)
            out["lean_level_index"] = lidx
            out["lean_level"] = BODYPART_LEVELS[lidx] if lidx >= 0 else "Alle keskiarvon"
            out["fat_note"] = (f"Rasva-% ({round(body_fat_pct)} %) nostaa mittaa ~{fat_cm} cm. "
                               f"Rasvakorjattu ~{round(lean_val,1)} cm → lihaksellinen taso: "
                               f"{out['lean_level']}.")
    return out


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
                         floor: float | None = None, rate_calibration: float = 1.0,
                         bodyweight_trend_per_week: float = 0.0, bodyweight: float | None = None,
                         body_fat_pct: float | None = None, site: str | None = None) -> list[dict]:
    """Ennusta ympärysmitan kehitys datavetoisesti (kasvu JA lasku).

    Perustuu ENSISIJAISESTI omaan lähitrendiin (adaptoituu). Kasvu tasaantuu
    pehmeästi kohti pituuspohjaista kattoa, lasku kohti pohjaa.

    LISÄKSI painon muutos kytketään mukaan: jos rasva-% on korkea ja paino
    laskee, ympärysmitat (etenkin vyötärö, mutta myös reisi/rinta) pienenevät
    osittain rasvan mukana — ennuste näkee tämän. Jos paino pysyy vakiona,
    lisätermi on ~0 ja ennuste seuraa omaa trendiä (odotus: pysyy samana).
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

    # Rasvavetoinen lisämuutos/vk: paino muuttuu -> osa mitasta seuraa (enemmän
    # rasvaa & herkempi kohta -> suurempi vaikutus). Vyötärölle korkein herkkyys.
    fat_step_week = 0.0
    if bodyweight and bodyweight > 0 and body_fat_pct and bodyweight_trend_per_week:
        s = (site or "").lower()
        sens = 0.9 if s == "vyötärö" else SITE_FAT_SENS.get(s, 0.4)
        fat_factor = max(0.0, min(1.4, (body_fat_pct - 8) / 25.0))
        frac = bodyweight_trend_per_week / bodyweight
        fat_step_week = current * frac * sens * fat_factor  # sama etumerkki kuin painomuutos

    # Pehmeä katto: ei rajoita jos data jo ylittää sen (huomioi geneettisesti
    # lahjakkaat / aineet). Pieni puskuri jotta ennuste ei jää heti seinään.
    if ceiling is not None:
        ceiling = max(ceiling, current * 1.03)

    from datetime import timedelta
    out = []
    value = current
    for w in range(1, horizon_weeks + 1):
        # Oma trendi + rasvavetoinen osa (molemmat tasaantuvat ajan myötä)
        step = (rate_per_week + fat_step_week * 0.7) * (0.96 ** w)
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


def baseline_tdee(bodyweight: float, height_cm: float | None, age: int | None,
                  sex: str | None, training_days_per_week: float) -> float | None:
    """Arvioi ylläpitokalorit (TDEE) ennen kuin syöntidataa on.

    BMR Mifflin–St Jeor -kaavalla + aktiivisuuskerroin, joka kasvaa
    viikoittaisten treenien mukaan. Näin "0 treeniä viikossa" antaa selvästi
    matalamman tarpeen kuin "5 treeniä viikossa" — tarve muuttuu treenimäärän
    mukaan, kuten pitääkin.
    """
    if not bodyweight or bodyweight <= 0:
        return None
    td = max(0.0, min(7.0, training_days_per_week or 0.0))
    # Aktiivisuus: 0 treeniä -> 1.25 (arki), joka treeni nostaa ~0.06
    activity = 1.25 + 0.06 * td
    if height_cm and age:
        s = -161.0 if (sex or "").lower().startswith("nain") else 5.0
        bmr = 10.0 * bodyweight + 6.25 * height_cm - 5.0 * age + s
        return round(bmr * activity, 0)
    # Varakaava ilman pituutta/ikää: ~24 kcal/kg BMR * aktiivisuus
    return round(bodyweight * 24.0 * activity, 0)


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


def assumed_working_rir(sets_at_weight: int) -> float:
    """Oletettu varasto (RIR) työsarjalle kun sitä ei ole kirjattu.

    Tärkeää: esim. 4x5 EI ole 5 toiston maksimi — ekoissa sarjoissa on varaa,
    eikä ensimmäistä sarjaa viety uupumukseen. Jos varastoa ei merkitä, sitä
    EI saa olettaa nollaksi, koska se aliarvioi 1RM:n. Mitä useampi sarja
    samalla painolla, sitä enemmän varaa työsarjoissa oli.

      1 sarja  -> 0.0  (todennäköisesti maksimiyritys / AMRAP)
      2 sarjaa -> 1.0
      3 sarjaa -> 2.0
      4+ sarjaa-> 2.5
    """
    return {1: 0.0, 2: 1.0, 3: 2.0}.get(sets_at_weight, 2.5)


def best_1rm_from_sets(sets: list[dict]) -> dict | None:
    """Palauta paras arvioitu 1RM joukosta sarjoja.

    sets: [{"weight": .., "reps": .., "rir": .. , "completed": bool}, ...]
    Vain suoritetut (completed) ja toistoja sisältävät sarjat huomioidaan.

    Jos sarjan varastoa (RIR) ei ole kirjattu, se päätellään sen mukaan kuinka
    monta sarjaa samalla painolla tehtiin (työsarjoissa on varaa, ei nollaa).
    """
    # Montako suoritettua sarjaa kullakin painolla -> oletusvaraston pohja
    counts: dict[float, int] = {}
    for s in sets:
        if not s.get("completed", True):
            continue
        reps = int(s.get("reps", 0))
        weight = float(s.get("weight", 0))
        if reps <= 0 or weight <= 0:
            continue
        counts[weight] = counts.get(weight, 0) + 1

    best = None
    for s in sets:
        if not s.get("completed", True):
            continue
        reps = int(s.get("reps", 0))
        weight = float(s.get("weight", 0))
        if reps <= 0 or weight <= 0:
            continue
        rir = s.get("rir")
        if rir is None:
            rir = assumed_working_rir(counts.get(weight, 1))
            assumed = True
        else:
            assumed = False
        e = estimate_1rm(weight, reps, rir)
        if best is None or e > best["estimated_1rm"]:
            best = {
                "estimated_1rm": round(e, 1),
                "weight": weight,
                "reps": reps,
                "rir": s.get("rir"),
                "assumed_rir": round(rir, 1) if assumed else None,
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


# ---------- Lihasaluekartta: mihin kukin liike osuu ja kuinka paljon ----------
# Jokainen liike kuormittaa useaa aluetta osuuskertoimella (1.0 = pääkohde,
# 0.5 = merkittävä sivukuorma, 0.2-0.3 = kevyt sivukuorma). Näin esim. penkki
# kerryttää myös ojentajien ja etuolkapään viikkovolyymiä, taljavedot hauista
# ja kyynärvarsia, kyykyt pakaroita ja pohkeita.
MUSCLE_AREAS = [
    "rinta", "yläselkä", "alaselkä", "olkapäät", "hauis", "ojentajat",
    "kyynärvarret", "etureidet", "takareidet", "pakarat", "pohkeet", "keskivartalo",
]

# Säännöt käydään järjestyksessä; ensimmäinen osuma voittaa (tarkin ensin).
_MUSCLE_RULES = [
    (("pystypunnerrus", "olkapääprässi"), {"olkapäät": 1, "ojentajat": 0.5, "keskivartalo": 0.2}),
    (("kapea penkki",), {"ojentajat": 1, "rinta": 0.6, "olkapäät": 0.4}),
    (("vinopenkki",), {"rinta": 1, "olkapäät": 0.5, "ojentajat": 0.45}),
    (("penkkipunnerrus", "rintaprässi"), {"rinta": 1, "ojentajat": 0.5, "olkapäät": 0.35}),
    (("dippi",), {"rinta": 0.8, "ojentajat": 1, "olkapäät": 0.3}),
    # Ojentajaliikkeet ENNEN yleistä punnerrus-sääntöä ("ojentajan punnerrus",
    # "ranskalainen punnerrus" ja "taljapunnerrus" ovat ojentajaliikkeitä).
    (("ranskalainen", "skull", "kickback", "ojentaja", "taljapunnerrus"), {"ojentajat": 1}),
    # Takaolkapää ENNEN pec deck / flyes -sääntöä (reverse pec deck on takaolkapääliike).
    (("face pull", "kasvoille", "takaolkapää", "vipunostot taakse", "reverse"), {"olkapäät": 0.8, "yläselkä": 0.5}),
    (("flyes", "vipunostot rinnalle", "pec deck", "taljaristikko", "crossover"), {"rinta": 1, "olkapäät": 0.2}),
    (("punnerrus",), {"rinta": 1, "ojentajat": 0.5, "olkapäät": 0.3, "keskivartalo": 0.3}),
    # Heilautukset ovat lantiosaranaliikkeitä (takaketju), eivät etureisiliikkeitä.
    (("heilautus", "swing"), {"pakarat": 1, "takareidet": 0.8, "alaselkä": 0.6, "keskivartalo": 0.3, "olkapäät": 0.2}),
    (("romanialainen", "takareisikoukistus", "jalkojen koukistus"), {"takareidet": 1, "pakarat": 0.6, "alaselkä": 0.4}),
    (("maastaveto",), {"pakarat": 1, "takareidet": 0.8, "alaselkä": 1, "yläselkä": 0.6, "kyynärvarret": 0.6, "etureidet": 0.4, "keskivartalo": 0.4}),
    (("tempaus", "rinnalleveto", "työntö telineestä"), {"etureidet": 0.8, "takareidet": 0.5, "pakarat": 0.8, "alaselkä": 0.8, "yläselkä": 0.6, "olkapäät": 0.6, "kyynärvarret": 0.4, "keskivartalo": 0.5, "pohkeet": 0.3}),
    (("askelkyykky", "bulgarian", "goblet", "käsipainokyykky"), {"etureidet": 1, "pakarat": 0.8, "takareidet": 0.3, "pohkeet": 0.2, "keskivartalo": 0.3}),
    (("kyykky", "jalkaprässi", "hack"), {"etureidet": 1, "pakarat": 0.7, "takareidet": 0.25, "alaselkä": 0.25, "pohkeet": 0.1}),
    (("reisiojennus", "jalkojen ojennus"), {"etureidet": 1}),
    (("lantionnosto", "pakaralaite", "lonkan ojennus"), {"pakarat": 1, "takareidet": 0.4}),
    (("lähennys",), {"etureidet": 0.4, "pakarat": 0.2}),
    (("loitonnus",), {"pakarat": 0.8}),
    (("pohje", "pohkeet", "pohjenousu"), {"pohkeet": 1}),
    (("selän ojennus",), {"alaselkä": 1, "pakarat": 0.5, "takareidet": 0.4}),
    (("leuanveto", "ylätalja"), {"yläselkä": 1, "hauis": 0.5, "kyynärvarret": 0.4, "olkapäät": 0.15}),
    (("pystysoutu",), {"olkapäät": 0.9, "yläselkä": 0.4, "hauis": 0.2, "kyynärvarret": 0.3}),
    (("soutu", "alatalja", "t-tanko"), {"yläselkä": 1, "hauis": 0.4, "kyynärvarret": 0.35, "alaselkä": 0.25, "olkapäät": 0.25}),
    (("sivunosto", "vipunostot sivulle", "taljavipunostot", "etunosto"), {"olkapäät": 1}),
    (("vasarakääntö", "zottman"), {"hauis": 1, "kyynärvarret": 0.6}),
    (("hauiskääntö", "curl", "scott", "spider", "keskitetty", "taljahauis"), {"hauis": 1, "kyynärvarret": 0.4}),
    (("ranneväännöt", "kyynärvarsi"), {"kyynärvarret": 1}),
    (("vatsarutistus", "vatsa", "lankku", "plank", "jalannosto", "rutistus"), {"keskivartalo": 1}),
]

_MUSCLE_FALLBACK = {
    "rinta": {"rinta": 1, "ojentajat": 0.4, "olkapäät": 0.3},
    "selkä": {"yläselkä": 1, "hauis": 0.4, "kyynärvarret": 0.3},
    "jalat": {"etureidet": 0.8, "pakarat": 0.6, "takareidet": 0.4},
    "olkapäät": {"olkapäät": 1, "ojentajat": 0.2},
    "olkapää": {"olkapäät": 1, "ojentajat": 0.2},
    "hauis": {"hauis": 1, "kyynärvarret": 0.3},
    "ojentaja": {"ojentajat": 1},
    "kädet": {"hauis": 0.6, "ojentajat": 0.6, "kyynärvarret": 0.3},
    "pohkeet": {"pohkeet": 1},
    "keskivartalo": {"keskivartalo": 1},
    "vatsa": {"keskivartalo": 1},
    "olympia": {"etureidet": 0.8, "pakarat": 0.8, "alaselkä": 0.8, "yläselkä": 0.5,
                "olkapäät": 0.5, "takareidet": 0.5, "keskivartalo": 0.4},
}


def exercise_muscle_map(name: str | None, category: str | None = None,
                        muscle_group: str | None = None) -> dict:
    """Palauta liikkeen kuormitusjakauma lihasalueille {alue: kerroin}."""
    n = (name or "").lower()
    for keys, mapping in _MUSCLE_RULES:
        if any(k in n for k in keys):
            return dict(mapping)
    cat = (category or "").lower()
    if cat in _MUSCLE_FALLBACK:
        return dict(_MUSCLE_FALLBACK[cat])
    mg = (muscle_group or "").lower()
    for key, mapping in _MUSCLE_FALLBACK.items():
        if key in mg:
            return dict(mapping)
    return {}


# Viikkotavoite tehollisia sarjoja per alue (sisältää epäsuoran kuorman).
# Alle min = kehitys jää vajaaksi; yli max = palautuminen voi ylittyä.
MUSCLE_WEEKLY_TARGETS = {
    "rinta": (10, 20), "yläselkä": (10, 22), "alaselkä": (4, 12),
    "olkapäät": (8, 20), "hauis": (8, 18), "ojentajat": (8, 18),
    "kyynärvarret": (4, 15), "etureidet": (8, 18), "takareidet": (6, 16),
    "pakarat": (6, 18), "pohkeet": (6, 16), "keskivartalo": (4, 16),
}


# ---------- Kokemustaso: ennusteen kalibrointi kun omaa dataa on vähän ----------
# Aloittelija kehittyy nopeasti, kokenut hitaasti. Vaikutus painotetaan
# luottamuksen käänteisarvolla: kun omaa dataa kertyy, oma toteutunut tahti
# syrjäyttää taustaoletuksen kokonaan.
EXPERIENCE_RATE_FACTOR = {
    "aloittelija": 1.25,
    "jonkin_verran": 1.0,
    "kokenut": 0.75,
    "palaava": 1.1,
}


def experience_rate_calibration(experience: str | None, confidence: float) -> float:
    """Kerroin ennusteen tahtiin kokemustason mukaan, häipyy datan karttuessa."""
    f = EXPERIENCE_RATE_FACTOR.get(experience or "", 1.0)
    conf = max(0.0, min(1.0, confidence))
    return 1.0 + (f - 1.0) * (1.0 - conf)


# ---------- BIA-ankkuroitu rasva-%-arvio ----------
# Laitemittaus (InBody tms.) on luotettavin saatavilla oleva rasva-%-lukema.
# Sen jälkeen arvio päivittyy painon ja vyötärön muutoksista: vyötärö on
# vahvin rasvan muutoksen merkki (~0.9 kg rasvaa / cm), painonmuutoksesta
# tyypillisesti ~70 % on rasvaa kun treeni jatkuu. Näin "paino sama + vyötärö
# kapenee" -> rasva-% laskee (lihasta tilalle), ilman uutta laitemittausta.
FAT_KG_PER_WAIST_CM = 0.9
FAT_SHARE_OF_WEIGHT_CHANGE = 0.7


def bf_from_bia_anchor(anchor_bf_pct: float, anchor_weight: float | None,
                       current_weight: float | None,
                       waist_delta_cm: float | None = None,
                       sex: str | None = None) -> dict | None:
    """Arvioi nykyinen rasva-% BIA-ankkurista painon/vyötärön muutoksilla.

    Palauttaa {bf_pct, fat_change_kg, muscle_change_kg, basis}.
    basis: "anchor" (ei muutosdataa), "weight", "waist" tai "weight+waist".
    """
    if anchor_bf_pct is None:
        return None
    if not anchor_weight or not current_weight:
        return {"bf_pct": round(anchor_bf_pct, 1), "fat_change_kg": 0.0,
                "muscle_change_kg": 0.0, "basis": "anchor"}
    fat_anchor = anchor_weight * anchor_bf_pct / 100.0
    d_w = current_weight - anchor_weight
    est_from_weight = FAT_SHARE_OF_WEIGHT_CHANGE * d_w
    if waist_delta_cm is not None:
        est_from_waist = FAT_KG_PER_WAIST_CM * waist_delta_cm
        # Vyötärö on informatiivisempi -> 2/3 paino, koska se erottaa
        # rasvan ja lihaksen (paino ei erota).
        d_fat = (est_from_weight + 2.0 * est_from_waist) / 3.0
        basis = "weight+waist" if abs(d_w) > 0.05 else "waist"
    else:
        d_fat = est_from_weight
        basis = "weight" if abs(d_w) > 0.05 else "anchor"
    # Rasvamuutos ei voi ylittää kokonaispainon muutosta järjettömästi:
    # rajaa fysiologisesti järkevään ikkunaan.
    d_fat = max(d_w - 0.6 * abs(d_w) - 1.5, min(d_fat, d_w + 0.6 * abs(d_w) + 1.5))
    fat_now = fat_anchor + d_fat
    floor_pct = 5.0 if sex == "mies" else 12.0
    bf = max(floor_pct, min(60.0, fat_now / current_weight * 100.0))
    fat_now = bf / 100.0 * current_weight
    return {
        "bf_pct": round(bf, 1),
        "fat_change_kg": round(fat_now - fat_anchor, 1),
        "muscle_change_kg": round(d_w - (fat_now - fat_anchor), 1),
        "basis": basis,
    }


# ---------- Ruoan laadun monipäiväinen arvio ----------
# Kun samat epäedulliset makrot toistuvat useana päivänä (vähän proteiinia,
# paljon herkkuja, vähän kasviksia), järjestelmä ehdottaa järkevämpää
# lähestymistä. Huono ruoka ei näy vain vaa'assa: se voi selittää väsyneet
# treenit, kehityksen pysähtymisen ja rasvan kertymisen. Arvio annetaan vain
# kun kirjattuja päiviä on tarpeeksi (data edellä).
def nutrition_quality(style: dict | None, bodyweight: float | None,
                      goal: str = "maintain") -> dict | None:
    """Pisteytä toteutunut syömistyyli (0–100) ja anna järkevämpi lähestymistapa.

    style: _macro_style-tyyppinen dict (protein_g, fat_g, carb_share, fat_share,
    treat_share, veg_g, kcal, n_days). Palauttaa None jos dataa liian vähän.
    """
    if not style or not bodyweight or style.get("n_days", 0) < 5:
        return None
    score = 100.0
    issues = []
    p_per_kg = style["protein_g"] / bodyweight
    f_per_kg = style["fat_g"] / bodyweight
    treat = style.get("treat_share", 0.0)
    veg = style.get("veg_g", 0.0)

    if p_per_kg < 1.2:
        score -= 24
        issues.append({"key": "protein", "severity": "high",
                       "text": f"Proteiinia vain ~{style['protein_g']} g/pv (~{p_per_kg:.1f} g/kg). "
                               "Treenaavalle tavoite ~1.6–2.2 g/kg. Tämä hidastaa palautumista ja "
                               "lihasten kehitystä — helppoja lisiä: rahka, raejuusto, kana, tonnikala, skyr."})
    elif p_per_kg < 1.6:
        score -= 10
        issues.append({"key": "protein", "severity": "med",
                       "text": f"Proteiini ~{p_per_kg:.1f} g/kg — hieman alle optimin (1.6–2.2 g/kg). "
                               "Lisää yksi proteiinilähde per ateria."})
    if treat >= 0.35:
        score -= 30
        issues.append({"key": "treats", "severity": "high",
                       "text": f"Herkut ja alkoholi ovat ~{round(treat*100)} % kaloreistasi — tämä on iso osuus. "
                               "Ne tuovat paljon energiaa mutta vähän ravinteita: seuraus on usein huono "
                               "palautuminen, väsyneet treenit ja rasvan kertyminen. Pudota ~10–15 %:iin."})
    elif treat >= 0.25:
        score -= 16
        issues.append({"key": "treats", "severity": "med",
                       "text": f"Herkut/alkoholi ~{round(treat*100)} % kaloreista — hieman paljon. "
                               "Vaihda osa proteiiniin ja hedelmiin, niin tavoite pysyy helpommin."})
    if veg < 150:
        score -= 18
        issues.append({"key": "veg", "severity": "high",
                       "text": f"Kasviksia/hedelmiä vain ~{round(veg)} g/pv — tavoite ~500 g/pv. "
                               "Kuitu ja vitamiinit tukevat vatsaa, kylläisyyttä ja palautumista."})
    elif veg < 300:
        score -= 10
        issues.append({"key": "veg", "severity": "med",
                       "text": f"Kasviksia ~{round(veg)} g/pv — nosta kohti 500 g. Lisää jotain vihreää joka aterialle."})
    if f_per_kg < 0.6:
        score -= 10
        issues.append({"key": "fat", "severity": "med",
                       "text": f"Rasvaa vain ~{f_per_kg:.1f} g/kg — hormonitoiminta tarvitsee ~0.8–1 g/kg. "
                               "Lisää pähkinöitä, oliiviöljyä, lohta tai avokadoa."})
    if goal == "cut" and style.get("carb_share", 0) > 0.55 and p_per_kg < 1.8:
        score -= 8
        issues.append({"key": "carbs_cut", "severity": "low",
                       "text": "Hiilarit yli puolet kaloreista dieetillä — proteiinin nosto hiilarin tilalle "
                               "auttaa kylläisyyteen ja lihasten säilymiseen."})

    score = int(max(0, min(100, round(score))))
    if score >= 75:
        level, label = "hyva", "Ruokavalio on kunnossa"
    elif score >= 50:
        level, label = "kohtalainen", "Ruokavaliossa on parannettavaa"
    else:
        level, label = "heikko", "Ruokavalio kaipaa selkeää korjausta"

    # Energiataso-/palautumislippu: toistuva huono ruoka verottaa treenejä
    energy_flag = (treat >= 0.3) or (p_per_kg < 1.2) or (veg < 150)
    energy_note = None
    if energy_flag:
        energy_note = ("Tämäntyyppinen ruokavalio voi selittää monta asiaa: väsyneet treenit, "
                       "kehityksen tyssäämisen ja sen ettei ylläpito toteudu (rasvan kertymisen riski). "
                       "Laadun korjaus näkyy usein nopeasti energiassa ja treeneissä.")

    # Järkevämpi lähestymistapa: 1–2 tärkeintä asiaa tavoitteen mukaan
    top = [i for i in issues if i["severity"] == "high"][:2] or issues[:1]
    if top:
        focus = {"protein": "nosta proteiini joka aterialle",
                 "treats": "puolita herkut/alkoholi",
                 "veg": "lisää kasviksia ~500 g/pv",
                 "fat": "lisää terveitä rasvoja",
                 "carbs_cut": "siirrä osa hiilareista proteiiniin"}
        parts = [focus.get(i["key"]) for i in top if focus.get(i["key"])]
        goal_txt = {"cut": "Dieetillä", "bulk": "Massalla", "maintain": "Ylläpidossa"}.get(goal, "")
        better_approach = (f"{goal_txt} tärkein korjaus: " + " ja ".join(parts) +
                           ". Pidä muu ennallaan — pienet muutokset riittävät kun ne toistuvat.")
    else:
        better_approach = "Ruokavalio tukee tavoitettasi hyvin — jatka samaan malliin."

    return {
        "available": True, "score": score, "level": level, "label": label,
        "n_days": style["n_days"], "issues": issues,
        "energy_flag": energy_flag, "energy_note": energy_note,
        "better_approach": better_approach,
    }


def today_food_advice(kcal_today: float, protein_today: float, treat_kcal_today: float,
                      target_kcal: float | None, target_protein: float | None) -> dict | None:
    """Saman päivän korjaava ohjaus: jos päivä on jo mennyt herkkuvoittoiseksi tai
    yli/ali tavoitteen, ehdota konkreettisesti mitä loppupäivänä ja huomenna kannattaa
    tehdä. Ei nolaa yksittäisestä herkusta — reagoi vasta kun päivä selvästi vinossa."""
    if kcal_today <= 0:
        return None
    tips = []
    over = (target_kcal and kcal_today > target_kcal + 300)
    treat_share = treat_kcal_today / kcal_today if kcal_today else 0
    low_protein = (target_protein and protein_today < target_protein * 0.6)

    if treat_share >= 0.3 and treat_kcal_today >= 400:
        tips.append("Herkkuja kertyi jo reilusti — jätä loppupäivä herkuitta ja painota proteiinia "
                    "ja kasviksia (kana, rahka, tonnikala, kananmuna, salaatti).")
    if over:
        tips.append(f"Päivä on jo ~{round(kcal_today - target_kcal)} kcal yli tavoitteen. Kevennä "
                    "loppupäivän ateriat proteiiniin ja kasviksiin (vähän rasvaa/hiilaria) ja juo vettä.")
        tips.append("Tasoita huominen: pidä se hieman tavoitteen alle — viikon keskiarvo ratkaisee, "
                    "ei yksittäinen päivä. Yksi runsas päivä ei pilaa mitään jos muut ovat kunnossa.")
    if low_protein:
        need = round(target_protein - protein_today)
        tips.append(f"Proteiinia puuttuu vielä ~{need} g tavoitteesta — lisää illaksi esim. raejuustoa, "
                    "rahkaa, kanaa tai heraproteiinia.")
    if not tips:
        return None
    return {"tips": tips[:3]}


def waist_weight_direction(weight_change_kg_month: float | None,
                           waist_change_cm_month: float | None,
                           has_enough: bool) -> dict | None:
    """Kuukauden mittainen vyötärö+paino-tuomio. EI yliherkkä: pieni heilahdus
    (turvotus, mittaustarkkuus) ei hälytä. Selvä signaali = paino JA vyötärö
    nousevat yhdessä kuukauden aikana -> väärä suunta, nopeat korjaukset.

    Vaatii tarpeeksi dataa (has_enough): muuten yksi mittaus ei kerro suuntaa.
    """
    if not has_enough or weight_change_kg_month is None or waist_change_cm_month is None:
        return None
    w = weight_change_kg_month
    waist = waist_change_cm_month
    # Väärä suunta: vyötärö +>=2 cm/kk JA paino noussut (>=0.8 kg/kk) -> rasvaa,
    # ei turvotusta (turvotus ei nostaisi molempia johdonmukaisesti kuukaudessa).
    if waist >= 2.0 and w >= 0.8:
        return {"status": "bad", "title": "Suunta kääntynyt väärään — rasvaa kertyy",
                "text": (f"Kuukaudessa vyötärö +{waist:.1f} cm ja paino +{w:.1f} kg. Kun MOLEMMAT "
                         "nousevat yhtä aikaa, kyse ei ole turvotuksesta vaan rasvan kertymisestä. "
                         "Nopeat korjaukset: leikkaa herkut/alkoholi puoleen, nosta proteiini ja "
                         "kasvikset, lisää arkiaskeleita/kevyttä kardiota, ja tarkista annoskoot. "
                         "Tartu nyt — kuukausi lisää samaa on jo useampi kilo."),
                "action": True}
    # Hyvä: vyötärö kaventuu, paino vakaa/nousee maltilla -> koostumus paranee
    if waist <= -1.0 and w <= 1.0:
        return {"status": "good", "title": "Suunta oikea — koostumus paranee",
                "text": (f"Kuukaudessa vyötärö {waist:.1f} cm ja paino {w:+.1f} kg — hyvä merkki: "
                         "rasva vähenee tai tilalle tulee lihasta. Jatka samaan malliin."),
                "action": False}
    # Lievä nousu molemmissa mutta alle hälytysrajan -> seuranta, ei paniikkia
    if waist >= 1.0 and w >= 0.3:
        return {"status": "watch", "title": "Pidä silmällä",
                "text": (f"Vyötärö +{waist:.1f} cm ja paino +{w:.1f} kg kuukaudessa — vielä maltillista "
                         "eikä hälytä (voi olla osin normaalia vaihtelua). Jos sama jatkuu ensi kuun, "
                         "kevennä hieman ruokaa. Seuraa muutamaa mittausta lisää ennen isoja muutoksia."),
                "action": False}
    return None


# ---------- Alkoholin vaikutusten seuranta (tutkimuspohjainen) ----------
# Idea: ei absolutistisia kaavoja vaan yleinen ymmärrys. Keho sietää pieniä
# määriä silloin tällöin paremmin kuin ison kerta-annoksen (lauantai/juhannus).
# Seurataan puhtaan alkoholin grammoja, 30 pv kuormaa ja OMAA mitattua vastetta
# (uni/HRV/leposyke krapula-aamuina vs. selvinä). Vakioannos = 12 g.
STANDARD_DRINK_G = 12.0

# Kertakäytön binge-raja (NIAAA ~5/4 annosta): miehet ~60 g, naiset ~48 g.
def _binge_threshold(sex: str | None) -> float:
    return 48.0 if (sex or "").lower().startswith("nain") else 60.0


def _widmark_r(sex: str | None) -> float:
    return 0.55 if (sex or "").lower().startswith("nain") else 0.68


def alcohol_assessment(events: list, nights: dict, sex: str | None,
                       bodyweight: float | None, today) -> dict | None:
    """events: [(date, grams_alkoholia)] viim. 30 pv juomapäivät.
    nights: {date: {"hrv","rhr","sleep"}} viim. ~35 pv (aamun mittaukset).
    Palauttaa 30 pv kuorman, rytmiarvion, oman mitatun vasteen ja ohjeen."""
    from datetime import timedelta as _td
    if not events:
        return {"available": True, "any_use": False,
                "note": "Ei kirjattua alkoholia viim. 30 pv. Jos käytät, kirjaa juomat "
                        "niin näet miten se vaikuttaa uneen, sykkeeseen ja treeneihin."}
    # Yhdistä saman päivän annokset
    by_day: dict = {}
    for d, g in events:
        by_day[d] = by_day.get(d, 0.0) + g
    total_g = sum(by_day.values())
    drinking_days = len(by_day)
    drinks = total_g / STANDARD_DRINK_G
    binge_thr = _binge_threshold(sex)
    binge_days = sum(1 for g in by_day.values() if g >= binge_thr)
    max_session = max(by_day.values())
    weekly_drinks = round(drinks / 30 * 7, 1)

    # Rytmiarvio: sama kokonaismäärä jaettuna on parempi kuin isot kertaryöpyt.
    avg_per_drinking_day = total_g / drinking_days
    if binge_days >= 2:
        pattern, pattern_txt = "binge", ("Painottuu isoihin kertaryöppyihin (humalajuominen). "
            "Tutkimusten mukaan iso kerta-annos rasittaa unta, sykettä ja palautumista selvästi "
            "enemmän kuin sama määrä jaettuna — juuri tämä on haitallisin rytmi.")
    elif avg_per_drinking_day <= binge_thr * 0.5 and binge_days == 0:
        pattern, pattern_txt = "spread", ("Käyttö on maltillista ja jakautunutta — keho sietää "
            "pieniä määriä silloin tällöin selvästi paremmin kuin kertaryöppyjä.")
    else:
        pattern, pattern_txt = "moderate", "Käyttö on kohtalaista; vältä isoja kertaryöppyjä."

    # OMA mitattu vaste: aamut juomapäivän JÄLKEEN vs. selvät aamut
    def _response(metric):
        after, base = [], []
        for d, m in nights.items():
            v = m.get(metric)
            if v is None:
                continue
            drank_prev = (d - _td(days=1)) in by_day
            (after if drank_prev else base).append(v)
        if len(after) >= 3 and len(base) >= 3:
            a = sum(after) / len(after); b = sum(base) / len(base)
            return {"after": round(a, 1), "sober": round(b, 1),
                    "delta_pct": round((a - b) / b * 100, 1) if b else None,
                    "n_after": len(after), "n_sober": len(base)}
        return None
    resp = {m: _response(m) for m in ("hrv", "rhr", "sleep")}
    resp = {k: v for k, v in resp.items() if v}
    measured_notes = []
    for m, r in resp.items():
        if m == "hrv" and r["delta_pct"] is not None and r["delta_pct"] <= -5:
            measured_notes.append(f"HRV on juomisen jälkeisinä aamuina ~{abs(r['delta_pct'])} % matalampi "
                                  f"({r['after']} vs. {r['sober']} selvinä) — palautuminen kärsii mitattavasti.")
        if m == "rhr" and r["delta_pct"] is not None and r["delta_pct"] >= 3:
            measured_notes.append(f"Leposyke on juomisen jälkeen ~{r['delta_pct']} % koholla "
                                  f"({r['after']} vs. {r['sober']}) — merkki kuormittuneesta palautumisesta.")
        if m == "sleep" and r["delta_pct"] is not None and r["delta_pct"] <= -5:
            measured_notes.append(f"Unta kertyy juomisen jälkeen ~{abs(r['delta_pct'])} % vähemmän "
                                  f"({r['after']} h vs. {r['sober']} h).")

    # Henkilökohtainen matalan vaikutuksen määrä (EI absoluuttinen raja):
    # ~0.3 g/kg/kerta on useimmilla vähäinen vaikutus; naisilla keho sietää
    # vähemmän (pienempi jakautumistilavuus). Ilmaistaan annoksina.
    low_impact_g = (bodyweight or 75) * (0.28 if (sex or "").lower().startswith("nain") else 0.35)
    low_impact_drinks = max(1, round(low_impact_g / STANDARD_DRINK_G))
    # Suurimman ryöpyn karkea "selviämisaika" (metabolia ~0.10 g/kg/h)
    hours_sober = round(max_session / ((bodyweight or 75) * 0.10), 1)

    # Kokonaisarvio
    if binge_days >= 2 or weekly_drinks >= 14:
        level, label = "korkea", "Käyttö vaikuttaa palautumiseen ja tuloksiin"
    elif weekly_drinks >= 7 or binge_days == 1:
        level, label = "kohtalainen", "Kohtalaista — kannattaa seurata vaikutuksia"
    else:
        level, label = "matala", "Maltillista käyttöä"

    guidance = (
        f"Sinun kokoisellesi (~{round(bodyweight or 75)} kg"
        f"{', nainen' if (sex or '').lower().startswith('nain') else ''}) noin "
        f"{low_impact_drinks} annosta (~{round(low_impact_g)} g) kerralla on tutkimuksen valossa "
        "vähäinen vaikutus, KUN se ei toistu tiheästi. Ratkaisevaa ei ole yksittäinen ilta vaan "
        "rytmi: pieniä määriä harvakseltaan on kehon kannalta paljon parempi kuin iso kertaryöppy. "
        "Vältä juomista treenipäivän iltana ja raskaan treenin aattona — alkoholi heikentää "
        "lihasten palautumista (proteiinisynteesi) ja seuraavan päivän suoritusta.")

    return {
        "available": True, "any_use": True,
        "total_g_30d": round(total_g), "drinks_30d": round(drinks, 1),
        "weekly_drinks": weekly_drinks, "drinking_days": drinking_days,
        "binge_days": binge_days, "binge_threshold_g": round(binge_thr),
        "max_session_g": round(max_session), "max_session_drinks": round(max_session / STANDARD_DRINK_G, 1),
        "hours_to_sober_max": hours_sober,
        "pattern": pattern, "pattern_note": pattern_txt,
        "measured_response": resp, "measured_notes": measured_notes,
        "low_impact_drinks": low_impact_drinks, "low_impact_g": round(low_impact_g),
        "level": level, "label": label, "guidance": guidance,
    }
