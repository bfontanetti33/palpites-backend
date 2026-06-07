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


def _stats_valida(stats: dict) -> bool:
    """Retorna True se o dict de StatsRecomendacao tem dados reais calculados."""
    return bool(stats and stats.get("top3") and stats.get("modelo_gols"))


@router.get("/copa/zebras")
@limiter.limit("30/minute")
async def zebras(request: Request, response: Response):
    """
    Jogos com alerta de zebra.
    IDEAL     = critério esportivo (Elo+forma) E value de odds (is_zebra=True).
    estatística = só critério esportivo, sem odds de valor confirmadas.
    só-valor  = is_zebra=True sem sinal esportivo Elo+forma.
    Fallback: mostra zebra estatística quando odds não disponíveis.
    """
    response.headers["Cache-Control"] = "public, max-age=900"   # 15min

    from app.cache import static_cache
    from app.agents.football_agent import _POR_SLUG

    agora = datetime.now(timezone.utc)
    resultado = []

    for slug, entry in static_cache._store.items():
        # Lê da nova chave 'stats'; fallback para 'recomendacao' legado
        stats_entry = entry.get("stats") or {}
        stats = stats_entry.get("dados") if stats_entry else None
        if not stats:
            rec = entry.get("recomendacao")
            if rec:
                stats = rec.get("dados")
        if not _stats_valida(stats):
            continue

        ctx           = stats.get("contexto", {})
        zebra_alerta  = ctx.get("zebra_alerta", False)
        value_bets    = stats.get("value_bets") or []
        zebras_valor  = [vb for vb in value_bets if vb.get("is_zebra")]

        # Inclui se ao menos um dos critérios estiver ativo
        if not zebra_alerta and not zebras_valor:
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
            if dt < agora - __import__("datetime").timedelta(hours=2):
                continue
        except Exception:
            pass

        # Tipo da zebra
        if zebra_alerta and zebras_valor:
            zebra_tipo = "IDEAL"
        elif zebra_alerta:
            zebra_tipo = "estatística"
        else:
            zebra_tipo = "só-valor"

        # Palpite = top1 (sempre o 1X2 de maior prob_dc desde Parte 1)
        top3 = stats.get("top3") or []
        top1 = top3[0] if top3 else {}

        # Melhor mercado zebra por value_score
        melhor_zebra = (
            max(zebras_valor, key=lambda vb: vb.get("value_score", 0))
            if zebras_valor else None
        )

        resultado.append({
            "slug":              slug,
            "horario":           jogo.get("data_hora_brasilia", ""),
            "horario_utc":       jogo.get("data_hora_utc", ""),
            "time_casa_nome":    jogo["time_casa"],
            "time_casa_logo":    jogo.get("time_casa_logo", ""),
            "time_fora_nome":    jogo["time_fora"],
            "time_fora_logo":    jogo.get("time_fora_logo", ""),
            "zebra_descricao":   ctx.get("zebra_descricao", ""),
            "zebra_tipo":        zebra_tipo,
            # Palpite da IA (quem o modelo acha que ganha)
            "mercado":           top1.get("mercado", ""),
            "entrada":           top1.get("entrada", ""),
            "odd_ref":           top1.get("odd_ref"),
            "prob_dc":           top1.get("prob_dc", 0.0),
            "confianca":         top1.get("confianca", ""),
            # Mercado zebra de valor (se disponível)
            "mercado_zebra":     melhor_zebra,
        })

    resultado.sort(key=lambda x: x.get("horario_utc", ""))
    return {"total": len(resultado), "zebras": resultado}


@router.get("/copa/bingo")
@limiter.limit("30/minute")
async def bingo(request: Request, response: Response):
    """
    Apostas de alta confiança para combinações (acumuladas).
    Requer odds disponíveis. Populado proativamente pelo cron de stats.
    """
    response.headers["Cache-Control"] = "public, max-age=900"   # 15min

    from app.cache import static_cache
    from app.agents.football_agent import _POR_SLUG

    agora = datetime.now(timezone.utc)
    candidatos = []

    for slug, entry in static_cache._store.items():
        stats_entry = entry.get("stats") or {}
        dados = stats_entry.get("dados") if stats_entry else None
        if not dados:
            rec = entry.get("recomendacao")
            if rec:
                dados = rec.get("dados")
        if not _stats_valida(dados):
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
    Prob > 65%, odd entre 1.10 e 1.70. Populado proativamente pelo cron de stats.
    """
    response.headers["Cache-Control"] = "public, max-age=900"   # 15min

    from app.cache import static_cache
    from app.agents.football_agent import _POR_SLUG

    agora = datetime.now(timezone.utc)
    resultado = []

    for slug, entry in static_cache._store.items():
        stats_entry = entry.get("stats") or {}
        dados = stats_entry.get("dados") if stats_entry else None
        if not dados:
            rec = entry.get("recomendacao")
            if rec:
                dados = rec.get("dados")
        if not _stats_valida(dados):
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
