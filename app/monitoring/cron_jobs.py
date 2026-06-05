"""
Cron jobs de monitoramento — 4 tarefas em background.

Job 1 (diário, 06h BRT / 09h UTC) : staleness do cache + resumo Telegram
Job 2 (tick 30min, tiered)          : atualiza odds com frequência por proximidade:
                                       > 12h → 1×/dia | 2–12h → 1×/hora | < 2h → 30min
Job 3 (15min)                       : alerta Telegram se quota API-Football < 500
Job 4 (30min)                       : pré-aquece stats (Camadas 1-4B) para todos os jogos
                                       próximos — garante que /zebras /bingo /odds-baixa
                                       funcionem sem presença de usuário premium
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)


async def _job_cache_diario() -> None:
    while True:
        agora = datetime.now(timezone.utc)
        proximo = agora.replace(hour=9, minute=0, second=0, microsecond=0)  # 09h UTC = 06h BRT
        if agora >= proximo:
            proximo += timedelta(days=1)
        await asyncio.sleep((proximo - agora).total_seconds())

        try:
            from app.cache import static_cache
            from app.monitoring.telegram_bot import send_telegram

            s = static_cache.summary()
            await send_telegram(
                f"📦 <b>Cache diário — Palpites da IA</b>\n"
                f"Entradas: {s['total']} total | {s['frescos']} frescos | {s['stale']} stale\n"
                f"Com stats: {s['com_stats']} | Com narrativa: {s['com_narrativa']}\n"
                f"Dados insuficientes: {s['dados_insuficientes']}\n"
                f"⏰ {datetime.now(timezone.utc).strftime('%d/%m %H:%M')} UTC"
            )
        except Exception as e:
            log.error("cron_cache_diario falhou: %s", e)


def _intervalo_odds(dt_jogo: datetime, agora: datetime) -> float:
    """Retorna intervalo mínimo (segundos) para buscar odds baseado em horas até o jogo."""
    horas = (dt_jogo - agora).total_seconds() / 3600
    if horas > 12:
        return 24 * 3600   # 1×/dia
    if horas > 2:
        return 1 * 3600    # 1×/hora
    return 30 * 60         # 30min


async def _job_odds_tiered() -> None:
    """
    Tick de 30min — só chama a API se o intervalo tiered do jogo tiver passado.
    Quando novas odds chegam, recalcula stats imediatamente (event-driven).
    Estimativa: ~200–300 req/mês (bem abaixo do limite free de 500).
    """
    await asyncio.sleep(60)  # aguarda startup completo antes da 1ª execução
    while True:
        try:
            from app.cache.odds_cache import (
                set_odds_dinamicas, get_last_updated,
            )
            from app.agents.odds_agent import buscar_odds_partida as _odds_api
            from app.agents.football_agent import _JOGOS, _POR_SLUG

            agora = datetime.now(timezone.utc)

            # Busca odds para todos os jogos futuros nos próximos 14 dias
            dt_por_slug: dict[str, datetime] = {}
            for j in _JOGOS:
                slug = j["slug"]
                try:
                    dt_str = j.get("data_hora_utc") or j.get("data_hora_brasilia", "")
                    dt = datetime.fromisoformat(dt_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    horas = (dt - agora).total_seconds() / 3600
                    if 0 < horas <= 336:  # só jogos futuros até 14 dias
                        dt_por_slug[slug] = dt
                except Exception:
                    pass

            for slug, dt_jogo in dt_por_slug.items():
                if dt_jogo < agora:
                    continue

                intervalo = _intervalo_odds(dt_jogo, agora)
                ultimo = get_last_updated(slug)
                if ultimo is not None and (agora - ultimo).total_seconds() < intervalo:
                    continue

                jogo = _POR_SLUG.get(slug)
                if not jogo:
                    continue
                try:
                    odds = await _odds_api(jogo["time_casa"], jogo["time_fora"])
                    if odds:
                        set_odds_dinamicas(slug, odds)
                        # Propaga odds para _partida_cache e disco
                        partida_atualizada = None
                        try:
                            from app.agents.football_agent import _partida_cache
                            from app.cache import static_cache as _sc
                            p = _partida_cache.get(slug)
                            if p is not None and p.odds is None:
                                p_novo = p.model_copy(update={"odds": odds})
                                _partida_cache[slug] = p_novo
                                _sc.put_partida(slug, p_novo.model_dump(mode="json"))
                                partida_atualizada = p_novo
                            elif p is not None:
                                partida_atualizada = p
                        except Exception as e2:
                            log.warning("cron odds %s: falha ao propagar partida: %s", slug, e2)

                        # Event-driven: invalida stats E narrativa quando odds chegam
                        if partida_atualizada is not None:
                            try:
                                from app.cache import static_cache as _sc
                                entry = _sc._store.get(slug)
                                if entry:
                                    invalidado = False
                                    if entry.get("stats"):
                                        del entry["stats"]
                                        invalidado = True
                                    # Invalida narrativa também — foi gerada sem odds
                                    if entry.get("narrativa"):
                                        del entry["narrativa"]
                                        invalidado = True
                                    if invalidado:
                                        _sc.save_to_disk()
                                        log.info("cron odds %s: stats+narrativa invalidados para recálculo", slug)
                            except Exception as e3:
                                log.warning("cron odds %s: falha ao invalidar cache: %s", slug, e3)

                        log.debug(
                            "cron odds %s: atualizado (intervalo %.0fh)",
                            slug, intervalo / 3600,
                        )
                except Exception as e:
                    log.warning("cron odds %s: %s", slug, e)
                await asyncio.sleep(2)  # evita burst para The Odds API

        except Exception as e:
            log.error("cron_odds_tiered falhou: %s", e)

        await asyncio.sleep(1800)  # tick a cada 30min


async def _job_prewarm_stats() -> None:
    """
    Tick de 30min — pré-aquece stats (Camadas 1-4B + Score Final) para todos os jogos
    próximos com dados disponíveis. Garante que /zebras /bingo /odds-baixa funcionem
    proativamente sem depender de chamadas de usuários premium.
    """
    await asyncio.sleep(120)  # aguarda 2min após startup para caches carregarem
    while True:
        try:
            from app.agents.football_agent import buscar_detalhe_partida, _JOGOS
            from app.agents.ia_agent import calcular_stats
            from app.cache import static_cache as _sc

            agora = datetime.now(timezone.utc)
            aquecidos = 0
            erros = 0

            for jogo in _JOGOS:
                slug = jogo["slug"]
                try:
                    dt_str = jogo.get("data_hora_utc") or jogo.get("data_hora_brasilia", "")
                    dt_jogo = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    if dt_jogo.tzinfo is None:
                        dt_jogo = dt_jogo.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                # Só jogos futuros (até 14 dias) — cobre toda a fase de grupos
                horas_ate = (dt_jogo - agora).total_seconds() / 3600
                if horas_ate < -0.5 or horas_ate > 336:  # passou ou >14 dias
                    continue

                # Se stats ainda frescos, pula
                if _sc.get_stats(slug) is not None:
                    continue

                # Busca partida completa (usa cache de disco/memória — sem custo API)
                try:
                    partida = await buscar_detalhe_partida(slug)
                    if partida is None:
                        continue
                except Exception as e:
                    log.debug("prewarm %s: buscar_detalhe_partida falhou: %s", slug, e)
                    continue

                # Calcula stats — 0 chamadas API externas, só computação local
                try:
                    await calcular_stats(partida)
                    aquecidos += 1
                except Exception as e:
                    log.warning("prewarm %s: calcular_stats falhou: %s", slug, e)
                    erros += 1

                await asyncio.sleep(3)  # pausa entre jogos para respeitar rate limit da API

            if aquecidos > 0:
                log.info("prewarm_stats: %d jogos atualizados, %d erros", aquecidos, erros)

        except Exception as e:
            log.error("cron_prewarm_stats falhou: %s", e)

        await asyncio.sleep(1800)  # tick a cada 30min


async def _job_healthcheck_15min() -> None:
    await asyncio.sleep(300)  # aguarda 5min após startup antes da 1ª verificação
    while True:
        try:
            from app.monitoring.telegram_bot import state, send_telegram

            try:
                rem = int(state.quota_api_football)
                if rem < 500:
                    await send_telegram(
                        f"⚠️ <b>QUOTA BAIXA — API-Football</b>\n"
                        f"Restante: <b>{rem}</b> req/dia (< 500)\n"
                        f"⏰ {datetime.now(timezone.utc).strftime('%d/%m %H:%M')} UTC"
                    )
            except (ValueError, TypeError):
                pass
        except Exception as e:
            log.error("cron_healthcheck_15min falhou: %s", e)

        await asyncio.sleep(900)  # 15min


async def iniciar_cron_jobs() -> None:
    """Inicia os 4 cron jobs como tasks asyncio independentes."""
    asyncio.create_task(_job_cache_diario())
    asyncio.create_task(_job_odds_tiered())
    asyncio.create_task(_job_prewarm_stats())
    asyncio.create_task(_job_healthcheck_15min())
    log.info("Cron jobs iniciados: cache-diário, odds-tiered, prewarm-stats, healthcheck-15min")
