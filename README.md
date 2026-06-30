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

## Käyttö puhelimella (Android / iPhone)

Sovellus toimii **samalla palvelimella** sekä tietokoneella että puhelimella —
puhelimeen ei tarvitse ladata mitään GitHubista. Käyttöliittymä on responsiivinen
(välilehdet swipe-rivinä, taulukot vierivät, kentät pinoutuvat) ja toimii sekä
PC:n leveällä että puhelimen kapealla näytöllä.

Testaaminen Android-puhelimella (puhelin ja tietokone samassa wifi-verkossa):

1. **Käynnistä palvelin tietokoneella** niin että se kuuntelee koko verkkoa
   (run.sh tekee tämän jo: `--host 0.0.0.0`). Käsin: `uvicorn app.main:app --host 0.0.0.0 --port 8000`.
2. **Selvitä tietokoneen lähiverkko-IP**, esim. `192.168.1.50`
   (Windows: `ipconfig`, Mac/Linux: `ip addr` / `ifconfig`).
3. **Avaa puhelimen selaimessa** osoite `http://192.168.1.50:8000`
   (käytä koneesi IP:tä). Sovellus aukeaa heti.
4. **Asenna kotinäytölle (PWA):** Chrome Android → valikko (⋮) → *Lisää
   aloitusnäyttöön* / *Asenna sovellus*. Tämän jälkeen se avautuu omana
   sovelluksenaan ilman selainpalkkia. (iPhone: Safari → Jaa → *Lisää
   Koti-valikkoon*.)

> Lähiverkkokäytössä data tallentuu **tietokoneelle** (`data/treeni.db`), ei
> puhelimeen — puhelin on vain näyttö, joka ottaa yhteyden koneeseen. Tämä toimii
> vain kun **kone on päällä ja samassa wifissä**.

## Käyttö ilman omaa konetta (vienti pilveen)

Jotta sovellus toimii puhelimella **missä vain ja vaikka oma kone on sammuksissa**,
se viedään pilveen. Repo sisältää valmiin `Dockerfile`n (yksi kontti tarjoilee
sekä API:n että käyttöliittymän) ja konfiguraatiot Renderille (`render.yaml`) ja
Fly.io:lle (`fly.toml`).

**Render (helpoin, lukee `render.yaml`n automaattisesti):**

1. Pushaa repo GitHubiin (jos ei vielä siellä).
2. Luo tili osoitteessa <https://render.com> → *New* → *Blueprint* → valitse repo.
3. Render rakentaa Dockerfilen ja antaa pysyvän `https://…onrender.com`-osoitteen.
4. Avaa osoite puhelimella ja asenna kotinäytölle (PWA). Kone saa olla sammuksissa.

**Pysyvä tietokanta:** sovellus lukee tietokannan polun ympäristömuuttujasta
`TREENI_DB_PATH` (oletus pilvessä `/data/treeni.db`). Liitä alustan **pysyvä
levy/volyymi** `/data`-polkuun, niin data säilyy uudelleenjulkaisuissa.
- Render: `render.yaml`ssa on `disk` valmiina (huom. levy on Renderissä maksullinen;
  ilman levyä toimii, mutta data nollautuu uudelleenjulkaisussa).
- Fly.io: `fly launch` + `fly volumes create treeni_data --size 1` (volyymi).

**Portit:** pilvialusta antaa portin `PORT`-ympäristömuuttujassa, ja kontti
sitoo siihen automaattisesti — sinun ei tarvitse avata portteja itse.

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
- **Automaattinen ohjelmageneraattori:** valitse laji (lihasmassa/voimanosto/
  olympianosto) ja treenikerrat/viikko (3–6) → järjestelmä rakentaa valmiin
  viikko-ohjelman liikkeineen (haetaan kirjastosta) ja sarjoineen; pääliikkeiden
  painot lasketaan 1RM:stä
- **Mittojen kasvun ennuste (älykäs):** ympärysmittojen kehitys ennustetaan
  ensisijaisesti omasta historiasta (adaptoituu: jos jokin kasvaa odotettua
  nopeammin, ennuste seuraa; jos hidastuu, mitoittuu uudelleen). Pituuspohjainen
  **pehmeä luonnollinen katto** (aloittelija kasvaa pidempään, edistynyt
  tasaantuu; data voi ylittää mallin). **Painon/rasvan kytkentä**: paino+vyötärö
  nousee → tunnistaa kasvun osin rasvaksi; dieetillä vakaa raaja → ymmärtää
  lihaksen säilyvän eikä pakota laskua
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
- **Treenin suoritus:** kuittaa treeni valmiiksi tai skip (skipattua ei lasketa
  kehitykseen); per-liike "OK"-kuittaus; pikavajaus ("4 toistoa vajaaksi")
  ilman sarjojen erittelyä — vähennetään volyymistä, jolloin samalla painolla
  tehty sarjasuoritus näkyy kehityskäyrällä
- **Liikearkisto:** muistaa viimeksi käytetyt painot, esitäyttää liikkeen
  edellisellä painolla ja ehdottaa rautoja eri toistomäärille; "ehdota seuraava
  paino" (hyväksy tai määritä itse)
- **Kokonaisrauta:** siirretty kokonais-kg, toistot ja sarjat per treeni
  aikajanagraafilla — vertailtavissa painoon ja kaloreihin
- **Ravintoseuranta:** ~125 valmista suomalaista ruoka-ainetta **kategorioittain**
  (hedelmät, liha, kana, kala, pasta & riisi, maitotuotteet, juomat, alkoholi,
  herkut, kastikkeet, proteiinijauheet…) raaka/kypsä-variantteineen ja
  annoskokoineen (esim. olut 0.33/0.5 l, viinilasi 0.2 l); **haku**, **suosikit**
  ja omien lisäys. Kirjaa ruokia grammoina **mille tahansa päivälle**
  (päivävalitsin), muokkaa määriä jälkikäteen; päivän makrosumma ja
  **liikaa/liian vähän -varoitus** dieettitavoitteeseen nähden; makrojen
  (kcal/P/H/R) kehitysgraafi. **Omat ateriat** (esim. smoothie = maito + marjat +
  whey) tallennetaan ja pikakirjataan yhdellä napilla.
- **Ateria-aikataulu (ravinnejaksotus):** jaksottaa päivän makrot aterioille
  (2–8 kpl) kellonaikojen ja treeniajan mukaan — treenin ympärille enemmän
  hiilaria, kauemmas rasvaa; proteiini tasan. 16:8-mallilla syönti-ikkuna
  rajataan automaattisesti.
- **Liikekirjasto:** valmiit liikkeet kategorioittain (rinta, selkä, jalat,
  olkapäät, hauis, ojentajat, vatsa, pohkeet, olympia) ja välineittäin (tanko,
  käsipainot, talja, kone, keho, kahvakuula); kukin järkevillä oletussarjoilla.
  Kategorioittain ryhmitelty valitsin treeniin/ohjelmaan, sarjat alustetaan
  liikkeen oletuksista.
- **Treenin kesto ja poltetut kalorit:** kirjaa treenin kesto (min) ja kcal
  (esim. älykellosta); mukana kuormitusaikajanassa ja korrelaatioissa
  treenin ja syömisen suhteen arviointiin
- **Fiilismerkintä:** merkitse treeniin hyvä olo tai ongelma (+ vapaa huomio,
  esim. kipu); merkityt nousevat yleisnäkymään huomaamaan jos jokin vaikuttaa
  jatkoon
- **Viikkovolyymi & ehdotukset:** suoritetut työsarjat lihasryhmittäin
  viikossa verrattuna suositukseen (~10–20 sarjaa) → ehdotus kasvata/kevennä/OK;
  käyttäjä voi kuitata "tilanne OK, ei muutoksia"
- **Sujuva treenin suoritus (mobiilifokus):** tehdyt liikkeet tiivistyvät
  ("✓ tehty" + arvioitu 1RM), edistymislaskuri (X/Y tehty), vajaus ja
  painoehdotus yhdellä painalluksella; arvioitu 1RM näkyy jokaiselle liikkeelle
- **Realistinen ennuste (data + malli):** pääliikkeiden kehitys ennustetaan
  toteutuneesta tahdista ja naturaalinostajan luonnollisesta kehityskaaresta
  (vähenevä tuotto kohti realistista kattoa). Painon lasku hidastaa ennustetta
  ja laskee maksimipotentiaalia; ennusteen **luottamus** kasvaa datan määrän
  myötä (vähemmän dataa → leveämpi haarukka). Myös **lajitotalin ura** (mihin
  esim. voimanoston total on menossa ~6 kk) ennustetaan haarukkana
- **Kehon pisteet:** suhdepisteet ympärysmitoista (vyötärö/pituus,
  hartia/vyötärö, rintakehä/vyötärö), fysiikkataso (FFMI) ja voimataso
  yhdistettynä yhteispisteiksi — kuva sekä ulkonäön että voiman tasosta
- **kcal-itsearvio:** jos treenin kulutusta ei syötetä (älykello), järjestelmä
  arvioi sen kehon painosta ja kestosta
- **Ennusteen osuvuus & itsekalibrointi:** järjestelmä tallentaa ennusteet ja
  vertaa myöhemmin toteumaan (näet menneet ennusteet vs. todellisuus). Osuvuus
  **kalibroi tulevat ennusteet** tarkemmiksi — jos ennusteet ovat aliarvioineet,
  tahtia nostetaan, ja päinvastoin. Ennuste annetaan jopa **1 vuoden** päähän
  (loukkaantuminen/sairaus voi tuoda takapakkia)
- **Voimatasot:** 8 porrasta (aloittelija → SM/EM/MM-luokka) kehon painoon ja
  sukupuoleen suhteutettuna, edistymispalkki ja seuraavan tason kynnys.
  Mukana **väestön keskiarvo** painoluokassasi vertailuksi ("sinä 2.3× keskiarvo")
- **Liikkeiden selitteet:** pääliikkeille ja yleisille liikkeille suoritusohje
  ja liikkeen idea (näytetään "Ohje"-napista Liikkeet-välilehdellä)
- **Fysiikkataso:** 8 porrasta (aloittelija → IFBB Pro) FFMI:n perusteella
  (paino + rasva-% + pituus), edistymispalkki Keho-välilehdellä
- **PWA:** asennettavissa puhelimen kotinäytölle (manifest + service worker),
  responsiivinen käyttöliittymä toimii sekä PC:llä että puhelimella
- **Ennustava graafi:** realistinen kehitysennuste haarukoineen — vähenevä
  tuotto kohti fysiologista kattoa (johdettu painosta ja voimastandardista)
- **Vanhojen tulosten kirjaus:** merkitse aiempia tuloksia taaksepäin, niin
  graafi ja ennuste näyttävät kehityssuunnan alusta asti
- **Palautuminen & korrelaatiot:** uni (tunnit + pisteet), HRV, leposyke
  aikajanoineen ja korrelaatiotyökalu (esim. uni vs. kokonaisrauta) Pearsonin
  kertoimella — kaikki vapaaehtoista lisädataa
- **Dieettimoottori:** viikkokeskiarvoon perustuva painotrendi, adaptiivinen
  TDEE (toteutuneesta syönnistä + painomuutoksesta), kcal- ja makrotavoitteet
  kehon painosta ja tavoitteesta, 4 valmista dieettimallia (cut/ylläpito/lean
  bulk) + 16:8-paasto ja low carb -mallit, suositus kalorien säädöstä,
  bulkin vyötärö/pituus-raja-arvio, voiman
  säilymisen seuranta dieetillä ja kehon alueiden kehitys (uuden lihaksen
  indikaattori vyötäröön nähden)
- **Per-päivä-tavoitteet:** treeni- ja lepopäivän kalorijako (hiilarisyklitys)
  treenitiheyden ja poltettujen kalorien mukaan — viikkokeskiarvo pysyy
  tavoitteessa — sekä viikkoyhteenveto (kalorien osuvuus ja tahdin arvio)

### Tämänhetkisen 1RM:n sääntö (kahden ohjelman "kiista")

Kun useaa ohjelmaa ajetaan peräkkäin, jokin liike voi parantua uudessa
ohjelmassa. Järjestelmä laskee arvioidun 1RM:n suoraan toteutuneista sarjoista
ja valitsee tämänhetkiseksi tasoksi **parhaan tuloksen tuoreelta aikaikkunalta**
(oletus 56 vrk liikkeen viimeisimmästä treenistä) — recency voittaa, eikä
vanha ohjelma "kiistele" uuden kanssa. Kaikkien aikojen ennätys säilyy erikseen.

## Mihin ja miten data tallentuu

Kaikki data tallennetaan **paikalliseen SQLite-tietokantaan**: tiedosto
`data/treeni.db` projektin juuressa. Kun lisäät tai muutat jotain
käyttöliittymässä, selain lähettää pyynnön FastAPI-backendille, joka kirjoittaa
muutoksen tietokantaan **välittömästi** (jokainen lisäys/muokkaus/poisto
tallentuu heti — ei erillistä "tallenna"-vaihetta koko sovellukselle).

- **Sijainti:** `data/treeni.db` (SQLite-tiedosto). Tämä on koko datasi.
- **Varmuuskopio:** kopioi `data/treeni.db` talteen — siinä on kaikki.
- **Siirrettävyys:** vie tiedosto toiselle koneelle ja sovellus jatkaa siitä.
- **Yksityisyys:** data pysyy omalla koneellasi, ei pilvessä (ellet itse vie).
- **Historiatiedot:** voit kirjata vanhoja painoja, mittoja ja tuloksia
  taaksepäin antamalla menneen päivämäärän — kaikissa lomakkeissa on
  päivämääräkenttä. Näin saat kehityskäyrän ja ennusteen alkamaan oikein
  vaikka aloittaisit sovelluksen käytön vasta nyt.

> Tietokanta on `.gitignore`ssa, joten omat treenitietosi eivät päädy versionhallintaan.

## Tietomalli

```
Profile ──< Program ──< ProgramDay ──< ProgramExercise >── Exercise
   │
   ├──< WorkoutSession ──< WorkoutExercise ──< SetLog
   │      (status: planned/completed/skipped;  WorkoutExercise: done, missed_reps)
   ├──< BodyEntry        (paino, rasva-%, uni, HRV, syke, kcal)
   ├──< Measurement      (ympärysmitat per kohta)
   ├──< FoodLog ──> Food (ruokakirjasto, makrot per 100 g)
   └──< DietPhase        (cut/maintain/bulk, tavoitetahti kg/vk)

Exercise: + category, equipment, default_sets/reps (valmis liikekirjasto)
```

## Suunniteltu jatko (visio)

Rakenne on suunniteltu laajennettavaksi seuraaviin ilman ydinmallien rikkomista:

- Aterioiden ajoitus kellonaikojen ja treeniaikataulun mukaan (ravinnejaksotus)
- Ohjelman seuraavien treenien siirto/aikataulutus skipatessa
- Älykellon/terveysdatan automaattinen tuonti (nyt manuaalinen kirjaus)
