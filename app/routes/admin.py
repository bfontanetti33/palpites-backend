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


# ── Telegram status go-live ──────────────────────────────────────────────────

@router.get("/admin/telegram-status", tags=["Admin"])
async def telegram_status():
    """Envia mensagem de status completo formatada para go-live."""
    import httpx
    from app.agents.football_agent import _partida_cache
    from app.auth.supabase_client import ping as sb_ping
    from app.monitoring.telegram_bot import state
    import json

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat  = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        return {"enviado": False, "erro": "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausentes"}

    sb    = await sb_ping()
    cache = len(_partida_cache)

    def _to_int(v):
        try: return int(v)
        except: return v

    quota_fb  = _to_int(state.quota_api_football)
    quota_odd = _to_int(state.quota_odds_api)

    msg = (
        "🔧 <b>Debug concluído — Palpites da IA</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Backend: online\n"
        "📍 Região: São Paulo\n"
        f"⚽ Jogos em cache: {cache}/72\n"
        f"🗄️ Supabase: {'conectado ✅' if sb['conectado'] else 'erro ❌'}\n"
        f"📊 Árbitros: 20/52 com dados reais\n"
        "   (script pronto para rodar após 21h BRT)\n"
        f"🌐 Site: palpitesdaia.com.br\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <b>Pendente:</b>\n"
        "- Seed árbitros (rodar após 21h BRT)\n"
        "- Supabase conectar no Lovable\n"
        "- Mercado Pago (sábado)\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Go live: AMANHÃ 🏆"
    )

    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": msg, "parse_mode": "HTML"},
        )
        ok   = r.status_code == 200
        body = r.json()

    return {
        "enviado": ok,
        "status_code": r.status_code,
        "telegram_ok": body.get("ok"),
        "cache": cache,
        "supabase": sb["conectado"],
        "erro": None if ok else body.get("description"),
    }


# ── Telegram resumo completo ─────────────────────────────────────────────────

@router.get("/admin/telegram-resumo", tags=["Admin"])
async def telegram_resumo():
    """
    Dispara o resumo diário completo agora.
    Retorna o diagnóstico detalhado da API do Telegram se falhar.
    """
    import httpx
    from app.monitoring.telegram_bot import (
        enviar_resumo_diario, TELEGRAM_TOKEN, TELEGRAM_CHAT,
    )
    from app.agents.football_agent import _partida_cache
    from app.monitoring.telegram_bot import state

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat  = os.getenv("TELEGRAM_CHAT_ID", "")

    # Diagnóstico direto na API do Telegram antes de tentar enviar
    diag: dict = {
        "token_set":    bool(token),
        "chat_id_set":  bool(chat),
        "chat_id_valor": chat,
        "bot_info":     None,
        "send_result":  None,
        "enviado":      False,
        "erro":         None,
    }

    if not token or not chat:
        diag["erro"] = "TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID ausentes"
        return diag

    async with httpx.AsyncClient(timeout=10) as c:
        # 1. Verifica se o bot existe
        r = await c.get(f"https://api.telegram.org/bot{token}/getMe")
        if r.status_code == 200:
            bot = r.json().get("result", {})
            diag["bot_info"] = f"@{bot.get('username')} (id={bot.get('id')})"
        else:
            diag["erro"] = f"Token inválido: {r.status_code} {r.text[:200]}"
            return diag

        # 2. Monta e envia o resumo
        agora = datetime.utcnow()
        n_cache = len(_partida_cache)

        def _to_int(v):
            try: return int(v)
            except: return v

        msg = (
            f"🏆 <b>Palpites da IA — Resumo {agora.strftime('%d/%m/%Y')}</b>\n"
            f"─────────────────────────\n"
            f"🌐 Status: ✅ Online\n"
            f"⚽ API-Football: {_to_int(state.quota_api_football)} req restantes\n"
            f"💰 Odds API: {_to_int(state.quota_odds_api)} req restantes\n"
            f"🤖 Jogos em cache: {n_cache}/72\n"
            f"❌ Erros últimas 24h: {len(state.erros_timestamps)}\n"
            f"─────────────────────────\n"
            f"🔧 Vars configuradas:\n"
            f"  ANTHROPIC: {'✅' if os.getenv('ANTHROPIC_API_KEY') else '❌'} | "
            f"API-Football: {'✅' if os.getenv('API_FOOTBALL_KEY') else '❌'} | "
            f"Supabase: {'✅' if os.getenv('SUPABASE_URL') else '❌'}\n"
            f"─────────────────────────\n"
            f"palpitesdaia.com.br"
        )

        r2 = await c.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": msg, "parse_mode": "HTML"},
        )
        diag["send_result"] = {"status": r2.status_code, "body": r2.json()}
        diag["enviado"] = r2.status_code == 200

        if not diag["enviado"]:
            err = r2.json()
            diag["erro"] = (
                f"sendMessage falhou ({r2.status_code}): "
                f"{err.get('description', r2.text[:200])}"
            )

    return diag


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


# ── Pré-aquecimento on-demand ─────────────────────────────────────────────────

@router.get("/admin/prewarm", tags=["Admin"])
async def prewarm_stats(
    dias: int = 14,
    authorization: str | None = Header(default=None),
):
    """
    Pré-aquece stats (Camadas 1-4B) para todos os jogos dos próximos N dias.
    Dispara calcular_stats em background para cada jogo sem dados em cache.
    Protegido por Bearer <ADMIN_TOKEN> se configurado.
    """
    _checar_token(authorization)
    import asyncio
    from datetime import datetime, timezone

    async def _run_prewarm(max_horas: int) -> dict:
        from app.agents.football_agent import buscar_detalhe_partida, _JOGOS
        from app.agents.ia_agent import calcular_stats
        from app.cache import static_cache as _sc

        agora = datetime.now(timezone.utc)
        aquecidos, pulados, erros = 0, 0, 0

        for jogo in _JOGOS:
            slug = jogo["slug"]
            try:
                dt = datetime.fromisoformat(jogo["data_hora_utc"].replace("Z", "+00:00"))
                horas = (dt - agora).total_seconds() / 3600
                if horas < -0.5 or horas > max_horas:
                    continue
            except Exception:
                continue

            if _sc.get_stats(slug) is not None:
                pulados += 1
                continue

            try:
                partida = await buscar_detalhe_partida(slug)
                if partida is None:
                    erros += 1
                    continue
                await calcular_stats(partida)
                aquecidos += 1
            except Exception:
                erros += 1

        return {"aquecidos": aquecidos, "ja_em_cache": pulados, "erros": erros}

    resultado = await _run_prewarm(dias * 24)
    s = __import__("app.cache.static_cache", fromlist=["summary"]).summary()
    return {
        "prewarm": resultado,
        "cache_summary": s,
    }


# ── Acurácia do modelo (backtesting contínuo) ─────────────────────────────────

@router.get("/admin/acuracia", tags=["Admin"])
async def acuracia_modelo(authorization: str | None = Header(default=None)):
    """
    Acurácia em tempo real do modelo contra resultados reais da Copa 2026.
    Alimentado via scripts/registrar_resultado.py após cada jogo.
    Protegido por Bearer <ADMIN_TOKEN> se configurado.
    """
    _checar_token(authorization)
    import json
    from pathlib import Path

    historico_path = Path(__file__).parent.parent.parent / "seeds" / "historico_predicoes.json"
    if not historico_path.exists():
        return {
            "total_jogos": 0,
            "mensagem": "Nenhum resultado registrado ainda. Use scripts/registrar_resultado.py após cada jogo.",
        }

    with open(historico_path, encoding="utf-8") as f:
        data = json.load(f)

    jogos = data.get("jogos", [])
    metricas = data.get("metricas_acumuladas", {})

    return {
        "metricas": metricas,
        "ultimos_jogos": jogos[-10:],
        "total_registrados": len(jogos),
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
        "ultimo_erro_500":     state.ultimo_erro_500,
        "uptime_segundos":     uptime_s,
        "vars_configuradas":   {v: bool(os.getenv(v)) for v in _vars},
    }


# ── Diagnóstico de odds ──────────────────────────────────────────────────────

@router.get("/admin/odds-debug", tags=["Admin"])
async def odds_debug(authorization: str | None = Header(default=None)):
    """
    Testa a conexão com The Odds API e lista os eventos disponíveis.
    Útil para diagnosticar por que odds não estão carregando.
    """
    _checar_token(authorization)
    from app.agents.odds_agent import listar_eventos_copa, ODDS_API_KEY, SPORT
    resultado = {
        "odds_api_key_configurada": bool(ODDS_API_KEY),
        "sport_key": SPORT,
        "eventos": [],
        "erro": None,
    }
    try:
        eventos = await listar_eventos_copa()
        resultado["total_eventos"] = len(eventos)
        resultado["eventos"] = [
            {"id": e.get("id"), "home": e.get("home_team"), "away": e.get("away_team"),
             "commence_time": e.get("commence_time")}
            for e in eventos[:5]
        ]
    except Exception as e:
        resultado["erro"] = str(e)
    return resultado
