"""
Cron jobs de monitoramento — 3 tarefas em background.

Job 1 (diário, 06h BRT / 09h UTC) : staleness do cache + resumo Telegram
Job 2 (30min)                       : atualiza odds para jogos hoje/amanhã
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


async def _job_odds_30min() -> None:
    await asyncio.sleep(60)  # aguarda startup completo antes da 1ª execução
    while True:
        try:
            from app.cache.odds_cache import get_today_tomorrow_slugs, set_odds_dinamicas
            from app.agents.odds_agent import buscar_odds_partida as _odds_api
            from app.agents.football_agent import _POR_SLUG

            slugs = get_today_tomorrow_slugs()
            for slug in slugs:
                jogo = _POR_SLUG.get(slug)
                if not jogo:
                    continue
                try:
                    odds = await _odds_api(jogo["time_casa"], jogo["time_fora"])
                    if odds:
                        set_odds_dinamicas(slug, odds)
                except Exception as e:
                    log.warning("cron odds %s: %s", slug, e)
                await asyncio.sleep(2)  # evita burst para The Odds API
        except Exception as e:
            log.error("cron_odds_30min falhou: %s", e)

        await asyncio.sleep(1800)  # 30min


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
    asyncio.create_task(_job_odds_30min())
    asyncio.create_task(_job_healthcheck_15min())
    log.info("Cron jobs iniciados: cache-diário, odds-30min, healthcheck-15min")
