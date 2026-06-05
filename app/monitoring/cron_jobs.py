"""
Cron jobs de monitoramento — 3 tarefas em background.

Job 1 (diário, 06h BRT / 09h UTC) : staleness do cache + resumo Telegram
Job 2 (tick 30min, tiered)          : atualiza odds com frequência por proximidade:
                                       > 12h → 1×/dia | 2–12h → 1×/hora | < 2h → 30min
Job 3 (15min)                       : alerta Telegram se quota API-Football < 500
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
                f"Com recomendação: {s['com_recomendacao']}\n"
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
    Estimativa: ~200–300 req/mês (bem abaixo do limite free de 500).
    """
    await asyncio.sleep(60)  # aguarda startup completo antes da 1ª execução
    while True:
        try:
            from app.cache.odds_cache import (
                get_today_tomorrow_slugs, set_odds_dinamicas, get_last_updated,
            )
            from app.agents.odds_agent import buscar_odds_partida as _odds_api
            from app.agents.football_agent import _JOGOS, _POR_SLUG

            agora = datetime.now(timezone.utc)

            # Monta mapa slug → datetime do jogo para jogos hoje/amanhã
            slugs_hoje_amanha = set(get_today_tomorrow_slugs())
            dt_por_slug: dict[str, datetime] = {}
            for j in _JOGOS:
                slug = j["slug"]
                if slug not in slugs_hoje_amanha:
                    continue
                try:
                    dt_str = j.get("data_hora_utc") or j.get("data_hora_brasilia", "")
                    dt = datetime.fromisoformat(dt_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    dt_por_slug[slug] = dt
                except Exception:
                    pass

            for slug, dt_jogo in dt_por_slug.items():
                # Jogo já passou — não busca odds
                if dt_jogo < agora:
                    continue

                intervalo = _intervalo_odds(dt_jogo, agora)
                ultimo = get_last_updated(slug)
                if ultimo is not None and (agora - ultimo).total_seconds() < intervalo:
                    continue  # ainda dentro do intervalo — pula

                jogo = _POR_SLUG.get(slug)
                if not jogo:
                    continue
                try:
                    odds = await _odds_api(jogo["time_casa"], jogo["time_fora"])
                    if odds:
                        set_odds_dinamicas(slug, odds)
                        # Propaga odds para _partida_cache e disco para que
                        # recomendações já cacheadas sem odds sejam recalculadas
                        try:
                            from app.agents.football_agent import _partida_cache
                            from app.cache import static_cache as _sc
                            p = _partida_cache.get(slug)
                            if p is not None and p.odds is None:
                                _partida_cache[slug] = p.model_copy(update={"odds": odds})
                                _sc.put_partida(slug, _partida_cache[slug].model_dump(mode="json"))
                                # Invalida stats cache da recomendação para forçar recálculo
                                entry = _sc._store.get(slug)
                                if entry and (entry.get("recomendacao") or {}).get("stats_cached_at"):
                                    entry["recomendacao"]["stats_cached_at"] = "2000-01-01T00:00:00+00:00"
                                    _sc.save_to_disk()
                        except Exception as e2:
                            log.warning("cron odds %s: falha ao propagar para cache: %s", slug, e2)
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
    """Inicia os 3 cron jobs como tasks asyncio independentes."""
    asyncio.create_task(_job_cache_diario())
    asyncio.create_task(_job_odds_tiered())
    asyncio.create_task(_job_healthcheck_15min())
    log.info("Cron jobs iniciados: cache-diário, odds-tiered, healthcheck-15min")
