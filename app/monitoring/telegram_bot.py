"""
Monitoramento automático via Telegram.

Variáveis de ambiente necessárias (.env / Railway):
  TELEGRAM_BOT_TOKEN  — token do bot (obtido via @BotFather)
  TELEGRAM_CHAT_ID    — ID do chat/grupo que receberá as mensagens
  ADMIN_TOKEN         — (opcional) protege GET /admin/health-check
  ANTHROPIC_CREDIT_REMAINING — (opcional) saldo em USD para alerta < $2
"""
import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import httpx

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT  = os.getenv("TELEGRAM_CHAT_ID", "")


# ── Estado global ─────────────────────────────────────────────────────────────

@dataclass
class MonitorState:
    quota_api_football: str = "?"
    quota_odds_api: str = "?"
    ultimo_erro_500: Optional[dict] = None
    erros_timestamps: list = field(default_factory=list)
    startup_time: datetime = field(default_factory=datetime.utcnow)
    requests_timestamps: list = field(default_factory=list)  # janela de 24h
    quota_alerta_5000_enviado: bool = False  # flag: alerta 5.000/7.500 já enviado hoje


state = MonitorState()


# ── Envio Telegram ─────────────────────────────────────────────────────────────

async def send_telegram(mensagem: str) -> bool:
    """Envia mensagem para o chat configurado. Retorna True se enviou."""
    import logging as _tg_log
    _log = _tg_log.getLogger(__name__)
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        _log.warning("send_telegram: TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não configurados")
        return False
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_CHAT,
                    "text": mensagem,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            if r.status_code != 200:
                _log.warning("send_telegram: HTTP %s — %s", r.status_code, r.text[:300])
            return r.status_code == 200
    except Exception as e:
        _log.warning("send_telegram: exceção — %s", e)
        return False


# ── Alertas automáticos ────────────────────────────────────────────────────────

async def alertar_erro_500(path: str, detalhe: str) -> None:
    """Chamado pelo middleware quando ocorre um erro 500."""
    agora = datetime.utcnow()
    state.ultimo_erro_500 = {
        "timestamp": agora.isoformat() + "Z",
        "endpoint": path,
        "detalhe": detalhe[:300],
    }
    state.erros_timestamps.append(agora)
    await send_telegram(
        f"🚨 <b>ERRO 500 — Palpites da IA</b>\n"
        f"Endpoint: <code>{path}</code>\n"
        f"Detalhe: {detalhe[:200]}\n"
        f"⏰ {agora.strftime('%d/%m %H:%M:%S')} UTC"
    )


def atualizar_quota_api_football(restante: str) -> None:
    """Chamado em _get() do football_agent após cada chamada real à API."""
    state.quota_api_football = restante
    try:
        rem  = int(restante)
        used = 7500 - rem
        agora = datetime.utcnow().strftime("%d/%m %H:%M")

        # Alerta em 5.000/7.500 — enviado uma vez por ciclo diário
        if used >= 5000 and not state.quota_alerta_5000_enviado:
            state.quota_alerta_5000_enviado = True
            asyncio.create_task(
                send_telegram(
                    f"⚠️ <b>Quota API-Football: {used} req usados</b>\n"
                    f"Remaining: <b>{rem}</b> / 7.500\n"
                    f"Monitore para evitar quota zerada.\n"
                    f"⏰ {agora} UTC"
                )
            )

        # Alerta crítico quando restam menos de 20 requisições
        if rem < 20:
            asyncio.create_task(
                send_telegram(
                    f"🚨 <b>QUOTA CRÍTICA — API-Football</b>\n"
                    f"Restante: <b>{rem}</b> req/dia\n"
                    f"⏰ {agora} UTC\n"
                    f"Cache 8h ativo — novas chamadas só após renovação da quota."
                )
            )
    except (ValueError, TypeError):
        pass


def atualizar_quota_odds(restante: str) -> None:
    """Chamado em _get() do odds_agent após cada chamada real à API."""
    state.quota_odds_api = restante


def verificar_credito_anthropic() -> None:
    """Lê ANTHROPIC_CREDIT_REMAINING do env e alerta se < $2."""
    credit_str = os.getenv("ANTHROPIC_CREDIT_REMAINING", "").strip()
    if not credit_str:
        return
    try:
        credit = float(credit_str)
        if credit < 2.0:
            asyncio.create_task(
                send_telegram(
                    f"⚠️ <b>CRÉDITO BAIXO — Anthropic</b>\n"
                    f"Saldo atual: <b>${credit:.2f}</b>\n"
                    f"Recarregue em console.anthropic.com\n"
                    f"⏰ {datetime.utcnow().strftime('%d/%m %H:%M')} UTC"
                )
            )
    except (ValueError, TypeError):
        pass


# ── Resumo diário ─────────────────────────────────────────────────────────────

async def enviar_resumo_diario() -> None:
    from app.agents.football_agent import _partida_cache

    agora = datetime.utcnow()
    cutoff = agora - timedelta(hours=24)
    state.erros_timestamps = [t for t in state.erros_timestamps if t > cutoff]
    n_erros = len(state.erros_timestamps)
    n_cache = len(_partida_cache)

    # Reseta flag de alerta de quota a cada ciclo diário
    state.quota_alerta_5000_enviado = False

    verificar_credito_anthropic()

    await send_telegram(
        f"🏆 <b>Palpites da IA — Resumo {agora.strftime('%d/%m/%Y')}</b>\n"
        f"─────────────────────────\n"
        f"🌐 Status: ✅ Online\n"
        f"⚽ API-Football: {state.quota_api_football} req restantes\n"
        f"💰 Odds API: {state.quota_odds_api} req restantes\n"
        f"🤖 Jogos em cache: {n_cache}/72\n"
        f"❌ Erros últimas 24h: {n_erros}\n"
        f"─────────────────────────\n"
        f"palpitesdaia.com.br"
    )


async def loop_resumo_diario() -> None:
    """
    Background task — dispara às 11:00 UTC = 08:00 BRT.
    Inicia com o servidor via app startup event.
    """
    while True:
        agora = datetime.utcnow()
        proximo = agora.replace(hour=11, minute=0, second=0, microsecond=0)
        if agora >= proximo:
            proximo += timedelta(days=1)
        await asyncio.sleep((proximo - agora).total_seconds())
        await enviar_resumo_diario()
