"""
Mercado Pago — webhook de notificações + criação de preferência (Checkout Pro).

Env vars necessárias:
  MERCADOPAGO_ACCESS_TOKEN   — token de acesso à API do MP
  MERCADOPAGO_WEBHOOK_SECRET — secret para verificar assinatura HMAC (obrigatório)

Configuração no painel MP:
  URL webhook: https://palpites-backend-production.up.railway.app/api/v1/webhooks/mercadopago
  Eventos: payment
  external_reference: "email|plano"
    ex: "brunno@gmail.com|mensal" | "brunno@gmail.com|semanal" | "brunno@gmail.com|jogo"
"""
import hashlib
import hmac
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()

MP_ACCESS_TOKEN   = os.getenv("MERCADOPAGO_ACCESS_TOKEN", "")
MP_WEBHOOK_SECRET = os.getenv("MERCADOPAGO_WEBHOOK_SECRET", "")
MP_API            = "https://api.mercadopago.com"
BACKEND_URL       = os.getenv("BACKEND_URL", "https://palpites-backend-production.up.railway.app")
FRONTEND_URL      = os.getenv("FRONTEND_URL", "https://palpitesdaia.com.br")

# Planos disponíveis — fonte única de verdade para webhook e /criar-preferencia
_PLANOS: dict[str, dict] = {
    "jogo":    {"dias": 1,  "credito": True,  "label": "Palpites da IA — Análise Avulsa (24h)", "preco": 2.90},
    "semanal": {"dias": 7,  "credito": False, "label": "Palpites da IA — Plano Semanal",        "preco": 6.90},
    "mensal":  {"dias": 30, "credito": False, "label": "Palpites da IA — Plano Mensal",         "preco": 14.90},
    # aliases legados (não expor no /criar-preferencia)
    "avulso":  {"dias": 1,  "credito": True,  "label": "Palpites da IA — Análise Avulsa (24h)", "preco": 2.90},
    "single":  {"dias": 1,  "credito": True,  "label": "Palpites da IA — Análise Avulsa (24h)", "preco": 2.90},
    "credito": {"dias": 1,  "credito": True,  "label": "Palpites da IA — Análise Avulsa (24h)", "preco": 2.90},
    "monthly": {"dias": 30, "credito": False, "label": "Palpites da IA — Plano Mensal",         "preco": 14.90},
    "premium": {"dias": 30, "credito": False, "label": "Palpites da IA — Plano Mensal",         "preco": 14.90},
}

_PLANOS_PUBLICOS = ("jogo", "semanal", "mensal")


# ── Verificação de assinatura HMAC (fail-closed) ──────────────────────────────

def _verificar_assinatura(data_id: str, request_id: str, ts: str, signature: str) -> bool:
    """
    Verifica HMAC-SHA256 do MP. Fail-closed: retorna False se qualquer coisa falhar.
    Manifest: id:{data_id};request-id:{request_id};ts:{ts};
    """
    if not MP_WEBHOOK_SECRET or not signature:
        return False
    try:
        parts = dict(p.split("=", 1) for p in signature.split(",") if "=" in p)
        v1 = parts.get("v1", "")
        manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
        expected = hmac.new(
            MP_WEBHOOK_SECRET.encode(), manifest.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, v1)
    except Exception:
        return False


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
    except Exception as e:
        log.warning("_buscar_pagamento(%s) falhou: %s", payment_id, e)
        return None


# ── Processamento do pagamento aprovado ──────────────────────────────────────

async def _processar_pagamento_aprovado(payment: dict) -> None:
    try:
        await _processar_pagamento_aprovado_inner(payment)
    except Exception as e:
        log.error("_processar_pagamento_aprovado: exceção não capturada — %s", e, exc_info=True)


async def _processar_pagamento_aprovado_inner(payment: dict) -> None:
    if payment.get("status") != "approved":
        return

    external_ref = payment.get("external_reference", "")
    partes = external_ref.split("|")
    email  = partes[0].strip() if partes else external_ref
    plano  = partes[1].strip().lower() if len(partes) > 1 else "desconhecido"

    plano_info = _PLANOS.get(plano)

    from app.auth.supabase_client import (
        set_premium, add_avulso_credit, get_user_id_by_email,
    )
    from app.monitoring.telegram_bot import send_telegram

    payment_id = payment.get("id", "?")
    valor      = payment.get("transaction_amount", 0)
    moeda      = payment.get("currency_id", "BRL")

    if not plano_info:
        plano_label = f"Plano '{plano}' não reconhecido"
        log.error("_processar_pagamento_aprovado: plano '%s' desconhecido (payment %s)", plano, payment_id)
    elif plano_info["credito"]:
        # Planos avulsos = crédito por jogo (add_avulso_credit já faz lookup por email)
        await add_avulso_credit(email)
        plano_label = plano_info["label"]
    else:
        # Planos baseados em tempo — precisa do user_id
        user_id = await get_user_id_by_email(email)
        if not user_id:
            plano_label = f"[ERRO: conta não encontrada] {plano_info['label']}"
            log.error(
                "_processar_pagamento_aprovado: user_id não encontrado para email=%s plano=%s payment=%s",
                email, plano, payment_id,
            )
        else:
            dias = plano_info["dias"]
            premium_until = (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat()
            await set_premium(user_id, premium_until, email=email)
            plano_label = plano_info["label"]

    await send_telegram(
        f"\U0001f4b0 <b>Nova conversão!</b>\n"
        f"E-mail: <code>{email}</code>\n"
        f"Plano: <b>{plano_label}</b>\n"
        f"Valor: {moeda} {valor:.2f}\n"
        f"Payment ID: <code>{payment_id}</code>\n"
        f"⏰ {datetime.utcnow().strftime('%d/%m %H:%M')} UTC"
    )


# ── Webhook ───────────────────────────────────────────────────────────────────

@router.post("/webhooks/mercadopago")
async def mercadopago_webhook(
    request: Request,
    x_signature:  str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
):
    """
    Recebe notificações do Mercado Pago.
    FAIL-CLOSED: rejeita se MERCADOPAGO_WEBHOOK_SECRET não configurado ou assinatura inválida.
    """
    body_raw = await request.body()

    # 1. Fail-closed: secret obrigatório
    if not MP_WEBHOOK_SECRET:
        log.error("webhook MP recebido mas MERCADOPAGO_WEBHOOK_SECRET não configurado — rejeitando")
        return JSONResponse(status_code=403, content={"status": "erro", "detalhe": "Webhook não configurado."})

    # 2. Extrai timestamp da assinatura
    ts = ""
    for part in (x_signature or "").split(","):
        if part.startswith("ts="):
            ts = part.split("=", 1)[1]
            break

    # 3. Parseia body antes de verificar (data_id faz parte do manifest)
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"status": "erro", "detalhe": "Body inválido."})

    data_id = str(data.get("data", {}).get("id", ""))

    # 4. Enforça verificação de assinatura
    if not _verificar_assinatura(data_id, x_request_id or "", ts, x_signature or ""):
        log.warning("webhook MP com assinatura inválida — data_id=%s x_request_id=%s", data_id, x_request_id)
        return JSONResponse(status_code=403, content={"status": "erro", "detalhe": "Assinatura inválida."})

    # 5. Filtra apenas eventos de pagamento
    event_type = data.get("type", "")
    if event_type != "payment":
        return {"status": "ok", "ignored": event_type}

    if not data_id:
        return {"status": "ok"}

    # 6. Busca e processa em background (MP exige resposta < 5s)
    import asyncio
    payment = await _buscar_pagamento(data_id)
    if payment:
        asyncio.create_task(_processar_pagamento_aprovado(payment))

    return {"status": "ok"}


# ── Criação de preferência (Checkout Pro) ─────────────────────────────────────

class _PreferenciaRequest(BaseModel):
    plano: str
    email: str | None = None  # usado apenas com PREMIUM_TOKEN (admin/teste)
    device_id: str | None = None  # MP_DEVICE_SESSION_ID do security.js (opcional)


@router.post("/pagamentos/criar-preferencia")
async def criar_preferencia(
    request: Request,
    body: _PreferenciaRequest,
    authorization: str | None = Header(default=None),
):
    """
    Cria uma preference no Mercado Pago Checkout Pro e retorna o init_point (URL).
    Requer usuário autenticado via JWT Supabase ou PREMIUM_TOKEN (admin/sandbox).
    """
    import os as _os
    PREMIUM_TOKEN = _os.getenv("PREMIUM_TOKEN", "")
    raw_auth = authorization or ""
    token = raw_auth.removeprefix("Bearer ").strip()

    log.info(
        "criar_preferencia: Authorization header presente=%s token_prefix=%s...",
        bool(raw_auth), token[:20] if token else "(vazio)",
    )

    # Identifica o e-mail do comprador
    if PREMIUM_TOKEN and token == PREMIUM_TOKEN:
        # Admin/teste: e-mail obrigatório no body
        if not body.email:
            raise HTTPException(status_code=400, detail="Campo 'email' obrigatório ao usar PREMIUM_TOKEN.")
        email = body.email
        log.info("criar_preferencia: auth via PREMIUM_TOKEN email=%s", email)
    elif token:
        from app.auth.supabase_client import verify_jwt_token
        payload = verify_jwt_token(token)
        if not payload:
            log.warning("criar_preferencia: verify_jwt_token retornou None para token_prefix=%s...", token[:20])
            raise HTTPException(status_code=403, detail="Token inválido. Faça login novamente.")
        email = payload.get("email", "") or payload.get("sub", "")
        log.info("criar_preferencia: JWT válido email=%s claims=%s", email, list(payload.keys()))
        if not email:
            log.warning("criar_preferencia: JWT sem email/sub — claims: %s", payload)
            raise HTTPException(status_code=403, detail="Token sem e-mail. Faça login novamente.")
    else:
        log.warning("criar_preferencia: sem Authorization header")
        raise HTTPException(status_code=403, detail="Faça login para continuar.")

    # Valida plano
    plano = body.plano.lower().strip()
    if plano not in _PLANOS_PUBLICOS:
        raise HTTPException(
            status_code=400,
            detail=f"Plano inválido. Use: {', '.join(_PLANOS_PUBLICOS)}",
        )

    plano_info = _PLANOS[plano]

    if not MP_ACCESS_TOKEN:
        raise HTTPException(status_code=503, detail="Serviço de pagamento não configurado.")

    preference_payload = {
        "items": [{
            "title":       plano_info["label"],
            "quantity":    1,
            "currency_id": "BRL",
            "unit_price":  plano_info["preco"],
        }],
        "payer": {
            "email": email,
        },
        "additional_info": {
            "items": [{
                "id":          f"plan_{plano}",
                "title":       plano_info["label"],
                "description": f"Acesso ao serviço Palpites da IA — {plano_info['label']}",
                "category_id": "services",
                "quantity":    1,
                "unit_price":  plano_info["preco"],
            }],
            "payer": {
                "email": email,
            },
        },
        "external_reference": f"{email}|{plano}",
        "back_urls": {
            "success": f"{FRONTEND_URL}/pagamento/sucesso",
            "failure": f"{FRONTEND_URL}/pagamento/falha",
            "pending": f"{FRONTEND_URL}/pagamento/pendente",
        },
        "auto_return":        "approved",
        "notification_url":   f"{BACKEND_URL}/api/v1/webhooks/mercadopago",
        "statement_descriptor": "PALPITES DA IA",
    }

    # [TEMP-LOG] diagnóstico device_id — remover após confirmar cadeia front→backend→MP
    device_id_preview = body.device_id[:20] if body.device_id else None
    log.info(
        "criar_preferencia [device_id]: chegou=%s preview=%s email=%s plano=%s",
        bool(body.device_id), device_id_preview, email, plano,
    )

    mp_headers: dict = {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Content-Type":  "application/json",
    }
    if body.device_id:
        mp_headers["X-meli-session-id"] = body.device_id
        log.info("criar_preferencia [device_id]: X-meli-session-id INCLUÍDO no header MP")
    else:
        log.info("criar_preferencia [device_id]: X-meli-session-id AUSENTE — device_id não veio no body")

    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{MP_API}/checkout/preferences",
                headers=mp_headers,
                json=preference_payload,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        log.error("criar_preferencia: MP retornou %s — %s", e.response.status_code, e.response.text[:300])
        raise HTTPException(status_code=502, detail=f"Erro MP ({e.response.status_code}): {e.response.text[:200]}")
    except Exception as e:
        log.error("criar_preferencia: falha ao chamar MP — %s", e)
        raise HTTPException(status_code=503, detail="Serviço de pagamento temporariamente indisponível.")

    log.info("preferencia criada: email=%s plano=%s id=%s", email, plano, data.get("id"))

    return {
        "preference_id":      data.get("id"),
        "init_point":         data.get("init_point"),         # produção
        "sandbox_init_point": data.get("sandbox_init_point"), # sandbox/teste
        "plano":  plano,
        "preco":  plano_info["preco"],
        "label":  plano_info["label"],
    }
