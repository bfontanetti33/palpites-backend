import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Header, Request, Response

from app.agents.football_agent import buscar_todos_jogos_copa, buscar_detalhe_partida
from app.agents.ia_agent import gerar_recomendacao
from app.models.schemas import RespostaCopa, Partida, RecomendacaoIA
from app.limiter import limiter

log = logging.getLogger(__name__)

router = APIRouter()

PREMIUM_TOKEN = os.getenv("PREMIUM_TOKEN", "token-secreto-troque-isso")

JOGOS_LIBERADOS: frozenset[str] = frozenset({
    "mexico-south-africa",
    "brazil-morocco",
    "south-korea-czech-republic",
    "usa-paraguay",
    "canada-bosnia-and-herzegovina",
    "qatar-switzerland",
    "haiti-scotland",
    "australia-türkiye",
    "germany-curaçao",
    "netherlands-japan",
    "ivory-coast-ecuador",
    "sweden-tunisia",
})
_MSG_BLOQUEIO = "🔓 Análise completa em breve — comece pelos 3 jogos de estreia, grátis."


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
    for p in partidas:
        if p.slug not in JOGOS_LIBERADOS:
            p.bloqueado = True
            p.mensagem_bloqueio = _MSG_BLOQUEIO
    return RespostaCopa(total=len(partidas), temporada=2026, partidas=partidas)


@router.get("/copa/jogos/{slug}", response_model=Partida)
@limiter.limit("20/minute")  # cache 8h protege quota API-Football
async def detalhe_jogo(
    request: Request,
    response: Response,
    slug: str,
    authorization: str | None = Header(default=None),
):
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
    if slug not in JOGOS_LIBERADOS:
        await _verificar_acesso(authorization)
        response.headers["Cache-Control"] = "private, max-age=300"
    else:
        response.headers["Cache-Control"] = "public, max-age=28800"  # 8h
    partida = await buscar_detalhe_partida(slug)
    if not partida:
        raise HTTPException(
            status_code=404,
            detail="Partida não encontrada. Os fixtures da Copa 2026 podem ainda não ter sido carregados na API.",
        )
    return partida


async def _verificar_acesso(authorization: str | None) -> str:
    """
    Valida token SEM consumir crédito avulso. Retorna user_id ou "admin".
    Usado pelo endpoint de detalhe — só confirma quem pode ver, não cobra.
    """
    token = (authorization or "").removeprefix("Bearer ").strip()

    if PREMIUM_TOKEN and token == PREMIUM_TOKEN:
        return "admin"

    if not token:
        raise HTTPException(status_code=403, detail="Faça login para acessar.")

    from app.auth.supabase_client import verify_jwt_token, get_user_premium_status
    payload = verify_jwt_token(token)
    if not payload:
        raise HTTPException(status_code=403, detail="Token inválido. Faça login novamente.")

    user_id = payload.get("sub", "")
    status  = await get_user_premium_status(user_id)

    if status["is_premium"] or status["avulso_credits"] > 0:
        return user_id

    raise HTTPException(
        status_code=403,
        detail="Acesso restrito. Assine o plano Premium para usar este recurso.",
    )


async def _verificar_acesso_recomendacao(authorization: str | None, slug: str) -> str:
    """
    Valida token E consome crédito avulso (se aplicável). Retorna user_id ou "admin".
    Usado pelo endpoint de recomendação — cobra 1 crédito por análise avulsa.
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
    if slug not in JOGOS_LIBERADOS:
        try:
            await _verificar_acesso_recomendacao(authorization, slug)
        except HTTPException:
            raise
        except Exception as e:
            log.error("_verificar_acesso_recomendacao falhou para %s: %s", slug, e, exc_info=True)
            raise HTTPException(status_code=503, detail="Erro interno de autenticação. Tente novamente.")

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


@router.get("/usuario/assinatura")
@limiter.limit("30/minute")
async def assinatura_usuario(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """
    Retorna o status de assinatura do usuário autenticado.
    Usado pelo frontend para saber o que bloquear/desbloquear sem tentar /recomendacao.

    Auth: Bearer <JWT Supabase> (usuário logado no site).
    PREMIUM_TOKEN NÃO deve ser usado pelo frontend — é só para testes manuais.
    """
    token = (authorization or "").removeprefix("Bearer ").strip()

    if not token:
        raise HTTPException(status_code=403, detail="Faça login para continuar.")

    # Admin/teste manual — nunca embutir no frontend
    if PREMIUM_TOKEN and token == PREMIUM_TOKEN:
        return {
            "is_premium": True,
            "premium_until": None,
            "avulso_credits": 999,
            "email": "admin",
        }

    from app.auth.supabase_client import verify_jwt_token, get_user_premium_status
    payload = verify_jwt_token(token)
    if not payload:
        raise HTTPException(status_code=403, detail="Token inválido. Faça login novamente.")

    user_id = payload.get("sub", "")
    email   = payload.get("email", "") or payload.get("sub", "")

    if not user_id:
        raise HTTPException(status_code=403, detail="Token sem identificador de usuário.")

    status = await get_user_premium_status(user_id)

    return {
        "is_premium":      status["is_premium"],
        "premium_until":   status["premium_until"],
        "avulso_credits":  status["avulso_credits"],
        "email":           email,
    }


def _stats_valida(stats: dict) -> bool:
    """Retorna True se o dict de StatsRecomendacao tem dados reais calculados."""
    return bool(stats and stats.get("top3") and stats.get("modelo_gols"))


@router.get("/copa/zebras")
@limiter.limit("30/minute")
async def zebras(request: Request, response: Response):
    """Temporariamente vazio no lançamento grátis."""
    response.headers["Cache-Control"] = "public, max-age=900"
    return {"total": 0, "zebras": []}


@router.get("/copa/bingo")
@limiter.limit("30/minute")
async def bingo(request: Request, response: Response):
    """Temporariamente vazio no lançamento grátis."""
    response.headers["Cache-Control"] = "public, max-age=900"
    return {"total": 0, "bingo": []}


@router.get("/copa/odds-baixa")
@limiter.limit("30/minute")
async def odds_baixa(request: Request, response: Response):
    """Temporariamente vazio no lançamento grátis."""
    response.headers["Cache-Control"] = "public, max-age=900"
    return {"total": 0, "odds_baixa": []}
