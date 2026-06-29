"""Treeni-ty-kalu — FastAPI-sovellus.

Tarjoaa REST-API:n (liikkeet, ohjelmat, treenit, laskentamoottori) ja
serveeraa selainkäyttöliittymän staattisista tiedostoista. Sama palvelin
toimii PC:llä ja myöhemmin puhelimella (selain / PWA).
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import (
    Base,
    engine,
    ensure_columns,
    ensure_default_profile,
    ensure_seed_exercises,
    ensure_seed_foods,
)
from .routers import (
    body,
    diet,
    engine_api,
    exercises,
    nutrition,
    profiles,
    programs,
    stats,
    templates,
    workouts,
)

# Luo tietokantataulut jos niitä ei vielä ole, lisää puuttuvat sarakkeet ja
# varmista oletusprofiili + valmiit liikkeet ja yleiset ruoat.
Base.metadata.create_all(bind=engine)
ensure_columns()
ensure_default_profile()
ensure_seed_exercises()
ensure_seed_foods()

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
app.include_router(diet.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serveeraa selainkäyttöliittymä (frontend/) sovelluksen juuresta.
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
