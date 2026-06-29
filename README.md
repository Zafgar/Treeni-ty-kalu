# 🏋️ Treeni-ty-kalu

Kehon- ja treeniseurantajärjestelmä. Tavoitteena täysi seurantajärjestelmä,
jolla voi suunnitella ohjelmat, kirjata treenit ja seurata kehitystä — sekä
tietokoneella (nyt) että puhelimella (myöhemmin, sama selainpohjainen sovellus).

## Teknologia

- **Backend:** Python + [FastAPI](https://fastapi.tiangolo.com/), SQLite + SQLAlchemy
- **Frontend:** Responsiivinen selainkäyttöliittymä (vanilla JS, ei build-vaihetta)
- **Laskentamoottori:** Python (1RM-arviot, sarjaohjelman konversio, totalit)

Sama palvelin tarjoilee API:n ja käyttöliittymän. Koska UI on selainpohjainen,
se toimii tietokoneella heti ja on myöhemmin muunnettavissa puhelimen
kotinäytölle asennettavaksi PWA:ksi ilman erillistä natiivisovellusta.

## Käynnistys

```bash
./run.sh
```

Avaa sitten selaimessa <http://localhost:8000>. Ensimmäisellä kerralla skripti
luo virtuaaliympäristön ja asentaa riippuvuudet automaattisesti.

Vaihtoehtoisesti käsin:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd backend
uvicorn app.main:app --reload
```

API-dokumentaatio (Swagger UI): <http://localhost:8000/docs>

## Testit

```bash
source .venv/bin/activate
python -m pytest backend/tests/ -q
```

## Toiminnot tällä hetkellä (ydin)

- **Liikkeet:** lisää mikä tahansa liike, merkitse pääliikkeet ja laji (totaleja varten)
- **Ohjelmat:** sykli- (treeni/lepo) tai viikkopohjaiset ohjelmat; per liike
  sarjat, toistot, paino ja palautusaika; muokkaus lennossa
- **Treenit:** kirjaa sarjat erikseen (tukee vajaita sarjoja kuten 4,4,4,3),
  RIR (varasto), huomiot per sarja, kehon paino; aloita treeni suoraan ohjelman
  päivästä esitäytetyillä tavoitteilla
- **Painolaskuri:** kun vaihdat sarjaohjelmaa (esim. 4×5 → 4×8), laskuri arvioi
  uuden painon joka vastaa samaa rasitusta (varasto huomioiden)
- **Sarjamallit:** joustavat per-sarja-toistot (pyramidit kuten 12,10,8 tai
  5x5) ja prosenttimallit (% 1RM:stä); useita ohjelmia voi pitää rinnakkain
- **Valmiit pohjat:** voimajaksot (5×5, prosenttipohjainen maksimivoima,
  pyramidi-hypertrofia) ohjeineen; lähtöpaino lasketaan automaattisesti
  tämänhetkisestä arvioidusta 1RM:stä
- **Kehityksen seuranta:** arvioidun 1RM:n kehityskäyrä per liike (useita
  liikkeitä samassa kuvaajassa), ennätystaulukko ja yleisnäkymä haulla
- **Lajitotalit:** esim. voimanoston total ala-/yläraja-arvioineen ja
  kehityskäyrä ajan yli
- **Profiilit:** seuraa omaa kehitystä, valmennettavia tai läheisiä; vaihda
  aktiivista profiilia yläpalkista. Jokaisella profiililla on oma data
  (ohjelmat, treenit, kehodata); liikkeet ovat yhteisiä.
- **Kehon seuranta:** paino, rasva-% ja koostumusarvio (rasva-/lihasmassa,
  BMI, FFMI), hyvinvointidata (uni, HRV, leposyke, kalorit) ja joustavat
  ympärysmitat (hauis, pohje, rintakehä, hartia, reisi, vyötärö, kyynärvarsi…)
  aikasarjagraafeineen

### Tämänhetkisen 1RM:n sääntö (kahden ohjelman "kiista")

Kun useaa ohjelmaa ajetaan peräkkäin, jokin liike voi parantua uudessa
ohjelmassa. Järjestelmä laskee arvioidun 1RM:n suoraan toteutuneista sarjoista
ja valitsee tämänhetkiseksi tasoksi **parhaan tuloksen tuoreelta aikaikkunalta**
(oletus 56 vrk liikkeen viimeisimmästä treenistä) — recency voittaa, eikä
vanha ohjelma "kiistele" uuden kanssa. Kaikkien aikojen ennätys säilyy erikseen.

## Tietomalli

```
Profile ──< Program ──< ProgramDay ──< ProgramExercise >── Exercise
   │
   ├──< WorkoutSession ──< WorkoutExercise ──< SetLog
   ├──< BodyEntry        (paino, rasva-%, uni, HRV, syke, kcal)
   └──< Measurement      (ympärysmitat per kohta)
```

## Suunniteltu jatko (visio)

Rakenne on suunniteltu laajennettavaksi seuraaviin ilman ydinmallien rikkomista:

- Kehitysennuste todelliseen kehoreagointiin perustuen
- Palautumis-välilehti (nopea painojen kasvu sarjoissa, total-kg)
- Muuttujien väliset korrelaatiot (esim. uni/kalorit vs. suoritus ja kehitys)
- PWA puhelimelle
