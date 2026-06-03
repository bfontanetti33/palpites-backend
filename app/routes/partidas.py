from fastapi import APIRouter, HTTPException, Header, Request, Response
from app.agents.football_agent import buscar_todos_jogos_copa, buscar_detalhe_partida
from app.agents.ia_agent import gerar_recomendacao
from app.models.schemas import RespostaCopa, Partida, RecomendacaoIA
from app.limiter import limiter
import os

router = APIRouter()

PREMIUM_TOKEN = os.getenv("PREMIUM_TOKEN", "token-secreto-troque-isso")


@router.get("/copa/jogos", response_model=RespostaCopa)
@limiter.limit("60/minute")
async def listar_jogos_copa(request: Request, response: Response):
    """
    Lista todos os jogos da Copa do Mundo FIFA 2026.
    Retorna status atual (NS/FT/1H/...) e placar quando disponível.
    dados_insuficientes na lista individual indica dados parciais.
    """
    response.headers["Cache-Control"] = "public, max-age=14400"  # 4h — dados estáticos do seed
    partidas = await buscar_todos_jogos_copa()
    return RespostaCopa(total=len(partidas), temporada=2026, partidas=partidas)


@router.get("/copa/jogos/{slug}", response_model=Partida)
@limiter.limit("30/minute")
async def detalhe_jogo(request: Request, slug: str):
    """
    Detalhes completos de um jogo da Copa 2026.

    Inclui:
    - Stats históricas de cada time nas Copas anteriores (fonte: Copa 2022/2018/...)
    - Forma recente (últimos 5 jogos em qualquer competição)
    - H2H: últimos 10 confrontos diretos
    - Probabilidades calculadas por modelo de Poisson

    O campo dados_insuficientes=true indica que algum dado não estava disponível
    na API — nunca são inventados ou estimados.
    """
    partida = await buscar_detalhe_partida(slug)
    if not partida:
        raise HTTPException(
            status_code=404,
            detail="Partida não encontrada. Os fixtures da Copa 2026 podem ainda não ter sido carregados na API.",
        )
    return partida


@router.get("/copa/jogos/{slug}/recomendacao", response_model=RecomendacaoIA)
@limiter.limit("3/minute")
async def recomendacao_ia(
    request: Request,
    slug: str,
    authorization: str | None = Header(default=None),
):
    """
    Gera recomendação de aposta via IA (Claude). Endpoint PREMIUM.
    Requer header: Authorization: Bearer <token>
    """
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != PREMIUM_TOKEN:
        raise HTTPException(
            status_code=403,
            detail="Acesso restrito. Assine o plano Premium para usar este recurso.",
        )
    partida = await buscar_detalhe_partida(slug)
    if not partida:
        raise HTTPException(status_code=404, detail="Partida não encontrada.")
    try:
        return await gerar_recomendacao(partida)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}")
