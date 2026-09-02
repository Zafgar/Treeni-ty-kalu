"""Treeni-ty-kalu — FastAPI-sovellus.

Tarjoaa REST-API:n (liikkeet, ohjelmat, treenit, laskentamoottori) ja
serveeraa selainkäyttöliittymän staattisista tiedostoista. Sama palvelin
toimii PC:llä ja myöhemmin puhelimella (selain / PWA).
"""
import json
import os
import re
import socket
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import models, security
from .database import (
    Base,
    SessionLocal,
    engine,
    get_db,
    ensure_columns,
    ensure_default_profile,
    ensure_exercise_descriptions,
    ensure_extra_exercises,
    ensure_extra_foods,
    ensure_alcohol_foods,
    ensure_seed_exercises,
    ensure_seed_foods,
)
from .routers import (
    auth,
    backup,
    body,
    coach,
    community,
    diet,
    engine_api,
    exercises,
    nutrition,
    photos,
    profiles,
    programs,
    recovery,
    stats,
    sync,
    templates,
    workouts,
)
from .routers.auth import ADMIN_KEY, SECRET_KEY

# Luo tietokantataulut jos niitä ei vielä ole, lisää puuttuvat sarakkeet ja
# varmista oletusprofiili + valmiit liikkeet ja yleiset ruoat.
Base.metadata.create_all(bind=engine)
ensure_columns()
ensure_default_profile()
ensure_seed_exercises()
ensure_extra_exercises()
ensure_exercise_descriptions()
ensure_seed_foods()
ensure_extra_foods()
ensure_alcohol_foods()

app = FastAPI(
    title="Treeni-ty-kalu API",
    version="0.1.0",
    description="Kehon- ja treeniseurantajärjestelmä.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Profiililukon vahvistus ------------------------------------------------
# Pääsynhallinta on VALINNAINEN: se aktivoituu vasta kun admin-PIN on asetettu
# (app_settings.admin_pin_hash). Ennen sitä middleware ei tee mitään, joten
# paikallinen yksinkäyttö toimii kuten ennen.

# Nämä /api-polut ovat aina avoimia (lukitusnäyttö ja versiotiedot tarvitsevat).
_OPEN_API = {"/api/health", "/api/version", "/api/network-info"}
_PROFILE_PATH_RE = re.compile(r"^/api/profiles/(\d+)")


def _read_auth_state(db) -> tuple[str, str | None]:
    admin_row = db.get(models.AppSetting, ADMIN_KEY)
    admin_hash = admin_row.value if admin_row else None
    secret_row = db.get(models.AppSetting, SECRET_KEY)
    secret = secret_row.value if secret_row else ""
    return secret, admin_hash


def _auth_state():
    """Lue lukon tila kannasta: (secret, admin_hash). admin_hash None = lukko pois.

    Kunnioittaa get_db-overridea (testit käyttävät omaa kantaa), muuten
    käyttää sovelluksen omaa SessionLocalia."""
    override = app.dependency_overrides.get(get_db)
    if override:
        gen = override()
        db = next(gen)
        try:
            return _read_auth_state(db)
        finally:
            gen.close()
    db = SessionLocal()
    try:
        return _read_auth_state(db)
    finally:
        db.close()


def _deny(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


@app.middleware("http")
async def profile_lock(request: Request, call_next):
    path = request.url.path
    # Vain /api/ suojataan; staattiset tiedostot, juuri ja PWA menevät läpi.
    if (not path.startswith("/api/") or path in _OPEN_API
            or path.startswith("/api/auth/")):
        return await call_next(request)

    secret, admin_hash = _auth_state()
    if not admin_hash:  # lukko pois päältä
        return await call_next(request)

    payload = security.read_token(secret, _bearer(request))
    if not payload:
        return _deny(401, "Kirjautuminen vaaditaan.")
    if payload.get("role") == "admin":
        return await call_next(request)

    # Tavallinen käyttäjä: sallittu vain oma profiili.
    own = payload.get("pid")
    # 1) Polun profiili-id (esim. /api/profiles/7)
    m = _PROFILE_PATH_RE.match(path)
    if m and int(m.group(1)) != own:
        return _deny(403, "Ei oikeutta tähän profiiliin.")
    # 2) Kyselyparametrin profile_id
    qp = request.query_params.get("profile_id")
    if qp is not None and _as_int(qp) != own:
        return _deny(403, "Ei oikeutta tähän profiiliin.")
    # 3) Pyynnön rungon profile_id (POST/PATCH/PUT)
    if request.method in ("POST", "PATCH", "PUT"):
        body_bytes = await request.body()
        bad = _body_profile_mismatch(body_bytes, own)
        if bad:
            return _deny(403, "Ei oikeutta tähän profiiliin.")

        async def receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        request._receive = receive
    return await call_next(request)


def _bearer(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    return auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else None


def _as_int(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _body_profile_mismatch(body_bytes: bytes, own: int) -> bool:
    if not body_bytes:
        return False
    try:
        data = json.loads(body_bytes)
    except (ValueError, TypeError):
        return False
    if isinstance(data, dict) and "profile_id" in data:
        return _as_int(str(data["profile_id"])) != own
    return False


app.include_router(auth.router)
app.include_router(community.router)
app.include_router(profiles.router)
app.include_router(exercises.router)
app.include_router(programs.router)
app.include_router(workouts.router)
app.include_router(engine_api.router)
app.include_router(stats.router)
app.include_router(templates.router)
app.include_router(body.router)
app.include_router(nutrition.router)
app.include_router(sync.router)
app.include_router(diet.router)
app.include_router(recovery.router)
app.include_router(backup.router)
app.include_router(photos.router)
app.include_router(coach.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


APP_VERSION = "1.1.0"


def _build_id() -> str:
    """Rakennetunniste päivitysten tunnistamiseen: git-lyhytsha jos saatavilla,
    muuten frontend/app.js:n muokkausaika. Näin näkee ollaanko uusimmassa."""
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                                      stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        if sha:
            return sha
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        appjs = root / "frontend" / "app.js"
        return datetime.utcfromtimestamp(appjs.stat().st_mtime).strftime("%Y%m%d-%H%M")
    except OSError:
        return "unknown"


@app.get("/api/version")
def version():
    """Sovelluksen versio ja rakennetunniste (näkyy 'Tietoja'-kohdassa;
    auttaa varmistamaan että laitteet ovat samassa versiossa)."""
    return {"version": APP_VERSION, "build": _build_id()}


@app.get("/api/network-info")
def network_info(request: Request):
    """Koneen lähiverkko-IP ja osoite, jolla puhelin yhdistää samassa wifissä."""
    ip = "127.0.0.1"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        pass
    port = request.url.port or 8000
    return {"lan_ip": ip, "port": port, "phone_url": f"http://{ip}:{port}"}


# Serveeraa selainkäyttöliittymä (frontend/) sovelluksen juuresta.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")

    # PWA-tiedostot juuresta (jotta service workerin scope on koko sovellus)
    @app.get("/manifest.json")
    def manifest():
        return FileResponse(FRONTEND_DIR / "manifest.json", media_type="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        return FileResponse(FRONTEND_DIR / "sw.js", media_type="application/javascript")

    @app.get("/icon.svg")
    def icon():
        return FileResponse(FRONTEND_DIR / "icon.svg", media_type="image/svg+xml")
