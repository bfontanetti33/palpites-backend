from dotenv import load_dotenv
load_dotenv()  # antes de qualquer import que leia os.getenv() no nível de módulo

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes.partidas import router as partidas_router

app = FastAPI(
    title="Palpites da IA — Copa do Mundo 2026",
    description=(
        "API focada na Copa do Mundo FIFA 2026. "
        "Stats históricas reais de cada seleção, H2H, forma recente e "
        "probabilidades calculadas por modelo de Poisson. "
        "Nunca inventa dados — dados_insuficientes=true quando a API não retorna."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"https://.*\.lovable\.app|https://.*\.lovableproject\.com",
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(partidas_router, prefix="/api/v1", tags=["Partidas"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "palpites-da-ia"}
