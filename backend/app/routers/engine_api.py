"""Laskentamoottorin API: painonkonversio ja 1RM-arviot."""
from fastapi import APIRouter

from .. import engine, schemas

router = APIRouter(prefix="/api/engine", tags=["engine"])


@router.post("/convert-scheme", response_model=schemas.SchemeConversionOut)
def convert_scheme(payload: schemas.SchemeConversionIn):
    """Laske uusi paino kun sarjaohjelma vaihtuu (esim. 4x5 -> 4x8)."""
    result = engine.convert_scheme(
        current_weight=payload.current_weight,
        current_sets=payload.current_sets,
        current_reps=payload.current_reps,
        target_sets=payload.target_sets,
        target_reps=payload.target_reps,
        current_rir=payload.current_rir,
        target_rir=payload.target_rir,
        increment=payload.increment,
    )
    return schemas.SchemeConversionOut(**result.__dict__)
