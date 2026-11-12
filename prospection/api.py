"""API du service de prospection, au format de web/src/types.ts (hackathon-app).

Lancer : uvicorn prospection.api:app --reload --port 8000
Swagger : http://localhost:8000/docs
"""

from __future__ import annotations

import json
import os

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

from . import writer
from .data import ALIASES, load
from .store import store

API_KEY = os.getenv("IA_API_KEY", "")

app = FastAPI(
    title="Service de prospection Givaudan",
    version="0.1.0",
    description=(
        "Charge un jeu de données de prospects, calcule un score explicable "
        "(Potentiel /60, Opportunité /30, Accessibilité /10) et rédige la fiche "
        "avec un LLM local (Ollama), avec une version par règles en secours."
    ),
)


def check_key(x_api_key: str = Header(default="")) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "En-tête X-API-Key absent ou faux.")


@app.on_event("startup")
def startup() -> None:
    store.load_default()


@app.get("/health", tags=["santé"])
def health() -> dict:
    return {"status": "ok", "dataset": store.info(), "llm": writer.llm_status()}


@app.get("/prospects", tags=["prospects"], dependencies=[Depends(check_key)])
def prospects() -> list[dict]:
    """Tous les prospects, triés par score. La rédaction du LLM n'apparaît que
    pour les fiches déjà rédigées (ouvertes, ou pré-rédigées au chargement) ;
    les autres ont la version par règles."""
    return [store.render_list_item(p) for p in store.prospects]


@app.get("/prospects/{pid}", tags=["prospects"], dependencies=[Depends(check_key)])
def prospect(pid: str, llm: bool | None = None) -> dict:
    """La fiche complète. `llm=true` force la rédaction par le LLM, `llm=false`
    celle par règles ; sans paramètre, PROSPECT_WRITER décide (règles par défaut)."""
    p = store.get(pid)
    if not p:
        raise HTTPException(404, "Aucun prospect avec cet identifiant.")
    return store.render(p, use_llm=llm)


@app.get("/datasets", tags=["données"], dependencies=[Depends(check_key)])
def dataset_info() -> dict:
    return {**store.info(), "acceptedFields": {k: v for k, v in ALIASES.items()}}


@app.post("/datasets", tags=["données"], dependencies=[Depends(check_key)])
async def upload(
    file: UploadFile = File(..., description="CSV (séparateur , ; ou tabulation) ou XLSX"),
    mapping: str = Form(
        default="",
        description='Optionnel, JSON champ -> colonne, ex. {"name": "Raison sociale"}',
    ),
) -> dict:
    """Remplace le jeu de données courant par le fichier envoyé."""
    try:
        ds = load(await file.read(), file.filename or "donnees.csv", json.loads(mapping) if mapping else None)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(422, str(e)) from e
    store.use(ds)
    return store.info()
