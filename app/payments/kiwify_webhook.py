"""
Kiwify — webhook de notificações de pagamento.

Env var:
  KIWIFY_WEBHOOK_TOKEN — token configurado no painel Kiwify

Eventos tratados:
  order_approved       — ativa/acumula premium
  subscription_renewed — acumula mais dias no mesmo plano
  outros               — logados e ignorados (sempre 200)
"""
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.auth.supabase_client import (
    add_avulso_credit,
    get_user_id_by_email,
    get_user_premium_status,
    set_premium,
)

log = logging.getLogger(__name__)
router = APIRouter()

KIWIFY_TOKEN = os.getenv("KIWIFY_WEBHOOK_TOKEN", "")

# product_id (UUID) → plano — confirmados via redirect dos links de checkout
_PRODUTOS: dict[str, dict] = {
    "7f8404a0-6865-11f1-87c8-9f90b522aa21": {"dias": 7,  "credito": False, "nome": "semanal"},
    "7de8c0a0-6864-11f1-96d1-ebb444055bc7": {"dias": 30, "credito": False, "nome": "mensal"},
    # ÚNICO (Análise Avulsa): product_id desconhecido — detectado por ausência de Subscription
}

_EVENTOS_ATIVOS = {"order_approved", "subscription_renewed"}


def _verificar_assinatura(body_bytes: bytes, signature: str) -> bool:
    """HMAC-SHA1 do body com KIWIFY_TOKEN como chave."""
    if not KIWIFY_TOKEN or not signature:
        return False
    try:
        expected = hmac.new(KIWIFY_TOKEN.encode(), body_bytes, hashlib.sha1).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


async def _processar_kiwify(body: dict) -> None:
    evento       = body.get("webhook_event_type", "")
    order_status = body.get("order_status", "")
    order_id     = body.get("order_id", "")

    if evento not in _EVENTOS_ATIVOS:
        log.warning("KIWIFY: evento ignorado — %s order_id=%s", evento, order_id)
        return

    if order_status != "paid":
        log.warning("KIWIFY: order_status=%s ignorado (order_id=%s)", order_status, order_id)
        return

    tracking       = body.get("TrackingParameters") or {}
    src_email      = (tracking.get("src") or "").strip().lower()
    customer       = body.get("Customer") or {}
    customer_email = (customer.get("email") or "").strip().lower()
    # src = email da conta logada (prioridade); fallback = email do checkout Kiwify
    email_conta = src_email or customer_email
    if not email_conta:
        log.warning("KIWIFY: email ausente — order_id=%s", order_id)
        return

    product      = body.get("Product") or {}
    product_id   = product.get("product_id", "")
    product_name = product.get("product_name", "")
    subscription = body.get("Subscription")

    # Resolve plano pelo product_id; fallback avulso se sem Subscription
    plano = _PRODUTOS.get(product_id)
    if plano is None:
        if not subscription:
            plano = {"dias": 1, "credito": True, "nome": "avulso-kiwify"}
            log.warning(
                "KIWIFY: product_id desconhecido '%s' ('%s') sem Subscription → avulso",
                product_id, product_name,
            )
        else:
            log.warning(
                "KIWIFY: product_id desconhecido '%s' ('%s') com Subscription → IGNORADO "
                "(adicione ao _PRODUTOS em kiwify_webhook.py)",
                product_id, product_name,
            )
            return

    user_id = await get_user_id_by_email(email_conta)
    if not user_id:
        import asyncio
        from app.monitoring.telegram_bot import send_telegram
        asyncio.create_task(send_telegram(
            f"⚠️ <b>KIWIFY — pagamento sem conta</b>\n"
            f"order_id: <code>{order_id}</code>\n"
            f"src (conta): <code>{src_email or '(vazio)'}</code>\n"
            f"email checkout: <code>{customer_email}</code>\n"
            f"plano: {plano['nome']}\n"
            f"👉 Conceder acesso manual no Supabase"
        ))
        log.warning(
            "KIWIFY: usuário não encontrado — src=%s customer_email=%s order_id=%s",
            src_email, customer_email, order_id,
        )
        return

    if plano["credito"]:
        await add_avulso_credit(email_conta)
        log.warning("KIWIFY: crédito avulso adicionado — email=%s order_id=%s", email_conta, order_id)
        return

    # Acumula premium (mesmo padrão do MP: base = max(agora, expiry_atual))
    dias = plano["dias"]
    status_atual = await get_user_premium_status(user_id)
    current_until_str = status_atual.get("premium_until")
    now_utc = datetime.now(timezone.utc)

    if current_until_str:
        try:
            current_until = datetime.fromisoformat(current_until_str.replace("Z", "+00:00"))
            base = max(now_utc, current_until)
        except ValueError:
            base = now_utc
    else:
        base = now_utc

    premium_until = (base + timedelta(days=dias)).isoformat()
    await set_premium(user_id, premium_until, email=email_conta)
    log.warning(
        "KIWIFY: premium ativado — email=%s plano=%s dias=%d until=%s order_id=%s",
        email_conta, plano["nome"], dias, premium_until, order_id,
    )


@router.post("/webhooks/kiwify")
async def kiwify_webhook(
    request: Request,
    signature: str | None = Query(default=None),
):
    body_bytes = await request.body()

    if not KIWIFY_TOKEN:
        log.warning("KIWIFY: KIWIFY_WEBHOOK_TOKEN não configurado — webhook ignorado")
        return JSONResponse(status_code=200, content={"status": "ok"})

    if not _verificar_assinatura(body_bytes, signature or ""):
        log.warning("KIWIFY: assinatura inválida — signature=%s", signature)
        return JSONResponse(status_code=200, content={"status": "ok"})

    try:
        body = json.loads(body_bytes)
    except Exception:
        log.warning("KIWIFY: payload não é JSON — %s", body_bytes[:200])
        return JSONResponse(status_code=200, content={"status": "ok"})

    try:
        await _processar_kiwify(body)
    except Exception as exc:
        log.warning("KIWIFY: erro inesperado — %s", exc, exc_info=True)

    return JSONResponse(status_code=200, content={"status": "ok"})
