"""Valmentaja: seuraa kehitystä ja hälyttää ongelmista.

Tarkkailee pääliikkeiden kehitystä ja jos se pysähtyy, tutkii mahdollisia syitä
(uni, paino, palautuminen, kuormitus, volyymi, progressio) ja ehdottaa
korjausliikkeitä. Kaikki huomiot annetaan vain kun dataa on tarpeeksi — muuten
arvaus olisi epäluotettava. Toimii sekä aloittelijalle että kokeneelle.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import engine, models
from ..database import get_db
from .stats import (DEFAULT_WINDOW_DAYS, _exercise_session_points,
                    _latest_bodyweight, _records_for_exercise)

router = APIRouter(prefix="/api/coach", tags=["coach"])


def _avg_body(entries, key, days_from, days_to, today):
    vals = [getattr(e, key) for e in entries if getattr(e, key) is not None
            and days_from <= (today - e.entry_date).days < days_to]
    return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)


@router.get("/notices")
def coach_notices(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Palauta valmentajan huomiot (pop-up-tyyliset) prioriteettijärjestyksessä."""
    today = date.today()
    profile = db.get(models.Profile, profile_id)
    sex = profile.sex if profile else None
    bw = _latest_bodyweight(db, profile_id)
    notices = []

    entries = (db.query(models.BodyEntry).filter(models.BodyEntry.profile_id == profile_id)
               .order_by(models.BodyEntry.entry_date).all())
    weight_hist = [(e.entry_date, e.bodyweight) for e in entries if e.bodyweight is not None]
    bw_trend = engine.weight_trend(weight_hist, max(d for d, _ in weight_hist)) if len(weight_hist) >= 2 else None
    sleep_avg, sleep_n = _avg_body(entries, "sleep_hours", 0, 14, today)

    # Onko tavoite voima/massa (vaikuttaa tulkintaan): aktiivisen ohjelman goal
    active_prog = (db.query(models.Program).filter(models.Program.profile_id == profile_id,
                   models.Program.is_active.is_(True)).first())
    goal = (active_prog.goal or "").lower() if active_prog else ""
    strength_focus = any(k in goal for k in ("voima", "voimanosto", "maksimivoima"))

    # ---- Pääliikkeiden pysähtyminen + syyanalyysi ----
    stalled = []
    near_ceiling = []
    for ex in db.query(models.Exercise).filter(models.Exercise.is_main_lift.is_(True)).all():
        points = _exercise_session_points(db, ex.id, profile_id)
        valid = [p for p in points if p["estimated_1rm"] > 0]
        if len(valid) < 4:
            continue  # ei tarpeeksi dataa luotettavaan päätelmään
        span = (valid[-1]["date"] - valid[0]["date"]).days
        if span < 42:
            continue
        # Lähitrendi (viim. ~56 pv)
        base = valid[0]["date"]
        recent = [((p["date"] - base).days, p["estimated_1rm"]) for p in valid
                  if (valid[-1]["date"] - p["date"]).days <= 56]
        if len(recent) < 3:
            continue
        rate_wk = engine._linear_rate(recent) * 7
        last_trained_days = (today - valid[-1]["date"]).days
        if last_trained_days > 28:
            continue  # tauolla -> paluu-logiikka hoitaa (comeback), ei "pysähdys"
        rec = _records_for_exercise(points, DEFAULT_WINDOW_DAYS)
        # Lähellä luonnollista kattoa?
        lk = engine.classify_lift(ex.name)
        ceiling = engine.natural_ceiling(lk, bw, sex) if (lk and bw) else None
        if ceiling and rec and rec["current_1rm"] >= ceiling * 0.92:
            near_ceiling.append(ex.name)
            continue
        if rate_wk < 0.15:  # käytännössä tasaista tai laskua
            stalled.append(ex.name)

    if stalled:
        factors = []
        if sleep_n >= 4 and sleep_avg is not None and sleep_avg < 7:
            factors.append(f"uni on jäänyt lyhyeksi (~{round(sleep_avg,1)} h/yö) — palautuminen kärsii")
        if bw_trend is not None and bw_trend < -0.1 and "cut" not in goal:
            factors.append(f"paino laskee ({bw_trend:+.1f} kg/vk) — voiman kasvu vaatii yleensä riittävästi energiaa ja hieman painoa")
        # Palautuminen / kuormitus
        try:
            from .recovery import readiness as _readiness
            rd = _readiness(profile_id, db)
            if rd.get("has_data") and rd["score"] < 60:
                factors.append("palautumismittarit ovat matalalla (HRV/leposyke/uni/kuorma) — harkitse kevennysviikkoa")
            elif rd.get("acwr") and rd["acwr"]["acwr"] > 1.5:
                factors.append("treenikuorma on piikissä — liiallinen kuormitus voi estää kehityksen")
        except Exception:  # noqa: BLE001
            pass
        # Progressio: eikö painot nouse?
        factors.append("varmista progressio: nosta painoa 1.25–2.5 kg kun sarjat menevät (autoprogressio ohjelmassa auttaa)")

        msg = ("Pääliikkeiden kehitys on pysähtynyt (" + ", ".join(stalled) + "). "
               "Mahdollisia syitä ja korjauksia: " + "; ".join(factors) + ".")
        notices.append({
            "id": "stall", "level": "warn", "category": "kehitys",
            "title": "Kehitys pysähtynyt — tarkista nämä",
            "message": msg,
        })

    if near_ceiling:
        notices.append({
            "id": "ceiling", "level": "info", "category": "kehitys",
            "title": "Lähellä luonnollista kattoa",
            "message": ("Liikkeissä " + ", ".join(near_ceiling) + " olet lähellä naturaalinostajan "
                        "realistista kattoa — kehitys hidastuu tästä eteenpäin, ja se on normaalia. "
                        "Keskity tekniikkaan, apuliikkeisiin ja pitkäjänteisyyteen; parin kilon vuosinousu "
                        "on tällä tasolla hyvä tulos."),
        })

    # ---- Palautuminen: deload ----
    try:
        from .recovery import readiness as _readiness2
        rd = _readiness2(profile_id, db)
        if rd.get("deload_recommended"):
            notices.append({
                "id": "deload", "level": "alert", "category": "palautuminen",
                "title": "Kevennysviikko suositeltu", "message": rd.get("deload_message", ""),
            })
    except Exception:  # noqa: BLE001
        pass

    # ---- Koko kehon kate: puuttuvat lihasryhmät ----
    try:
        from .stats import coverage as _coverage
        cov = _coverage(profile_id, db)
        if cov["missing"]:
            notices.append({
                "id": "coverage", "level": "info", "category": "tasapaino",
                "title": "Osa kehosta jää treenaamatta",
                "message": ("Viimeisen ~10 pv aikana ei ole treenattu: " + ", ".join(cov["missing"]) +
                            ". Lisää nämä ohjelmaan tasapainon ja loukkaantumisten ehkäisyn vuoksi."),
            })
    except Exception:  # noqa: BLE001
        pass

    # ---- Paluu vanhoihin tuloksiin ----
    try:
        from .stats import comeback as _comeback
        cb = _comeback(profile_id, db)
        if cb["comebacks"]:
            top = cb["comebacks"][0]
            notices.append({
                "id": "comeback", "level": "info", "category": "kehitys",
                "title": "Liikkeitä palautettavaksi",
                "message": (f"Et ole tehnyt liikettä {top['exercise_name']} hetkeen (ennätys {top['best_ever_1rm']} kg). "
                            f"Aloita ~{top['suggested_start_kg']} kg — paluu huippuun on nopeaa (lihasmuisti). "
                            "Ks. 'Paluu vanhoihin tuloksiin' Kehitys-välilehdellä."),
            })
    except Exception:  # noqa: BLE001
        pass

    # ---- Treenin tuntuma: mukaudu koettuun (väh. 3 fiiliskirjausta) ----
    workouts = (db.query(models.WorkoutSession)
                .filter(models.WorkoutSession.profile_id == profile_id,
                        models.WorkoutSession.status == "completed")
                .order_by(models.WorkoutSession.session_date.desc()).limit(6).all())
    feels = [w.feeling for w in workouts if w.feeling]
    if len(feels) >= 3:
        neg = sum(1 for f in feels if f == "negative")
        pos = sum(1 for f in feels if f == "positive")
        try:
            from .recovery import readiness as _rd3
            rd3 = _rd3(profile_id, db)
            rd_ok = rd3.get("has_data") and rd3["score"] >= 75
            rd_low = rd3.get("has_data") and rd3["score"] < 60
        except Exception:  # noqa: BLE001
            rd_ok = rd_low = False
        if pos >= 3 and rd_ok:
            notices.append({
                "id": "feels-easy", "level": "info", "category": "kuormitus",
                "title": "Treenit tuntuvat helpoilta — nosta rohkeasti",
                "message": ("Viimeisimmät treenit ovat tuntuneet hyviltä ja palautumismittarit ovat "
                            "kunnossa. Keho kestäisi enemmän: nosta painoja askel tai lisää 1–2 sarjaa "
                            "pääliikkeisiin. Autoprogressio ohjelmassa tekee tämän puolestasi."),
            })
        elif neg >= 3:
            notices.append({
                "id": "feels-hard", "level": "warn", "category": "kuormitus",
                "title": "Treenit tuntuneet raskailta",
                "message": ("Useampi treeni putkeen on tuntunut raskaalta tai väsyneeltä" +
                            (" — ja palautumismittarit vahvistavat saman" if rd_low else "") +
                            ". Kevennä paria seuraavaa treeniä ~15 % tai pidä ylimääräinen lepopäivä, "
                            "ja panosta uneen. Tuntuma on dataa siinä missä mittaritkin."),
            })

    # ---- Tekemättä jääneet: vanhat suunnitellut + vajaat treenit ----
    old_planned = (db.query(models.WorkoutSession)
                   .filter(models.WorkoutSession.profile_id == profile_id,
                           models.WorkoutSession.status == "planned",
                           models.WorkoutSession.session_date <= today - timedelta(days=4))
                   .count())
    if old_planned:
        notices.append({
            "id": "unfinished", "level": "info", "category": "treenit",
            "title": "Suunniteltuja treenejä odottaa",
            "message": (f"{old_planned} suunniteltua treeniä on jäänyt tekemättä yli 4 päivää sitten. "
                        "Tee tai skippaa ne, niin seuranta (volyymi, kuormasuhde, ohjelman yhteenveto) "
                        "pysyy totuudenmukaisena."),
        })
    skipped_ex = 0
    for w in workouts[:4]:
        skipped_ex += sum(1 for we in w.exercises if not we.done)
    if skipped_ex >= 4:
        notices.append({
            "id": "partial", "level": "info", "category": "treenit",
            "title": "Liikkeitä jää tekemättä treeneissä",
            "message": (f"Viime treeneissä on jäänyt yhteensä {skipped_ex} liikettä tekemättä. "
                        "Jos syy on aikapula, lyhennä ohjelmaa (vähemmän liikkeitä, tehty kokonaan on "
                        "parempi kuin puoliksi). Jos jaksaminen, kevennä kuormaa tai katso palautuminen."),
        })

    order = {"alert": 0, "warn": 1, "info": 2}
    notices.sort(key=lambda n: order.get(n["level"], 3))
    return {"notices": notices, "count": len(notices)}


@router.get("/direction")
def direction(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Kokonaiskuva: mihin keho on menossa. Yhdistää painon, vyötärön,
    lihasmitat, raudat ja levon — jokainen tekijä vain jos dataa on tarpeeksi.

    Ydinidea: paino vakaa + vyötärö kaventuu + mitat/raudat kasvavat =
    kehon koostumus paranee (syöminen onnistunut). Paino vakaa + vyötärö
    kasvaa = rasvaa kertyy vaikka vaaka ei näytä sitä.
    """
    today = date.today()
    factors = []
    data_needs = []
    score = 0

    # --- Paino (viikkokeskiarvotrendi) ---
    entries = (db.query(models.BodyEntry)
               .filter(models.BodyEntry.profile_id == profile_id,
                       models.BodyEntry.bodyweight.isnot(None))
               .order_by(models.BodyEntry.entry_date).all())
    w_pts = [(e.entry_date, e.bodyweight) for e in entries]
    w_recent = [p for p in w_pts if (today - p[0]).days <= 28]
    weight_trend = None
    if len(w_recent) >= 4 and (w_recent[-1][0] - w_recent[0][0]).days >= 10:
        weight_trend = engine.weight_trend(w_pts, max(d for d, _ in w_pts))
    else:
        data_needs.append("painoa ~3×/vk parin viikon ajan")

    # --- Mitat: vyötärö + lihaskohdat (tahti cm/vk viim. ~8 vk) ---
    meas = (db.query(models.Measurement)
            .filter(models.Measurement.profile_id == profile_id)
            .order_by(models.Measurement.entry_date).all())
    by_site: dict[str, list] = {}
    for m in meas:
        if (today - m.entry_date).days <= 90:
            by_site.setdefault(m.site, []).append((m.entry_date, m.value_cm))

    def site_rate(site):
        pts = by_site.get(site, [])
        if len(pts) >= 2 and (pts[-1][0] - pts[0][0]).days >= 14:
            return engine.recent_rate_per_week(pts)
        return None

    waist_rate = site_rate("vyötärö")
    if waist_rate is None and "vyötärö" not in by_site:
        data_needs.append("vyötärömitta ~2 vk välein")
    muscle_sites = ["hauis", "reisi", "rintakehä", "hartia", "pohje", "lantio"]
    muscle_rates = {s: r for s in muscle_sites if (r := site_rate(s)) is not None}
    growing = [s for s, r in muscle_rates.items() if r > 0.05]
    shrinking = [s for s, r in muscle_rates.items() if r < -0.05]

    # --- Raudat (kokonaiskuorman trendi 14 vs 14 pv) ---
    from .diet import _strength_trend
    strength = _strength_trend(db, profile_id, today)

    # --- Uni (14 pv, väh. 5 kirjausta) ---
    sleep_vals = [e.sleep_hours for e in entries
                  if e.sleep_hours is not None and (today - e.entry_date).days <= 14]
    sleep_avg = sum(sleep_vals) / len(sleep_vals) if len(sleep_vals) >= 5 else None
    if sleep_avg is None:
        data_needs.append("unta useampana yönä viikossa")

    # --- Tulkinta: rasva vs lihas (ydinlogiikka) ---
    stable = weight_trend is not None and abs(weight_trend) <= 0.2
    if weight_trend is not None and waist_rate is not None:
        if stable and waist_rate <= -0.08:
            score += 3
            factors.append({"status": "good", "title": "Kehon koostumus paranee (recomp)",
                            "text": (f"Paino vakaa ({weight_trend:+.1f} kg/vk) mutta vyötärö kaventuu "
                                     f"({waist_rate:.2f} cm/vk) — rasva vähenee ja tilalle tulee lihasta. "
                                     "Syöminen on onnistunut erinomaisesti.")})
        elif stable and waist_rate >= 0.08:
            score -= 2
            factors.append({"status": "bad", "title": "Rasvaa kertyy vaikka paino ei nouse",
                            "text": (f"Paino vakaa mutta vyötärö kasvaa ({waist_rate:+.2f} cm/vk) — "
                                     "koostumus heikkenee. Tarkista ruokavalion laatu (herkut/alkoholi), "
                                     "uni ja arkiliikunta.")})
        elif weight_trend < -0.2 and waist_rate <= -0.05:
            score += 2
            factors.append({"status": "good", "title": "Paino ja vyötärö laskevat yhdessä",
                            "text": f"Pudotus etenee oikein ({weight_trend:+.1f} kg/vk, vyötärö {waist_rate:.2f} cm/vk)."})
        elif weight_trend > 0.2 and waist_rate >= 0.12:
            factors.append({"status": "warn", "title": "Massa tulee rasvapitoisena",
                            "text": (f"Paino nousee {weight_trend:+.1f} kg/vk ja vyötärö {waist_rate:+.2f} cm/vk — "
                                     "hidasta nousua (~0.2 kg/vk) niin isompi osa on lihasta.")})

    if growing and (waist_rate is None or waist_rate <= 0.05):
        score += 2
        factors.append({"status": "good", "title": "Lihasmitat kasvavat",
                        "text": (", ".join(growing) + " kasvaa ilman vyötärön kasvua — "
                                 "todennäköisesti aitoa lihasta.")})
    if shrinking and weight_trend is not None and weight_trend < -0.3:
        factors.append({"status": "warn", "title": "Mitat pienenevät pudotuksessa",
                        "text": (", ".join(shrinking) + " pienenee — nopeassa pudotuksessa osa voi olla "
                                 "lihasta. Pidä proteiini korkealla ja raudat raskaana.")})

    if strength:
        if strength["change_pct"] > 3:
            score += 2
            factors.append({"status": "good", "title": "Raudat kasvavat",
                            "text": f"Kokonaiskuorma +{strength['change_pct']} % — oikeita asioita tapahtuu."})
        elif strength["change_pct"] < -8:
            score -= 1
            factors.append({"status": "warn", "title": "Raudat laskussa",
                            "text": f"Kokonaiskuorma {strength['change_pct']} % — katso lepo ja syöminen."})
    else:
        data_needs.append("treenejä säännöllisesti (raudat-trendiin)")

    if sleep_avg is not None:
        if sleep_avg >= 7.2:
            score += 1
            factors.append({"status": "good", "title": "Lepo tukee kehitystä",
                            "text": f"Unta ~{sleep_avg:.1f} h/yö — palautuminen ja koostumus hyötyvät."})
        elif sleep_avg < 6.5:
            score -= 1
            factors.append({"status": "warn", "title": "Lepo rajoittaa",
                            "text": (f"Unta vain ~{sleep_avg:.1f} h/yö — vähäinen uni heikentää sekä lihaskasvua "
                                     "että rasvanpolttoa. Tämä voi selittää hitaan kehityksen.")})

    # Lihashuolto viim. 7 pv (pieni plussa kokonaisuuteen)
    care_acts = ("venyttely", "foam roll", "liikkuvuus", "lämmittely")
    care_n = (db.query(models.CardioSession)
              .filter(models.CardioSession.profile_id == profile_id,
                      models.CardioSession.activity.in_(care_acts),
                      models.CardioSession.session_date >= today - timedelta(days=7)).count())
    if care_n:
        score += min(1, care_n // 2)
        factors.append({"status": "good", "title": "Lihashuolto plussaa",
                        "text": f"Lihashuoltoa {care_n} krt viikossa — tukee palautumista ja liikkuvuutta."})

    enough = len(factors) >= 2
    if not enough:
        verdict, label = "no_data", "Ei vielä tarpeeksi dataa kokonaiskuvaan"
    elif score >= 4:
        verdict, label = "excellent", "Erinomainen suunta — jatka juuri näin"
    elif score >= 2:
        verdict, label = "good", "Hyvä suunta"
    elif score >= 0:
        verdict, label = "neutral", "Vakaa tilanne"
    else:
        verdict, label = "bad", "Suunta vaatii huomiota"
    return {"verdict": verdict, "label": label, "score": score, "factors": factors,
            "data_needs": data_needs, "enough_data": enough}


# ---------- Aloitusopas: taustakyselystä konkreettinen suunnitelma ----------

# Kokemustason vaikutus ennusteeseen ja ohjaukseen. rate = odotettu kehitys-
# kerroin (aloittelija etenee nopeasti, kokenut hitaasti), cycle = suositeltu
# ohjelmajakson pituus viikkoina ennen vaihtoa/kevennystä.
EXPERIENCE_PROFILES = {
    "aloittelija": {
        "label": "Aloittelija",
        "cycle_weeks": (8, 12),
        "cycle_note": ("Pidä sama ohjelma 8–12 viikkoa ja lisää painoa pienin askelin "
                       "(1.25–2.5 kg) aina kun kaikki sarjat onnistuvat. Aloittelijana "
                       "kehityt joka viikko — ohjelman vaihtelu vain hidastaisi. "
                       "Kevennysviikko vasta jos kehitys pysähtyy 2–3 treeniä putkeen."),
        "expectation": ("Ensimmäisinä kuukausina isot liikkeet nousevat tyypillisesti "
                        "1.25–2.5 kg VIIKOSSA (kyykky/mave nopeammin, penkki/pystypunnerrus "
                        "hitaammin). Tämä on normaalia eikä jatku ikuisesti — nauti siitä."),
    },
    "jonkin_verran": {
        "label": "Jonkin verran treenannut",
        "cycle_weeks": (6, 10),
        "cycle_note": ("Pidä ohjelma 6–10 viikkoa. Lisää painoa kun sarjat onnistuvat, "
                       "ja pidä kevennysviikko (~60–70 % painoista) noin joka 7.–8. viikko "
                       "tai kun treenit alkavat tuntua jatkuvasti raskailta."),
        "expectation": ("Isot liikkeet nousevat tyypillisesti 2.5–5 kg KUUKAUDESSA kun "
                        "treeni, uni ja ruoka ovat kunnossa. Viikkotason heittely on "
                        "normaalia — seuraa kuukausitrendiä."),
    },
    "kokenut": {
        "label": "Kokenut (useita vuosia)",
        "cycle_weeks": (4, 6),
        "cycle_note": ("Jaksota 4–6 viikon blokkeihin: volyymiblokki -> voimablokki -> "
                       "kevennys. Maksimiyritykset vasta blokin lopussa. Kokeneena "
                       "palautuminen ratkaisee — hermostollinen kuorma kannattaa pitää "
                       "silmällä (Kehitys-välilehden Lihaskuormitus-kortti)."),
        "expectation": ("Kehitys on hidasta mutta todellista: 1RM +2–5 kg per 2–3 kk on "
                        "hyvä tahti. Ennusteet kalibroituvat omaan dataasi muutamassa "
                        "viikossa."),
    },
    "palaava": {
        "label": "Palaava (tauolta)",
        "cycle_weeks": (6, 8),
        "cycle_note": ("Ensimmäiset 6–8 viikkoa: aloita ~60–70 %:sta vanhoista painoista "
                       "ja nosta reippaasti (jopa 5 kg/vk isoissa) niin kauan kuin tekniikka "
                       "pitää. Lihasmuisti tuo vanhat tulokset takaisin moninkertaisesti "
                       "nopeammin kuin ne alun perin tulivat."),
        "expectation": ("Paluu vanhalle tasolle on nopeaa (viikkoja–kuukausia, ei vuosia). "
                        "Kirjaa vanhat ennätykset järjestelmään (Kehitys -> vanhan tuloksen "
                        "kirjaus), niin ennuste ja paluusuunnitelma osaavat huomioida ne."),
    },
}

GOAL_PLANS = {
    # tavoite -> (ensisijainen ohjelmapohja kokeneemmille, perustelu)
    "voima": ("voimanosto", "Voimatavoitteeseen sopii kyykky/penkki/mave-painotteinen ohjelma."),
    "lihasmassa": ("bodaus", "Lihasmassatavoitteeseen sopii isompi volyymi ja lihasryhmäjako."),
    "kunto": ("aloittelija", "Kuntotavoitteeseen sopii koko kehon ohjelma + kardio kylkeen."),
    "painonpudotus": ("bodaus", "Painonpudotuksessa lihasmassa suojataan isolla volyymilla ja "
                       "riittävällä proteiinilla — kalorivaje tulee ruoasta, ei treenistä."),
}


@router.get("/onboarding")
def onboarding(profile_id: int = Query(...), db: Session = Depends(get_db)):
    """Aloitusopas: profiilin taustakyselyn vastauksista konkreettinen suunnitelma.

    Kertoo mikä ohjelmapohja kannattaa luoda, kuinka pitkiä jaksoja treenataan,
    mitä kehitystä on realistista odottaa ja mitä dataa kannattaa kirjata.
    Erityisen tärkeä uusille profiileille joilla ei vielä ole omaa dataa.
    """
    profile = db.get(models.Profile, profile_id)
    if not profile:
        return {"available": False, "missing": ["profiili"]}
    missing = []
    if not profile.experience:
        missing.append("kokemustaso")
    if not profile.goal:
        missing.append("tavoite")
    if missing:
        return {"available": False, "missing": missing,
                "note": "Täytä taustakysely profiilin muokkauksessa, niin saat "
                        "henkilökohtaiset suositukset."}

    exp = EXPERIENCE_PROFILES.get(profile.experience, EXPERIENCE_PROFILES["jonkin_verran"])
    days = profile.days_per_week or 3
    # Aloittelija ohjataan aina aloittelijapohjaan tavoitteesta riippumatta —
    # perusliikkeet ja rutiini ensin, erikoistuminen myöhemmin.
    if profile.experience == "aloittelija":
        plan_id, plan_why = "aloittelija", ("Aloittelijana tärkeintä on oppia perusliikkeet "
                                            "ja rakentaa rutiini — erikoistuminen kannattaa "
                                            "vasta ~6–12 kk päästä.")
    else:
        plan_id, plan_why = GOAL_PLANS.get(profile.goal, GOAL_PLANS["kunto"])
    from .templates import PLAN_BLUEPRINTS
    bp = PLAN_BLUEPRINTS.get(plan_id, {})
    day_options = sorted(bp.get("days", {}).keys())
    plan_days = min(day_options, key=lambda x: abs(x - days)) if day_options else days

    has_program = (db.query(models.Program)
                   .filter(models.Program.profile_id == profile_id).count()) > 0
    workout_count = (db.query(models.WorkoutSession)
                     .filter(models.WorkoutSession.profile_id == profile_id,
                             models.WorkoutSession.status == "completed").count())

    tips = [
        "Kirjaa kehon paino aamuisin pari kertaa viikossa — moni arvio (kaloritarve, "
        "voimatasot, ennusteet) tarkentuu sen mukana.",
        "Merkitse treenin tuntuma (helppo/raskas) treenin jälkeen — järjestelmä oppii "
        "milloin kuormaa voi nostaa ja milloin kevennetään.",
    ]
    if profile.experience == "palaava":
        tips.insert(0, "Kirjaa vanhat ennätyksesi (Kehitys -> vanhan tuloksen kirjaus "
                       "vuoden kanssa) — paluusuunnitelma ja ennusteet rakentuvat niiden päälle.")
    if profile.goal == "painonpudotus":
        tips.append("Punnitse säännöllisesti: dieetin onnistumista seurataan painotrendistä, "
                    "eikä ruokapäiväkirjaa tarvita jos paino kehittyy oikeaan suuntaan.")
    if profile.goal in ("voima", "lihasmassa"):
        tips.append("Uni on tärkein yksittäinen palautumistekijä — kirjaa unitunnit jos "
                    "mahdollista, niin valmentaja osaa erottaa treeniongelman uniongelmasta.")

    lo, hi = exp["cycle_weeks"]
    return {
        "available": True,
        "answers": {"experience": profile.experience, "experience_label": exp["label"],
                    "training_years": profile.training_years, "goal": profile.goal,
                    "days_per_week": profile.days_per_week},
        "program": {"plan": plan_id, "days_per_week": plan_days, "why": plan_why,
                    "guidance": bp.get("guidance"), "has_program": has_program},
        "cycle": {"weeks_min": lo, "weeks_max": hi, "note": exp["cycle_note"]},
        "expectation": exp["expectation"],
        "tips": tips,
        "workout_count": workout_count,
    }
