# Jakelu: Android, kavereille jakaminen ja päivitykset

Tämä ohje vastaa kolmeen kysymykseen: **saako sovelluksen Androidille**,
**miten sen jakaa kavereille**, ja **miten päivitykset hoituvat järkevästi**.

## Tärkein tosiasia ensin (rehellinen arvio)

Sovelluksen **äly on Pythonissa** (1RM-arviot, ennusteet, TDEE, palautuminen,
alkoholi, lihaskuormitus…). Siksi on kaksi periaatteellista tapaa saada se
Androidille, ja niillä on iso ero vaivassa:

| Tapa | Toimii ilman nettiä | Helppo jakaa | Päivitys | Vaiva |
|------|--------------------|--------------|----------|-------|
| **A. Isännöity PWA** (suositus) | rungon osalta kyllä, data tarvitsee palvelimen | linkki / QR / APK-kääre | automaattinen | pieni |
| **B. Oma tiedostopaketti** (kaveri ajaa itse) | kyllä (kaverin oma kone) | zip-tiedosto | git pull / uusi zip | keskisuuri |
| **C. Natiivi APK jossa Python sisällä** | kyllä | APK-tiedosto | uusi APK | **suuri, riskialtis** |

**Vaihtoehto C (Python paketoituna APK:hon, esim. Chaquopy) ei ole
suositeltava tälle sovellukselle:** Pydantic v2:n ydin on Rustia, jolle ei ole
valmiita Android-wheelejä — se todennäköisesti kaatuu käännösvaiheessa. Sen
saisi toimimaan vain kirjoittamalla koko backendin uudelleen puhtaaksi
selain-JS:ksi (valtava työ) tai vaihtamalla Pydantic pois. Ei kannata nyt.

**Suositus: Vaihtoehto A.** Se on standardi tapa jakaa web-sovellus kavereiden
Androideille, ja päivitykset tulevat automaattisesti. Projektissa on jo valmiit
julkaisukonfigit (`Dockerfile`, `fly.toml`, `render.yaml`), joten isännöinti on
90 % valmiina.

---

## Vaihtoehto A: Isännöity PWA (suositus — helpoin jakaa ja päivittää)

Idea: sovellus pyörii yhdessä paikassa (pilvi tai oma kone), ja kaverit
**asentavat sen puhelimen aloitusnäytölle** selaimesta. Näyttää ja tuntuu
natiivilta appilta (oma ikoni, koko ruutu), mutta päivittyy itsestään.

### 1) Julkaise sovellus (kerran)

**Fly.io (edullisin pysyvä ratkaisu, data säilyy volyymissä):**
```bash
fly launch            # lukee fly.toml, kysyy sovelluksen nimen ja alueen
fly volumes create treeni_data --size 1 --region arn   # sama alue kuin fly.toml
fly deploy
```
Saat osoitteen kuten `https://treeni-ty-kalu.fly.dev`.

> **Data säilyy** volyymissä (`/data/treeni.db`) julkaisujen ja
> uudelleenkäynnistysten yli. **Aja vain yksi kone** — SQLite ei jakaudu usealle
> koneelle, joten älä skaalaa (`min_machines_running` saa olla 0 tai 1).
> `min_machines_running = 1` pitää palvelimen aina hereillä (ei herätysviivettä,
> hieman kalliimpi); `0` säästää mutta ensimmäinen avaus herättää koneen ~1–2 s.
> **Reaaliaikaisuus ei riipu tästä:** kaikki jakavat saman kannan, joten näet
> aina uusimman datan heti kun avaat sovelluksen, oli kone hereillä tai ei.

**Automaattiset päivitykset (suositus):** repossa on valmis GitHub Actions -työ
(`.github/workflows/fly-deploy.yml`). Kun lisäät GitHubiin salaisuuden
`FLY_API_TOKEN` (luo: `fly tokens create deploy`), jokainen push `main`-haaraan
julkaisee automaattisesti — et tarvitse `fly deploy`:tä käsin, ja kaverit saavat
uusimman version seuraavalla avauksella.

**Tai Render.com:** yhdistä GitHub-repo → Render lukee `render.yaml` → deploy.
Renderin **natiivit automaattipäivitykset** ovat vielä helpommat (push → deploy
ilman erillistä työtä), mutta **pysyvä levy on Renderissä maksullinen** (n. 7 $/kk).
Fly on halvempi pysyvälle datalle; Render on yksinkertaisin jos maksu ei haittaa.

**Tai oma kone:** aja `run.sh` (Linux/Mac) tai `Kaynnista-Windows.bat` ja jaa
lähiverkon osoite (näkyy Profiilit-välilehdellä). Toimii vain samassa wifissä.

### 2) Kaverit asentavat aloitusnäytölle

- Avaa osoite **Chromella** Androidilla → valikko (⋮) → **"Lisää
  aloitusnäyttöön"** / "Asenna sovellus".
- Sovellus ilmestyy omalla ikonilla ja avautuu koko ruutuun ilman
  selainpalkkia (PWA-manifesti on jo tehty).

### 3) (Valinnainen) Tee siitä oikea APK-tiedosto

Jos haluat jaettavan **APK-tiedoston** (esim. WhatsAppilla):

1. Mene **https://www.pwabuilder.com** ja syötä julkaistu osoitteesi.
2. Valitse **Android → Generate** → lataa APK (TWA, Trusted Web Activity).
3. Jaa APK kavereille. He sallivat "asennus tuntemattomasta lähteestä" ja
   asentavat. APK on ohut kuori joka avaa saman isännöidyn sovelluksen.

### Miten päivitys toimii (vaihtoehto A)

- **Automaattisesti.** Service worker hakee aina tuoreimman version verkosta
  (network-first). Kun julkaiset uuden version (`fly deploy` / git push
  Renderiin), kaverit saavat sen seuraavalla avauksella — mitään ei tarvitse
  jakaa uudelleen.
- APK-kuorta ei tarvitse päivittää, koska se vain näyttää isännöidyn sovelluksen.
- Version voi tarkistaa: `GET /api/version` palauttaa version + build-tunnisteen.

**Rajoitus:** data (treenit, ruoat) tarvitsee yhteyden palvelimeen. Runko
toimii offline, mutta kirjaaminen vaatii yhteyden. Jos kaverit tarvitsevat
täysin offline-datan matkalla, katso vaihtoehto B + laitesynkronointi.

---

### Profiililukko (kun jaat saman instanssin kavereille)

Jos kaikki kaverit käyttävät **samaa isännöityä instanssia** (kaikki puhuvat
keskenään samaan kantaan), ota käyttöön **profiililukko**, ettei kukaan
vahingossa kirjaa väärälle profiilille:

- Avaa **Profiilit → 🔒 Profiililukko** ja aseta **admin-PIN**. Sinusta (PT)
  tulee admin, joka näkee ja hallinnoi kaikkia profiileja.
- Aseta kullekin kaverille **oma PIN**. Tämän jälkeen kaveri näkee ja voi kirjata
  vain omaan profiiliinsa; muiden dataa hän ei näe.
- Profiili ilman PINiä on avoin — aseta PIN jokaiselle jonka haluat suojata.
- Lukko on **valinnainen**: ennen admin-PINin asetusta mikään ei muutu
  (paikallinen yksinkäyttö toimii kuten ennen). Lukon saa pois päältä admin-PINillä.

Tämä on **järkevä suoja kaveriporukalle**, ei pankkitason turva — pääasiallinen
tarkoitus on estää vahingossa väärälle profiilille kirjaaminen ja pitää muiden
data piilossa. Palvelin (pilvi) on aina päällä, joten **sinun PC:si ei tarvitse
olla auki** jotta muiden kirjaukset tallentuvat — ne menevät suoraan yhteiseen
kantaan, ja sinä näet ne adminina milloin vain avaat sovelluksen.

## Vaihtoehto B: Oma tiedostopaketti (täysin offline, kaverin oma data)

Idea: kaveri saa **koko sovelluksen tiedostoina** ja ajaa sen omalla
koneellaan/puhelimellaan. Data on hänen omalla laitteellaan, ja
**laitesynkronointi** (Profiilit-välilehti) yhdistää sen sinun koneeseesi kun
olette samassa wifissä.

### Jakaminen

1. Paketoi repo zipiksi (ilman `data/`- ja `.git`-kansioita).
2. Kaveri purkaa ja ajaa:
   - **Windows:** tuplaklikkaa `Kaynnista-Windows.bat` (asentaa riippuvuudet ja
     käynnistää; avaa `http://localhost:8000`).
   - **Mac/Linux:** `./run.sh`.
   - **Android:** vaatii Termux/Pydroid-tyyppisen Python-ympäristön — teknistä,
     ei suositella tavalliselle kaverille. Käytä mieluummin vaihtoehtoa A.

### Päivitys

- Jos kaverilla on git: `git pull` hakee uusimman, käynnistä uudelleen.
- Muuten: jaa uusi zip. Data säilyy koska se on `data/`-kansiossa (ei zipissä),
  ja migraatiot (`ensure_columns`) päivittävät kannan automaattisesti.
- **Datan siirto sinulle:** kaveri avaa Profiilit → Laitesynkronointi ja
  synkronoi samassa wifissä, TAI lähettää varmuuskopion tiedostona.

---

## Yhteenveto: mitä minun kannattaa tehdä?

1. **Jos haluat vain helposti jakaa kavereille ja unohtaa päivitykset:**
   Julkaise Fly.io/Render (vaihtoehto A), jaa linkki tai PWABuilder-APK.
   Päivitykset tulevat itsestään.
2. **Jos valmennat ja jokaisella pitää olla oma offline-data:** kaverit ajavat
   oman kopion (vaihtoehto B) ja synkronoivat kanssasi wifissä. Työläämpää
   asentaa, mutta täysin offline ja oma data.
3. **Natiivi "Python APK:n sisällä" (vaihtoehto C):** älä tee nyt — Pydantic v2
   estää sen käytännössä ilman isoa uudelleenkirjoitusta.

Molemmissa toimivissa tavoissa (A ja B) **laitesynkronointi** hoitaa datan
siirron laitteiden välillä, ja **`/api/version`** kertoo ollaanko uusimmassa.
