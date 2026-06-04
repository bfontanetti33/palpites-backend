import logging
import os

from fastapi import APIRouter, HTTPException, Header, Request, Response

from app.agents.football_agent import buscar_todos_jogos_copa, buscar_detalhe_partida
from app.agents.ia_agent import gerar_recomendacao
from app.models.schemas import RespostaCopa, Partida, RecomendacaoIA
from app.limiter import limiter

log = logging.getLogger(__name__)

router = APIRouter()

PREMIUM_TOKEN = os.getenv("PREMIUM_TOKEN", "token-secreto-troque-isso")


@router.get("/copa/jogos", response_model=RespostaCopa)
@limiter.limit("60/minute")  # seed estático — custo zero
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
@limiter.limit("20/minute")  # cache 4h protege quota API-Football
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


async def _verificar_acesso_recomendacao(authorization: str | None, slug: str) -> str:
    """
    Fluxo de autenticação:
    1. PREMIUM_TOKEN fixo → admin override (sem logging)
    2. JWT Supabase → verifica premium ou crédito avulso
    3. Sem token → 403
    Retorna user_id (ou "admin") se autorizado.
    """
    token = (authorization or "").removeprefix("Bearer ").strip()

    # 1. Admin override — PREMIUM_TOKEN fixo continua funcionando
    if PREMIUM_TOKEN and token == PREMIUM_TOKEN:
        return "admin"

    # 2. Sem token
    if not token:
        raise HTTPException(status_code=403, detail="Faça login para acessar.")

    # 3. Valida JWT Supabase
    from app.auth.supabase_client import (
        verify_jwt_token, get_user_premium_status,
        register_usage, deduct_avulso_credit,
    )
    payload = verify_jwt_token(token)
    if not payload:
        raise HTTPException(status_code=403, detail="Token inválido. Faça login novamente.")

    user_id = payload.get("sub", "")
    status  = await get_user_premium_status(user_id)

    if status["is_premium"]:
        await register_usage(user_id, slug)
        return user_id

    if status["avulso_credits"] > 0:
        if await deduct_avulso_credit(user_id):
            await register_usage(user_id, slug)
            return user_id

    raise HTTPException(
        status_code=403,
        detail="Acesso restrito. Assine o plano Premium para usar este recurso.",
    )


@router.get("/copa/jogos/{slug}/recomendacao", response_model=RecomendacaoIA)
@limiter.limit("5/minute")
async def recomendacao_ia(
    request: Request,
    slug: str,
    authorization: str | None = Header(default=None),
):
    """
    Gera recomendação de aposta via IA (Claude). Endpoint PREMIUM.
    Aceita: PREMIUM_TOKEN fixo (admin) ou JWT Supabase (usuário premium/avulso).
    Nunca retorna 500 — usa fallback GLOBAL_AVG quando APIs externas estão indisponíveis.
    """
    await _verificar_acesso_recomendacao(authorization, slug)

    try:
        partida = await buscar_detalhe_partida(slug)
    except Exception as e:
        log.error("buscar_detalhe_partida falhou para %s: %s", slug, e, exc_info=True)
        partida = None

    if not partida:
        raise HTTPException(status_code=404, detail="Partida não encontrada.")

    # gerar_recomendacao nunca lança exceção — usa fallback por camada.
    # O try/except abaixo é segurança extra para erros verdadeiramente inesperados.
    try:
        return await gerar_recomendacao(partida)
    except Exception as e:
        log.error("gerar_recomendacao falhou para %s: %s", slug, e, exc_info=True)
        raise HTTPException(
            status_code=503,
            detail="Serviço temporariamente indisponível. Tente novamente em instantes.",
        )
