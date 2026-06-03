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


state = MonitorState()


# ── Envio Telegram ─────────────────────────────────────────────────────────────

async def send_telegram(mensagem: str) -> bool:
    """Envia mensagem para o chat configurado. Retorna True se enviou."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
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
            return r.status_code == 200
    except Exception:
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
        if int(restante) < 20:
            asyncio.create_task(
                send_telegram(
                    f"⚠️ <b>QUOTA BAIXA — API-Football</b>\n"
                    f"Restante: <b>{restante}</b> req/dia\n"
                    f"⏰ {datetime.utcnow().strftime('%d/%m %H:%M')} UTC\n"
                    f"Ação: pré-cache já está ativo, requests param quando cache expira."
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
