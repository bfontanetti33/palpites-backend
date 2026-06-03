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


@router.get("/admin/test-supabase", tags=["Admin"])
async def test_supabase():
    """Teste de conexão Supabase — insere, busca e remove usuário de teste."""
    import uuid, os, httpx
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    result: dict = {
        "supabase_url_configurada": bool(url),
        "supabase_key_configurada": bool(key),
        "insert": None, "select": None, "delete": None, "erro": None,
    }
    if not url or not key:
        result["erro"] = "SUPABASE_URL ou SUPABASE_KEY não configurados"
        return result

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    test_id    = str(uuid.uuid4())
    test_email = f"test-{test_id[:8]}@palpitesdaia-test.com"

    async with httpx.AsyncClient(timeout=10) as c:
        # INSERT
        try:
            r = await c.post(f"{url}/rest/v1/users", headers=headers,
                json={"id": test_id, "email": test_email})
            result["insert"] = {"status": r.status_code, "ok": r.status_code in (200, 201)}
            if r.status_code not in (200, 201):
                result["erro"] = f"INSERT falhou: {r.status_code} — {r.text[:200]}"
                return result
        except Exception as e:
            result["erro"] = f"INSERT exception: {e}"
            return result

        # SELECT
        try:
            r = await c.get(f"{url}/rest/v1/users", headers=headers,
                params={"id": f"eq.{test_id}", "select": "id,email,is_premium,avulso_credits"})
            data = r.json()
            result["select"] = {
                "status": r.status_code,
                "ok": r.status_code == 200 and len(data) == 1,
                "row": data[0] if data else None,
            }
        except Exception as e:
            result["select"] = {"ok": False, "erro": str(e)}

        # DELETE
        try:
            r = await c.delete(f"{url}/rest/v1/users", headers=headers,
                params={"id": f"eq.{test_id}"})
            result["delete"] = {"status": r.status_code, "ok": r.status_code in (200, 204)}
        except Exception as e:
            result["delete"] = {"ok": False, "erro": str(e)}

    result["conexao_ok"] = (
        result["insert"]["ok"] and
        result["select"]["ok"] and
        result["delete"]["ok"]
    )
    return result


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
