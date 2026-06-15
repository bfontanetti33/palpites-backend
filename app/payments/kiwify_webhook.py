"""
Kiwify — webhook de notificações (ESQUELETO fase de descoberta).

TEMPORÁRIO: loga payload bruto para mapear estrutura real.
Remover log.warning após etapa 2 (mapeamento produto→plano).

URL a cadastrar no painel Kiwify:
  https://palpites-backend-production.up.railway.app/api/v1/webhooks/kiwify
"""
import json
import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhooks/kiwify")
async def kiwify_webhook(
    request: Request,
    token: str | None = Query(default=None),
):
    try:
        body_bytes = await request.body()
        try:
            body = json.loads(body_bytes)
        except Exception:
            body = body_bytes.decode("utf-8", errors="replace")

        token_body = body.get("token") if isinstance(body, dict) else None

        log.warning(
            "KIWIFY WEBHOOK PAYLOAD: token_query=%s token_body=%s body=%s",
            token,
            token_body,
            json.dumps(body, ensure_ascii=False) if isinstance(body, dict) else body,
        )
    except Exception as exc:
        log.warning("KIWIFY WEBHOOK erro ao logar payload: %s", exc)

    return JSONResponse(status_code=200, content={"status": "ok"})
