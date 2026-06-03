"""
Supabase — autenticação JWT e operações de banco de dados.

Env vars necessárias:
  SUPABASE_URL         — ex: https://xyzxyz.supabase.co
  SUPABASE_KEY         — chave anon ou service_role
  SUPABASE_JWT_SECRET  — secret do JWT (Settings → API → JWT Settings)
"""
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from jose import JWTError, jwt

SUPABASE_URL        = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY        = os.getenv("SUPABASE_KEY", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    import logging
    logging.getLogger(__name__).warning(
        "Supabase não configurado — auth desativado. "
        "Defina SUPABASE_URL e SUPABASE_KEY nas variáveis de ambiente."
    )

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=minimal",
}


async def ping() -> bool:
    """Verifica conectividade com o Supabase. Usado pelo health-check."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/",
                headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
            )
            return r.status_code in (200, 404)  # 404 = conectado, sem tabela na raiz
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────────────────────

def verify_jwt_token(token: str) -> Optional[dict]:
    """
    Valida JWT emitido pelo Supabase Auth.
    Retorna o payload (dict com 'sub', 'email', etc.) se válido, None se inválido.
    """
    if not SUPABASE_JWT_SECRET or not token:
        return None
    try:
        return jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    except JWTError:
        return None


# ── Consultas Supabase (PostgREST) ────────────────────────────────────────────

async def get_user_premium_status(user_id: str) -> dict:
    """
    Retorna status do usuário:
      {"is_premium": bool, "premium_until": str|None, "avulso_credits": int}
    Em caso de erro retorna defaults falsos (fail-closed).
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return {"is_premium": False, "premium_until": None, "avulso_credits": 0}
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=_HEADERS,
                params={
                    "id": f"eq.{user_id}",
                    "select": "is_premium,premium_until,avulso_credits",
                },
            )
            r.raise_for_status()
            data = r.json()
    except Exception:
        return {"is_premium": False, "premium_until": None, "avulso_credits": 0}

    if not data:
        return {"is_premium": False, "premium_until": None, "avulso_credits": 0}

    user = data[0]
    is_premium = bool(user.get("is_premium", False))
    premium_until = user.get("premium_until")

    # Verifica validade temporal do premium
    if is_premium and premium_until:
        try:
            until_dt = datetime.fromisoformat(premium_until.replace("Z", "+00:00"))
            if until_dt < datetime.now(timezone.utc):
                is_premium = False
        except ValueError:
            pass

    return {
        "is_premium": is_premium,
        "premium_until": premium_until,
        "avulso_credits": int(user.get("avulso_credits", 0)),
    }


async def register_usage(user_id: str, slug: str) -> None:
    """Registra uso de análise na tabela usage_log (best-effort, silencia erros)."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(
                f"{SUPABASE_URL}/rest/v1/usage_log",
                headers=_HEADERS,
                json={"user_id": user_id, "slug": slug},
            )
    except Exception:
        pass


async def deduct_avulso_credit(user_id: str) -> bool:
    """
    Debita 1 crédito avulso. Usa leitura+escrita atômica via RPC do Supabase.
    Retorna True se debitou com sucesso, False se sem créditos ou erro.
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            # Lê créditos atuais
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=_HEADERS,
                params={"id": f"eq.{user_id}", "select": "avulso_credits"},
            )
            r.raise_for_status()
            data = r.json()
            if not data:
                return False
            credits = int(data[0].get("avulso_credits", 0))
            if credits <= 0:
                return False
            # Decrementa
            await c.patch(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=_HEADERS,
                params={"id": f"eq.{user_id}"},
                json={"avulso_credits": credits - 1},
            )
            return True
    except Exception:
        return False


async def set_premium(user_id: str, premium_until_iso: str) -> None:
    """Ativa premium para o usuário até a data indicada (ISO 8601)."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.patch(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=_HEADERS,
                params={"id": f"eq.{user_id}"},
                json={"is_premium": True, "premium_until": premium_until_iso},
            )
    except Exception:
        pass


async def add_avulso_credit(email: str) -> None:
    """Adiciona 1 crédito avulso ao usuário identificado pelo e-mail."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=_HEADERS,
                params={"email": f"eq.{email}", "select": "id,avulso_credits"},
            )
            r.raise_for_status()
            data = r.json()
            if not data:
                return
            user = data[0]
            await c.patch(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=_HEADERS,
                params={"id": f"eq.{user['id']}"},
                json={"avulso_credits": int(user.get("avulso_credits", 0)) + 1},
            )
    except Exception:
        pass
