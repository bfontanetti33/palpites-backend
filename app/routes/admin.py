from datetime import datetime, timedelta

from fastapi import APIRouter, Header, HTTPException
import os

router = APIRouter()

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")
_VERSAO     = "1.0.0"
_REGIAO     = "southamerica-east1"


def _checar_token(authorization: str | None) -> None:
    if not ADMIN_TOKEN:
        return
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Token inválido.")


# ── T1: Telegram test ─────────────────────────────────────────────────────────

@router.get("/admin/telegram-test", tags=["Admin"])
async def telegram_test():
    """Envia mensagem de teste no Telegram. Sem autenticação."""
    from app.monitoring.telegram_bot import send_telegram
    from datetime import datetime
    msg = (
        f"✅ <b>Palpites da IA — Telegram OK</b>\n"
        f"Mensagem de teste enviada em {datetime.utcnow().strftime('%d/%m/%Y %H:%M')} UTC\n"
        f"O bot está funcionando corretamente."
    )
    ok = await send_telegram(msg)
    if ok:
        return {"enviado": True, "erro": None}
    token_set = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    chat_set  = bool(os.getenv("TELEGRAM_CHAT_ID"))
    return {
        "enviado": False,
        "erro": (
            "Envio falhou. "
            f"TELEGRAM_BOT_TOKEN: {'✅' if token_set else '❌ ausente'}. "
            f"TELEGRAM_CHAT_ID: {'✅' if chat_set else '❌ ausente'}."
        ),
    }


# ── T2: Supabase CRUD test ────────────────────────────────────────────────────

@router.get("/admin/supabase-test", tags=["Admin"])
async def supabase_test():
    """Testa insert → select → delete no Supabase. Sem autenticação."""
    import uuid
    from app.auth.supabase_client import (
        SUPABASE_URL, SUPABASE_KEY,
        get_user_premium_status, register_usage,
    )
    import httpx

    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")

    result: dict = {
        "url_configurada": bool(url),
        "key_configurada": bool(key),
        "insert": None, "select": None, "delete": None,
        "crud_ok": False, "erro": None,
    }

    if not url or not key:
        result["erro"] = "SUPABASE_URL ou SUPABASE_KEY ausentes"
        return result

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    test_id    = str(uuid.uuid4())
    test_email = f"test-crud-{test_id[:8]}@palpitesdaia-test.com"

    async with httpx.AsyncClient(timeout=10) as c:
        # INSERT
        r = await c.post(f"{url}/rest/v1/users", headers=headers,
            json={"id": test_id, "email": test_email, "is_premium": False})
        result["insert"] = {"status": r.status_code, "ok": r.status_code in (200, 201)}
        if not result["insert"]["ok"]:
            result["erro"] = f"INSERT falhou {r.status_code}: {r.text[:300]}"
            return result

        # SELECT
        r = await c.get(f"{url}/rest/v1/users", headers=headers,
            params={"id": f"eq.{test_id}",
                    "select": "id,email,is_premium,avulso_credits"})
        data = r.json() if r.status_code == 200 else []
        result["select"] = {
            "status": r.status_code,
            "ok": r.status_code == 200 and len(data) == 1,
            "row": data[0] if data else None,
        }

        # DELETE
        r = await c.delete(f"{url}/rest/v1/users", headers=headers,
            params={"id": f"eq.{test_id}"})
        result["delete"] = {"status": r.status_code, "ok": r.status_code in (200, 204)}

    result["crud_ok"] = (
        result["insert"]["ok"] and
        result["select"]["ok"] and
        result["delete"]["ok"]
    )
    return result


# ── T4: Stats ─────────────────────────────────────────────────────────────────

@router.get("/admin/stats", tags=["Admin"])
async def admin_stats():
    """Métricas operacionais. Sem autenticação."""
    from app.agents.football_agent import _partida_cache, _cache as _fb_cache
    from app.monitoring.telegram_bot import state

    agora      = datetime.utcnow()
    cutoff_24h = agora - timedelta(hours=24)
    reqs_24h   = len([t for t in state.requests_timestamps if t > cutoff_24h])
    erros_24h  = len([t for t in state.erros_timestamps     if t > cutoff_24h])
    uptime_s   = int((agora - state.startup_time).total_seconds())

    def _to_int(v: str):
        try:
            return int(v)
        except (ValueError, TypeError):
            return None

    return {
        "jogos_em_cache":     len(_partida_cache),
        "uptime_segundos":    uptime_s,
        "requests_hoje":      reqs_24h,
        "erros_500_hoje":     erros_24h,
        "quota_api_football": _to_int(state.quota_api_football),
        "quota_odds_api":     _to_int(state.quota_odds_api),
        "versao":             _VERSAO,
        "regiao":             _REGIAO,
    }


# ── T4: Health-check completo ─────────────────────────────────────────────────

@router.get("/admin/health-check", tags=["Admin"])
async def health_check(authorization: str | None = Header(default=None)):
    """
    Status completo do sistema.
    Protegido por Bearer <ADMIN_TOKEN> se configurado.
    """
    _checar_token(authorization)

    from app.agents.football_agent import _partida_cache, _cache as _fb_cache
    from app.monitoring.telegram_bot import state
    from app.auth.supabase_client import ping as supabase_ping

    agora     = datetime.utcnow()
    cutoff    = agora - timedelta(hours=24)
    erros_24h = len([t for t in state.erros_timestamps if t > cutoff])
    uptime_s  = int((agora - state.startup_time).total_seconds())

    sb         = await supabase_ping()
    telegram_ok = bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

    def _to_int(v):
        try:
            return int(v)
        except (ValueError, TypeError):
            return v  # devolve "?" se não for número

    _vars = [
        "ANTHROPIC_API_KEY", "API_FOOTBALL_KEY", "ODDS_API_KEY",
        "PREMIUM_TOKEN", "SUPABASE_URL", "SUPABASE_KEY",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SENTRY_DSN",
    ]

    return {
        "status":              "ok",
        "timestamp":           agora.isoformat() + "Z",
        "versao":              _VERSAO,
        "regiao":              _REGIAO,
        "jogos_em_cache":      len(_partida_cache),
        "supabase_connected":  sb["conectado"],
        "supabase_ping_status": sb.get("status_code"),
        "supabase_erro":       sb.get("erro"),
        "telegram_configured": telegram_ok,
        "quota_api_football":  _to_int(state.quota_api_football),
        "quota_odds_api":      _to_int(state.quota_odds_api),
        "erros_24h":           erros_24h,
        "uptime_segundos":     uptime_s,
        "vars_configuradas":   {v: bool(os.getenv(v)) for v in _vars},
    }
