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
    force: bool = False,
    authorization: str | None = Header(default=None),
):
    """
    Dispara pré-aquecimento em background e retorna imediatamente.
    force=true recalcula todos os jogos ignorando cache existente.
    Use /admin/validar-semana para acompanhar progresso.
    """
    _checar_token(authorization)
    import asyncio
    from datetime import datetime, timezone

    async def _run_prewarm(max_horas: int, force_recalc: bool) -> None:
        import logging
        _log = logging.getLogger("admin.prewarm")
        from app.agents.football_agent import buscar_detalhe_partida, _JOGOS
        from app.agents.ia_agent import calcular_stats, gerar_narrativa
        from app.cache import static_cache as _sc

        agora = datetime.now(timezone.utc)
        aquecidos, pulados, erros = 0, 0, 0

        # force=True: invalida player_stats + L1 para todos os slugs na janela
        # (1 disk write total, não por slug)
        if force_recalc:
            from app.agents.football_agent import _partida_cache as _l1_cache
            for jogo in _JOGOS:
                try:
                    dt = datetime.fromisoformat(jogo["data_hora_utc"].replace("Z", "+00:00"))
                    horas = (dt - agora).total_seconds() / 3600
                    if -0.5 <= horas <= max_horas:
                        _l1_cache.pop(jogo["slug"], None)
                        _sc.invalidate_player_stats(jogo["slug"], save=False)
                except Exception:
                    continue
            _sc.save_to_disk()  # 1 write para todos os slugs

        # Warm-up: garante janela de rate limit limpa antes do 1º jogo
        await asyncio.sleep(10)

        for jogo in _JOGOS:
            slug = jogo["slug"]
            try:
                dt = datetime.fromisoformat(jogo["data_hora_utc"].replace("Z", "+00:00"))
                horas = (dt - agora).total_seconds() / 3600
                if horas < -0.5 or horas > max_horas:
                    continue
            except Exception:
                continue

            if not force_recalc and _sc.get_stats(slug) is not None:
                pulados += 1
                continue

            try:
                partida = await buscar_detalhe_partida(slug)
                if partida is None:
                    erros += 1
                    continue
                stats = await calcular_stats(partida)
                await gerar_narrativa(partida, stats)
                aquecidos += 1
                _log.info("prewarm: %s ok (%d aquecidos até agora)", slug, aquecidos)
            except Exception as e:
                _log.warning("prewarm: %s erro: %s", slug, e)
                erros += 1

            await asyncio.sleep(1.5)  # pacing entre jogos — evita burst de cold-start

        _log.info("prewarm concluído: %d aquecidos, %d pulados, %d erros", aquecidos, pulados, erros)

    from app.agents.football_agent import _JOGOS
    agora = datetime.now(timezone.utc)
    pendentes = []
    from app.cache import static_cache as _sc
    for jogo in _JOGOS:
        try:
            dt = datetime.fromisoformat(jogo["data_hora_utc"].replace("Z", "+00:00"))
            horas = (dt - agora).total_seconds() / 3600
            em_janela = 0 < horas <= dias * 24
            sem_cache = _sc.get_stats(jogo["slug"]) is None
            if em_janela and (force or sem_cache):
                pendentes.append(jogo["slug"])
        except Exception:
            pass

    asyncio.create_task(_run_prewarm(dias * 24, force))
    return {
        "status": "iniciado",
        "force": force,
        "jogos_pendentes": len(pendentes),
        "slugs_pendentes": pendentes[:10],  # mostra só os primeiros 10 no retorno
        "mensagem": "Prewarm rodando em background. Use /admin/validar-semana para acompanhar.",
    }


# ── Export/snapshot do cache para versionamento ───────────────────────────────

@router.get("/admin/cache-snapshot", tags=["Admin"])
async def cache_snapshot(authorization: str | None = Header(default=None)):
    """
    Retorna o conteúdo completo de seeds/cache_partidas.json.
    Use para baixar o cache populado e commitar no git (garante que o próximo
    deploy do Railway já começa com dados — evita re-consumir quota API).
    """
    _checar_token(authorization)
    import json
    from pathlib import Path

    path = Path(__file__).parent.parent.parent / "seeds" / "cache_partidas.json"
    if not path.exists():
        return {"entradas": 0, "dados": {}}
    try:
        with open(path, encoding="utf-8") as f:
            dados = json.load(f)
        # Retorna formato canônico {slug: {...}} diretamente.
        # Assim: curl /admin/cache-snapshot > seeds/cache_partidas.json funciona sem wrapper.
        return dados
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao ler cache: {e}")


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
        "PREMIUM_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_JWT_SECRET",
        "MERCADOPAGO_ACCESS_TOKEN", "MERCADOPAGO_WEBHOOK_SECRET",
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


# ── Refresh cirúrgico de odds no cache ───────────────────────────────────────

@router.get("/admin/refresh-odds", tags=["Admin"])
async def refresh_odds(
    authorization: str | None = Header(default=None),
    dry_run: bool = False,
):
    """
    Atualiza partida.odds para todos os jogos futuros no cache.
    NÃO re-busca stats/forma/h2h (sem custo de quota API-Football).
    Invalida 'stats' de cada slug atualizado para forçar recompute de value_bets.

    dry_run=true  → só inspeciona o estado atual, sem escrever nada.
    dry_run=false → atualiza odds + invalida stats + salva no disco.
    """
    _checar_token(authorization)
    import asyncio
    from datetime import datetime, timezone
    from app.agents.odds_agent import buscar_odds_partida
    from app.agents.football_agent import _JOGOS
    from app.cache import static_cache as _sc

    agora = datetime.now(timezone.utc)

    # Filtra jogos futuros presentes no _store
    jogos_futuros = []
    for jogo in _JOGOS:
        try:
            dt = datetime.fromisoformat(jogo["data_hora_utc"].replace("Z", "+00:00"))
            if dt < agora:
                continue
        except Exception:
            continue
        if jogo["slug"] not in _sc._store:
            continue
        jogos_futuros.append(jogo)

    if dry_run:
        inspecao = []
        for jogo in jogos_futuros:
            slug = jogo["slug"]
            pj = (_sc._store[slug].get("partida") or {})
            inspecao.append({
                "slug":       slug,
                "odds_cache": bool(pj.get("odds")),
                "stats_cache": bool(_sc._store[slug].get("stats")),
            })
        sem_odds = sum(1 for x in inspecao if not x["odds_cache"])
        return {
            "dry_run":            True,
            "total_jogos_futuros": len(jogos_futuros),
            "sem_odds_no_cache":  sem_odds,
            "com_odds_no_cache":  len(inspecao) - sem_odds,
            "detalhes":           inspecao,
        }

    atualizados, sem_odds, erros = 0, 0, 0
    detalhes = []
    from app.agents.football_agent import _partida_cache as _pc

    for jogo in jogos_futuros:
        slug = jogo["slug"]
        home = jogo["time_casa"]
        away = jogo["time_fora"]

        try:
            odds = await buscar_odds_partida(home, away)
            entry = _sc._store.get(slug)
            if entry is None:
                continue

            entry = dict(entry)
            # Invalida stats para TODOS os slugs — garante Elo TSV novo no recompute
            entry["stats"] = None
            entry["recomendacao"] = None

            if odds:
                pj = dict(entry.get("partida") or {})
                pj["odds"] = odds
                entry["partida"] = pj
                atualizados += 1
                detalhes.append({
                    "slug":       slug,
                    "bookmaker":  odds.get("bookmaker"),
                    "mercados":   [k for k in odds if k not in ("bookmaker", "event_id", "bookmakers_h2h")],
                })
            else:
                sem_odds += 1
                detalhes.append({"slug": slug, "odds": None})

            _sc._store[slug] = entry
            # Limpa L1 (in-memory TTL 8h) para que odds novas sejam lidas imediatamente
            _pc.pop(slug, None)

        except Exception as e:
            erros += 1
            detalhes.append({"slug": slug, "erro": str(e)})

        await asyncio.sleep(0.3)  # respeita rate limit da Odds API

    if jogos_futuros:
        _sc.save_to_disk()

    return {
        "dry_run":             False,
        "total_jogos_futuros": len(jogos_futuros),
        "atualizados":         atualizados,
        "sem_odds":            sem_odds,
        "erros":               erros,
        "detalhes":            detalhes,
    }


# ── Validação da semana 1 Copa 2026 (Jun 11-17, 24 jogos) ────────────────────

@router.get("/admin/validar-semana", tags=["Admin"])
async def validar_semana(authorization: str | None = Header(default=None)):
    """
    Valida todos os 24 jogos da primeira semana da Copa 2026 (11-17 Jun, horário Brasília).
    Lê apenas do cache estático (sem chamadas API) — resposta instantânea.
    Verifica completude de dados, sanidade do modelo, coerência de odds e consistência interna.
    """
    _checar_token(authorization)

    from app.agents.football_agent import _JOGOS
    from app.cache import static_cache as _sc
    from app.cache.odds_cache import get_odds_dinamicas

    # ── Filtrar jogos da semana 1 (Jun 11-17 horário Brasília) ───────────────
    jogos_semana: list[dict] = []
    for jogo in _JOGOS:
        data_br = (jogo.get("data_hora_brasilia") or "")[:10]
        if "2026-06-11" <= data_br <= "2026-06-17":
            jogos_semana.append(jogo)

    # ── Processar cada jogo (só leitura de cache — sem I/O) ──────────────────
    resultados = []
    com_stats   = 0
    com_odds    = 0
    com_forma   = 0
    com_problemas = 0

    for jogo in jogos_semana:
        slug      = jogo["slug"]
        nome_casa = jogo["time_casa"]
        nome_fora = jogo["time_fora"]
        data_br   = (jogo.get("data_hora_brasilia") or "")[:10]

        issues: list[str] = []
        checks: dict = {
            "tem_stats":              False,
            "tem_forma":              False,
            "tem_odds":               False,
            "h2h_count":              0,
            "dados_insuficientes":    False,
            "probs_ok":               False,
            "lambda_ok":              False,
            "odds_margin_ok":         None,  # None = odds ausentes
            "modelo_concorda_odds":   None,
            "under_placar_coerente":  None,
            "cache_presente":         False,
        }

        try:
            # ── 1. Ler Partida do cache estático (sem API) ───────────────────
            entry        = _sc._store.get(slug) or {}
            partida_dict = entry.get("partida") or {}
            dados_insuf  = bool(entry.get("dados_insuficientes", False) if entry else True)
            cache_ok     = bool(partida_dict)

            checks["cache_presente"]      = cache_ok
            checks["dados_insuficientes"] = dados_insuf

            if not cache_ok:
                issues.append("partida não está no cache — prewarm pendente")

            # ── 2. Forma e H2H (do dict da partida em cache) ─────────────────
            forma_casa = partida_dict.get("forma_casa") or []
            forma_fora = partida_dict.get("forma_fora") or []
            h2h        = partida_dict.get("head_to_head") or []
            # odds podem estar no partida_dict ou no odds_cache dinâmico
            odds_part  = partida_dict.get("odds")
            odds_dyn   = get_odds_dinamicas(slug)
            odds       = odds_dyn or odds_part  # preferência ao mais recente (dinâmico)

            has_forma_casa = len(forma_casa) > 0
            has_forma_fora = len(forma_fora) > 0
            h2h_count      = len(h2h)
            has_odds       = odds is not None

            checks["tem_forma"]  = has_forma_casa and has_forma_fora
            checks["tem_odds"]   = has_odds
            checks["h2h_count"]  = h2h_count

            if cache_ok and not has_forma_casa:
                issues.append(f"forma_casa vazia para {nome_casa}")
            if cache_ok and not has_forma_fora:
                issues.append(f"forma_fora vazia para {nome_fora}")
            if not has_odds:
                issues.append("odds indisponíveis")
            if dados_insuf and cache_ok:
                issues.append("dados_insuficientes=True")

            # ── 3. Stats sanity ───────────────────────────────────────────────
            stats_dict = _sc.get_stats(slug)
            has_stats  = stats_dict is not None
            checks["tem_stats"] = has_stats

            if has_stats and stats_dict:
                try:
                    mg = stats_dict.get("modelo_gols") or {}
                    prob_casa  = float(mg.get("prob_vitoria_casa", 0))
                    prob_emp   = float(mg.get("prob_empate", 0))
                    prob_fora  = float(mg.get("prob_vitoria_fora", 0))
                    lc         = float(mg.get("lambda_casa", 0))
                    lf         = float(mg.get("lambda_fora", 0))

                    probs_sum_ok = abs(prob_casa + prob_emp + prob_fora - 100) < 2
                    lambda_ok    = (0.3 <= lc <= 4.0) and (0.3 <= lf <= 4.0)

                    checks["probs_ok"]  = probs_sum_ok
                    checks["lambda_ok"] = lambda_ok

                    if not mg:
                        issues.append("modelo_gols ausente nas stats")
                    if not probs_sum_ok:
                        total_prob = prob_casa + prob_emp + prob_fora
                        issues.append(
                            f"probs não somam 100%: casa={prob_casa:.1f} "
                            f"emp={prob_emp:.1f} fora={prob_fora:.1f} "
                            f"soma={total_prob:.1f}"
                        )
                    if not lambda_ok:
                        issues.append(
                            f"lambdas fora do intervalo [0.3, 4.0]: "
                            f"lambda_casa={lc:.2f} lambda_fora={lf:.2f}"
                        )
                except Exception as e_stats:
                    issues.append(f"erro ao ler stats: {e_stats}")
            elif cache_ok:
                issues.append("stats não disponíveis no cache")

            # ── 4. Odds coherence ────────────────────────────────────────────
            if has_odds and odds:
                try:
                    vc_odd  = float(odds.get("vitoria_casa", 0) or 0)
                    emp_odd = float(odds.get("empate", 0) or 0)
                    vf_odd  = float(odds.get("vitoria_fora", 0) or 0)
                    ov_odd  = float(odds.get("over25", 0) or 0)
                    un_odd  = float(odds.get("under25", 0) or 0)

                    if vc_odd > 0 and emp_odd > 0 and vf_odd > 0:
                        implied_sum = (1 / vc_odd) + (1 / emp_odd) + (1 / vf_odd)
                        margin_ok   = 1.0 <= implied_sum <= 1.15
                        checks["odds_margin_ok"] = margin_ok
                        if not margin_ok:
                            issues.append(
                                f"margem odds 1X2 fora do esperado: "
                                f"soma_probs_implícitas={implied_sum:.3f} "
                                f"(esperado 1.00-1.15)"
                            )

                    if ov_odd > 0 and un_odd > 0:
                        ou_sum = (1 / ov_odd) + (1 / un_odd)
                        ou_ok  = 1.0 <= ou_sum <= 1.10
                        checks["over_under_sum_ok"] = ou_ok
                        if not ou_ok:
                            issues.append(
                                f"margem odds over/under fora do esperado: "
                                f"soma={ou_sum:.3f} (esperado 1.00-1.10)"
                            )

                    # Model vs odds: does the model agree with the market favorite?
                    if has_stats and stats_dict:
                        mg = stats_dict.get("modelo_gols") or {}
                        prob_casa = float(mg.get("prob_vitoria_casa", 0))
                        prob_fora = float(mg.get("prob_vitoria_fora", 0))

                        odds_fav_casa = 0 < vc_odd < 2.0
                        odds_fav_fora = 0 < vf_odd < 2.0
                        model_fav_casa = prob_casa > prob_fora and prob_casa > 35
                        model_fav_fora = prob_fora > prob_casa and prob_fora > 35

                        if odds_fav_casa or odds_fav_fora:
                            concorda = (odds_fav_casa and model_fav_casa) or (
                                odds_fav_fora and model_fav_fora
                            )
                            checks["modelo_concorda_odds"] = concorda
                            if not concorda:
                                issues.append(
                                    f"modelo discorda das odds: "
                                    f"odds_fav={'casa' if odds_fav_casa else 'fora'} "
                                    f"model_prob_casa={prob_casa:.1f}% "
                                    f"model_prob_fora={prob_fora:.1f}%"
                                )
                except Exception as e_odds:
                    issues.append(f"erro ao verificar odds: {e_odds}")

            # ── 5. Internal consistency ──────────────────────────────────────
            if has_stats and stats_dict:
                try:
                    mg = stats_dict.get("modelo_gols") or {}
                    prob_under25 = float(mg.get("prob_under25", 0))
                    prob_over25  = float(mg.get("prob_over25", 0))
                    lc           = float(mg.get("lambda_casa", 0))
                    lf           = float(mg.get("lambda_fora", 0))
                    top5         = mg.get("top5_placares") or []

                    if prob_under25 > 55 and top5:
                        top_placar = top5[0]
                        placar_str = top_placar.get("placar", "0-0")
                        try:
                            partes = placar_str.split("-")
                            total_gols = int(partes[0]) + int(partes[1])
                            under_placar_ok = total_gols <= 2
                        except Exception:
                            under_placar_ok = True
                        checks["under_placar_coerente"] = under_placar_ok
                        if not under_placar_ok:
                            issues.append(
                                f"inconsistência under/placar: prob_under25={prob_under25:.1f}% "
                                f"mas placar mais provável é {placar_str} ({total_gols} gols)"
                            )

                    if lc > 0 and lf > 0:
                        lambda_total = lc + lf
                        if lambda_total > 3.0:
                            lambda_over_ok = prob_over25 > 50
                            checks["lambda_vs_over_ok"] = lambda_over_ok
                            if not lambda_over_ok:
                                issues.append(
                                    f"inconsistência lambda/over: "
                                    f"lambda_total={lambda_total:.2f} > 3.0 "
                                    f"mas prob_over25={prob_over25:.1f}% <= 50%"
                                )
                except Exception as e_cons:
                    issues.append(f"erro na consistência interna: {e_cons}")

        except Exception as e_jogo:
            issues.append(f"erro inesperado ao processar jogo: {e_jogo}")

        # ── Contagens de resumo ───────────────────────────────────────────────
        if checks["tem_stats"]:
            com_stats += 1
        if checks["tem_odds"]:
            com_odds += 1
        if checks["tem_forma"]:
            com_forma += 1

        # ── Status geral do jogo ──────────────────────────────────────────────
        if not checks["cache_presente"]:
            status = "sem_cache"
        elif checks["dados_insuficientes"]:
            status = "incompleto"
        elif any(
            k in i
            for i in issues
            for k in ("inconsistência", "discorda", "margem odds", "probs não somam", "lambdas fora")
        ):
            status = "inconsistente"
        elif any(
            i for i in issues
            if not i.startswith("odds indisponíveis")
               and "h2h" not in i.lower()
        ):
            status = "incompleto"
        else:
            status = "ok"

        if status != "ok":
            com_problemas += 1

        resultados.append({
            "slug":   slug,
            "casa":   nome_casa,
            "fora":   nome_fora,
            "data":   data_br,
            "status": status,
            "checks": checks,
            "issues": issues,
        })

    # ── Resumo global ─────────────────────────────────────────────────────────
    resumo = {
        "total_jogos":        len(jogos_semana),
        "com_stats":          com_stats,
        "com_odds":           com_odds,
        "com_forma_completa": com_forma,
        "com_problemas":      com_problemas,
        "sem_cache":          sum(1 for r in resultados if r["status"] == "sem_cache"),
    }

    return {"resumo": resumo, "jogos": resultados}


# ── Debug temporário: cronometra buscar_jogadores_destaque ────────────────────

@router.get("/admin/debug-players/{team_name}", tags=["Admin"])
async def debug_players(team_name: str, authorization: str | None = Header(default=None)):
    """Diagnóstico: mede tempo e resultado de buscar_jogadores_destaque. Remover após uso."""
    _checar_token(authorization)
    import time
    from app.agents.players_agent import buscar_jogadores_destaque
    t0 = time.monotonic()
    try:
        result = await buscar_jogadores_destaque(team_name)
        elapsed = round(time.monotonic() - t0, 1)
        return {
            "team":                team_name,
            "elapsed_s":           elapsed,
            "jogadores_count":     len(result.get("jogadores", [])),
            "jogadores_analisados": result.get("jogadores_analisados", 0),
            "dados_insuficientes": result.get("dados_insuficientes", False),
            "jogadores": [
                {"nome": j.get("nome"), "categoria": j.get("categoria"), "mins": j.get("minutos_jogados")}
                for j in result.get("jogadores", [])
            ],
        }
    except Exception as e:
        return {
            "team":      team_name,
            "elapsed_s": round(time.monotonic() - t0, 1),
            "error":     type(e).__name__,
            "detail":    str(e),
        }
