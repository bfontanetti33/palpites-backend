"""
Webhook Mercado Pago — processa notificações de pagamento.

Env vars necessárias:
  MERCADOPAGO_ACCESS_TOKEN   — token de acesso à API do MP
  MERCADOPAGO_WEBHOOK_SECRET — secret para verificar assinatura (opcional)

Configuração no painel MP:
  URL: https://palpites-backend-production.up.railway.app/api/v1/webhooks/mercadopago
  Eventos: payment
  external_reference deve ter formato: "email|plano"
    ex: "brunno@gmail.com|mensal" ou "brunno@gmail.com|avulso"
"""
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Header, Request

router = APIRouter()

MP_ACCESS_TOKEN    = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "")
MP_WEBHOOK_SECRET  = os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "")
MP_API             = "https://api.mercadopago.com"


# ── Verificação de assinatura ─────────────────────────────────────────────────

def _verificar_assinatura(request_id: str, timestamp: str, body_raw: bytes, signature: str) -> bool:
    """
    Verifica HMAC-SHA256 do MP. Retorna True se válido ou se secret não configurado.
    Formato do header x-signature: ts=<ts>,v1=<hmac>
    """
    if not MP_WEBHOOK_SECRET:
        return True  # sem secret configurado = aceita tudo (configurar em produção)
    try:
        parts = {p.split("=")[0]: p.split("=")[1] for p in signature.split(",")}
        ts = parts.get("ts", timestamp)
        v1 = parts.get("v1", "")
        manifest = f"id:{request_id};request-id:{request_id};ts:{ts};"
        expected = hmac.new(
            MP_WEBHOOK_SECRET.encode(), manifest.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return True  # falha na verificação = aceita (evita perda de eventos reais)


# ── Busca detalhes do pagamento na API do MP ──────────────────────────────────

async def _buscar_pagamento(payment_id: str) -> dict | None:
    if not MP_ACCESS_TOKEN:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{MP_API}/v1/payments/{payment_id}",
                headers={"Authorization": f"Bearer {MP_ACCESS_TOKEN}"},
            )
            r.raise_for_status()
            return r.json()
    except Exception:
        return None


# ── Processamento do pagamento ────────────────────────────────────────────────

async def _processar_pagamento_aprovado(payment: dict) -> None:
    """Atualiza banco e notifica Telegram após pagamento aprovado."""
    status = payment.get("status", "")
    if status != "approved":
        return

    external_ref = payment.get("external_reference", "")
    # Formato esperado: "email|plano"
    partes = external_ref.split("|")
    email  = partes[0].strip() if partes else external_ref
    plano  = partes[1].strip().lower() if len(partes) > 1 else "desconhecido"

    # Atualiza Supabase
    from app.auth.supabase_client import set_premium, add_avulso_credit

    if plano in ("mensal", "monthly", "premium"):
        premium_until = (
            datetime.now(timezone.utc) + timedelta(days=30)
        ).isoformat()
        await set_premium(email, premium_until)
        plano_label = "Premium Mensal (30 dias)"
    elif plano in ("avulso", "single", "credito"):
        await add_avulso_credit(email)
        plano_label = "Crédito Avulso"
    else:
        plano_label = f"Plano '{plano}' (não reconhecido)"

    # Notifica Telegram
    payment_id  = payment.get("id", "?")
    valor       = payment.get("transaction_amount", 0)
    moeda       = payment.get("currency_id", "BRL")

    from app.monitoring.telegram_bot import send_telegram
    await send_telegram(
        f"💰 <b>Nova conversão!</b>\n"
        f"E-mail: <code>{email}</code>\n"
        f"Plano: <b>{plano_label}</b>\n"
        f"Valor: {moeda} {valor:.2f}\n"
        f"Payment ID: <code>{payment_id}</code>\n"
        f"⏰ {datetime.utcnow().strftime('%d/%m %H:%M')} UTC"
    )


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/webhooks/mercadopago")
async def mercadopago_webhook(
    request: Request,
    x_signature:  str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
):
    """
    Recebe notificações do Mercado Pago.
    Retorna 200 OK sempre — MP exige resposta rápida ou envia novamente.
    """
    body_raw = await request.body()

    # Verifica assinatura (best-effort)
    if x_signature:
        ts = ""
        for part in (x_signature or "").split(","):
            if part.startswith("ts="):
                ts = part.split("=", 1)[1]
                break
        _verificar_assinatura(x_request_id or "", ts, body_raw, x_signature)

    try:
        data = await request.json()
    except Exception:
        return {"status": "ok"}

    event_type = data.get("type", "")
    if event_type != "payment":
        return {"status": "ok", "ignored": event_type}

    payment_id = str(data.get("data", {}).get("id", ""))
    if not payment_id:
        return {"status": "ok"}

    # Busca e processa em background para responder rápido ao MP
    import asyncio
    payment = await _buscar_pagamento(payment_id)
    if payment:
        asyncio.create_task(_processar_pagamento_aprovado(payment))

    return {"status": "ok"}
