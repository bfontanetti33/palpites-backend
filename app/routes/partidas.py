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
@limiter.limit("20/minute")  # cache 8h protege quota API-Football
async def detalhe_jogo(request: Request, response: Response, slug: str):
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
    response.headers["Cache-Control"] = "public, max-age=28800"  # 8h
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
    try:
        await _verificar_acesso_recomendacao(authorization, slug)
    except HTTPException:
        raise  # 403/401 são esperados — propaga normalmente
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


def _rec_valida(dados: dict) -> bool:
    """Retorna True se o dict de recomendação tem conteúdo real (não é fallback)."""
    return bool(
        dados
        and dados.get("texto_completo", "")
        and dados.get("narrativa", "")
        and "se enfrentam na Copa do Mundo 2026" not in (dados.get("narrativa") or "")
    )


@router.get("/copa/zebras")
@limiter.limit("30/minute")
async def zebras(request: Request, response: Response):
    """
    Jogos com alerta de zebra — azarão com edge estatístico real identificado pelo modelo.
    Requer recomendação gerada (premium) para o jogo aparecer aqui.
    """
    response.headers["Cache-Control"] = "public, max-age=900"   # 15min

    from app.cache import static_cache
    from app.agents.football_agent import _POR_SLUG

    agora = datetime.now(timezone.utc)
    resultado = []

    for slug, entry in static_cache._store.items():
        rec = entry.get("recomendacao")
        if not rec:
            continue
        dados = rec.get("dados", {})
        if not _rec_valida(dados):
            continue
        ctx = dados.get("contexto", {})
        if not ctx.get("zebra_alerta", False):
            continue

        jogo = _POR_SLUG.get(slug)
        if not jogo:
            continue

        # Só jogos futuros ou em andamento
        try:
            dt = datetime.fromisoformat(
                (jogo.get("data_hora_utc") or "").replace("Z", "+00:00")
            )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < agora - __import__("datetime").timedelta(hours=2):
                continue
        except Exception:
            pass

        top3 = dados.get("top3") or []
        top1 = top3[0] if top3 else {}

        resultado.append({
            "slug":            slug,
            "horario":         jogo.get("data_hora_brasilia", ""),
            "horario_utc":     jogo.get("data_hora_utc", ""),
            "time_casa_nome":  jogo["time_casa"],
            "time_casa_logo":  jogo.get("time_casa_logo", ""),
            "time_fora_nome":  jogo["time_fora"],
            "time_fora_logo":  jogo.get("time_fora_logo", ""),
            "zebra_descricao": ctx.get("zebra_descricao", ""),
            "mercado":         top1.get("mercado", ""),
            "entrada":         top1.get("entrada", ""),
            "odd_ref":         top1.get("odd_ref"),
            "prob_dc":         top1.get("prob_dc", 0.0),
            "confianca":       top1.get("confianca", ""),
        })

    resultado.sort(key=lambda x: x.get("horario_utc", ""))
    return {"total": len(resultado), "zebras": resultado}


@router.get("/copa/bingo")
@limiter.limit("30/minute")
async def bingo(request: Request, response: Response):
    """
    Apostas de alta confiança para combinações (acumuladas).
    Requer odds disponíveis e recomendação gerada para o jogo.
    """
    response.headers["Cache-Control"] = "public, max-age=900"   # 15min

    from app.cache import static_cache
    from app.agents.football_agent import _POR_SLUG

    agora = datetime.now(timezone.utc)
    candidatos = []

    for slug, entry in static_cache._store.items():
        rec = entry.get("recomendacao")
        if not rec:
            continue
        dados = rec.get("dados", {})
        if not _rec_valida(dados):
            continue
        if not dados.get("odds_disponiveis", False):
            continue

        jogo = _POR_SLUG.get(slug)
        if not jogo:
            continue

        try:
            dt = datetime.fromisoformat(
                (jogo.get("data_hora_utc") or "").replace("Z", "+00:00")
            )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < agora:
                continue
        except Exception:
            pass

        top3 = dados.get("top3") or []
        for m in top3:
            if (
                m.get("prob_dc", 0) >= 60
                and m.get("odd_ref") is not None
                and 1.3 <= (m.get("odd_ref") or 0) <= 2.5
                and m.get("value_score") is not None
                and m.get("value_score", -1) >= 0.0
                and m.get("confianca", "") in ("Alta", "Média")
            ):
                candidatos.append({
                    "slug":           slug,
                    "horario":        jogo.get("data_hora_brasilia", ""),
                    "horario_utc":    jogo.get("data_hora_utc", ""),
                    "time_casa_nome": jogo["time_casa"],
                    "time_fora_nome": jogo["time_fora"],
                    "mercado":        m.get("mercado", ""),
                    "entrada":        m.get("entrada", ""),
                    "odd_ref":        m.get("odd_ref"),
                    "prob_dc":        m.get("prob_dc", 0.0),
                    "value_score":    m.get("value_score"),
                    "confianca":      m.get("confianca", ""),
                })
                break  # 1 entrada por jogo

    candidatos.sort(key=lambda x: -(x.get("prob_dc") or 0))
    return {"total": len(candidatos), "bingo": candidatos[:10]}


@router.get("/copa/odds-baixa")
@limiter.limit("30/minute")
async def odds_baixa(request: Request, response: Response):
    """
    Apostas de alta probabilidade com odds baixas (apostas seguras).
    Prob > 65%, odd entre 1.10 e 1.70. Requer odds disponíveis.
    """
    response.headers["Cache-Control"] = "public, max-age=900"   # 15min

    from app.cache import static_cache
    from app.agents.football_agent import _POR_SLUG

    agora = datetime.now(timezone.utc)
    resultado = []

    for slug, entry in static_cache._store.items():
        rec = entry.get("recomendacao")
        if not rec:
            continue
        dados = rec.get("dados", {})
        if not _rec_valida(dados):
            continue
        if not dados.get("odds_disponiveis", False):
            continue

        jogo = _POR_SLUG.get(slug)
        if not jogo:
            continue

        try:
            dt = datetime.fromisoformat(
                (jogo.get("data_hora_utc") or "").replace("Z", "+00:00")
            )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < agora:
                continue
        except Exception:
            pass

        top3 = dados.get("top3") or []
        for m in top3:
            odd = m.get("odd_ref")
            if (
                m.get("prob_dc", 0) >= 65
                and odd is not None
                and 1.10 <= odd <= 1.70
            ):
                resultado.append({
                    "slug":           slug,
                    "horario":        jogo.get("data_hora_brasilia", ""),
                    "horario_utc":    jogo.get("data_hora_utc", ""),
                    "time_casa_nome": jogo["time_casa"],
                    "time_fora_nome": jogo["time_fora"],
                    "mercado":        m.get("mercado", ""),
                    "entrada":        m.get("entrada", ""),
                    "odd_ref":        odd,
                    "prob_dc":        m.get("prob_dc", 0.0),
                    "confianca":      m.get("confianca", ""),
                })
                break

    resultado.sort(key=lambda x: -(x.get("prob_dc") or 0))
    return {"total": len(resultado), "odds_baixa": resultado}
