from datetime import datetime, timedelta

from fastapi import APIRouter, Header, HTTPException
import os

router = APIRouter()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
_VERSAO     = "1.0.0"
_REGIAO     = "southamerica-east1"


def _checar_token(authorization: str | None) -> None:
    if not ADMIN_TOKEN:
        return  # endpoint aberto quando ADMIN_TOKEN não está configurado
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido.")


@router.get("/admin/stats", tags=["Admin"])
async def admin_stats():
    """
    Métricas operacionais do sistema.
    Sem autenticação — dados não sensíveis.
    """
    from app.agents.football_agent import _partida_cache, _cache as _fb_cache
    from app.monitoring.telegram_bot import state

    agora = datetime.utcnow()
    cutoff_24h = agora - timedelta(hours=24)

    # Filtra timestamps das últimas 24h
    reqs_24h   = len([t for t in state.requests_timestamps if t > cutoff_24h])
    erros_24h  = len([t for t in state.erros_timestamps     if t > cutoff_24h])
    uptime_s   = int((agora - state.startup_time).total_seconds())

    # Quotas como int se possível
    def _to_int(v: str):
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    return {
        "jogos_em_cache":       len(_partida_cache),
        "uptime_segundos":      uptime_s,
        "requests_hoje":        reqs_24h,
        "erros_500_hoje":       erros_24h,
        "quota_api_football":   _to_int(state.quota_api_football),
        "quota_odds_api":       _to_int(state.quota_odds_api),
        "versao":               _VERSAO,
        "regiao":               _REGIAO,
    }


@router.get("/admin/health-check")
async def health_check(authorization: str | None = Header(default=None)):
    """
    Status detalhado do sistema: quotas, cache, último erro, conectividade.
    Protegido por Authorization: Bearer <ADMIN_TOKEN> se configurado.
    """
    _checar_token(authorization)

    import os
    from app.agents.football_agent import _partida_cache, _cache as _fb_cache
    from app.monitoring.telegram_bot import state
    from app.auth.supabase_client import ping as supabase_ping

    agora = datetime.utcnow()
    cutoff = agora - timedelta(hours=24)
    erros_24h = len([t for t in state.erros_timestamps if t > cutoff])

    supabase_ok = await supabase_ping()
    telegram_ok = bool(
        os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")
    )

    return {
        "status": "ok",
        "timestamp": agora.isoformat() + "Z",
        "supabase_connected": supabase_ok,
        "telegram_configured": telegram_ok,
        "quota_api_football": state.quota_api_football,
        "quota_odds_api": state.quota_odds_api,
        "jogos_em_cache": len(_partida_cache),
        "api_calls_em_cache": len(_fb_cache),
        "ultimo_erro_500": state.ultimo_erro_500,
        "erros_24h": erros_24h,
    }
