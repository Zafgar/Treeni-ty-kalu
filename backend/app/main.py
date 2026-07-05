"""Treeni-ty-kalu — FastAPI-sovellus.

Tarjoaa REST-API:n (liikkeet, ohjelmat, treenit, laskentamoottori) ja
serveeraa selainkäyttöliittymän staattisista tiedostoista. Sama palvelin
toimii PC:llä ja myöhemmin puhelimella (selain / PWA).
"""
import os
import socket
import subprocess
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import (
    Base,
    engine,
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
    backup,
    body,
    coach,
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


APP_VERSION = "1.0.0"


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
