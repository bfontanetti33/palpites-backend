from datetime import datetime, timedelta

from fastapi import APIRouter, Header, HTTPException
import os

router = APIRouter()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")


def _checar_token(authorization: str | None) -> None:
    if not ADMIN_TOKEN:
        return  # endpoint aberto quando ADMIN_TOKEN não está configurado
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido.")


@router.get("/admin/health-check")
async def health_check(authorization: str | None = Header(default=None)):
    """
    Status detalhado do sistema: quotas, cache, último erro.
    Protegido por Authorization: Bearer <ADMIN_TOKEN> se configurado.
    """
    _checar_token(authorization)

    from app.agents.football_agent import _partida_cache, _cache as _fb_cache
    from app.monitoring.telegram_bot import state

    agora = datetime.utcnow()
    cutoff = agora - timedelta(hours=24)
    erros_24h = len([t for t in state.erros_timestamps if t > cutoff])

    return {
        "status": "ok",
        "timestamp": agora.isoformat() + "Z",
        "quota_api_football": state.quota_api_football,
        "quota_odds_api": state.quota_odds_api,
        "jogos_em_cache": len(_partida_cache),
        "api_calls_em_cache": len(_fb_cache),
        "ultimo_erro_500": state.ultimo_erro_500,
        "erros_24h": erros_24h,
    }
