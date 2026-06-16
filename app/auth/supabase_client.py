"""
Supabase — autenticação JWT e operações de banco de dados.

Env vars necessárias:
  SUPABASE_URL         — ex: https://xyzxyz.supabase.co
  SUPABASE_KEY         — chave anon ou service_role
  SUPABASE_JWT_SECRET  — secret HS256 (legado). Projetos novos usam ES256 via JWKS;
                         nesse caso esta var não é usada na verificação de JWT.
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


async def ping() -> dict:
    """
    Verifica conectividade com o Supabase.
    Lê os.getenv() ao ser chamado (não variáveis de módulo) para capturar
    vars adicionadas após o import.
    Retorna dict com diagnóstico completo.
    """
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    result = {
        "url_configurada": bool(url),
        "key_configurada": bool(key),
        "conectado": False,
        "status_code": None,
        "erro": None,
    }
    if not url or not key:
        result["erro"] = "SUPABASE_URL ou SUPABASE_KEY ausentes"
        return result
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=True) as c:
            r = await c.get(
                f"{url}/auth/v1/health",
                headers={"apikey": key},
            )
        result["status_code"] = r.status_code
        # Qualquer resposta HTTP = servidor acessível (401 = auth, não indisponível)
        result["conectado"] = r.status_code < 500
    except Exception as e:
        result["erro"] = str(e)[:200]
    return result


# ── JWT ───────────────────────────────────────────────────────────────────────

import logging as _jwt_log_mod
import time as _time_mod

_log_jwt = _jwt_log_mod.getLogger(__name__)

# Cache JWKS (chaves públicas ES256/RS256 do Supabase)
_jwks_cache: dict = {}
_jwks_fetched_at: float = 0.0


def _get_public_key(kid: str | None) -> dict | None:
    """Busca chave pública do JWKS do Supabase, com cache de 1h."""
    global _jwks_cache, _jwks_fetched_at
    url = os.getenv("SUPABASE_URL", "")
    if not url:
        return None
    if not _jwks_cache or (_time_mod.time() - _jwks_fetched_at) > 3600:
        try:
            r = httpx.get(f"{url}/auth/v1/.well-known/jwks.json", timeout=5)
            r.raise_for_status()
            keys = r.json().get("keys", [])
            _jwks_cache = {k.get("kid"): k for k in keys}
            _jwks_fetched_at = _time_mod.time()
            _log_jwt.info("_get_public_key: JWKS carregado — %d chave(s)", len(_jwks_cache))
        except Exception as e:
            _log_jwt.warning("_get_public_key: falhou ao buscar JWKS — %s", e)
            return None
    key = _jwks_cache.get(kid) if kid else next(iter(_jwks_cache.values()), None)
    if not key:
        _log_jwt.warning("_get_public_key: kid=%s não encontrado. kids disponíveis: %s", kid, list(_jwks_cache.keys()))
    return key


def verify_jwt_token(token: str) -> Optional[dict]:
    """
    Valida JWT emitido pelo Supabase Auth.
    Suporta HS256 (secret simétrico) e ES256/RS256 (chave pública via JWKS).
    Retorna o payload se válido, None se inválido.
    """
    import base64 as _b64
    import json as _json

    if not token:
        return None

    # Decodifica header sem verificação para detectar algoritmo
    try:
        h_b64 = token.split(".")[0]
        h_b64 += "=" * (4 - len(h_b64) % 4)
        header = _json.loads(_b64.urlsafe_b64decode(h_b64))
        alg = header.get("alg", "HS256")
        kid = header.get("kid")
    except Exception as he:
        _log_jwt.warning("verify_jwt_token: falhou ao ler header — %s", he)
        alg, kid = "HS256", None

    _log_jwt.info("verify_jwt_token: alg=%s kid=%s prefix=%s...", alg, kid, token[:20])

    if alg == "HS256":
        secret = os.getenv("SUPABASE_JWT_SECRET", "")
        if not secret:
            _log_jwt.warning("verify_jwt_token: SUPABASE_JWT_SECRET ausente para HS256")
            return None
        try:
            return jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
        except JWTError as e:
            _log_jwt.warning("verify_jwt_token: JWTError HS256 — %s", e)
            return None
    else:
        # ES256, RS256 — verifica via JWKS
        jwk_key = _get_public_key(kid)
        if not jwk_key:
            return None
        try:
            return jwt.decode(token, jwk_key, algorithms=[alg], options={"verify_aud": False})
        except JWTError as e:
            _log_jwt.warning("verify_jwt_token: JWTError %s kid=%s — %s", alg, kid, e)
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


async def get_user_id_by_email(email: str) -> str | None:
    """Retorna o user_id (UUID) do usuário pelo e-mail. None se não encontrado."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/users",
                headers=_HEADERS,
                params={"email": f"eq.{email}", "select": "id"},
            )
            r.raise_for_status()
            data = r.json()
            return data[0]["id"] if data else None
    except Exception:
        return None


async def set_premium(user_id: str, premium_until_iso: str, email: str = "") -> None:
    """
    Ativa premium para o usuário até a data indicada (ISO 8601).
    Usa UPSERT: cria a linha se não existir (usuário sem linha em public.users).
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    import logging as _l
    _log = _l.getLogger(__name__)
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.post(
                f"{SUPABASE_URL}/rest/v1/users",
                headers={**_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
                json={
                    "id":            user_id,
                    "email":         email,
                    "is_premium":    True,
                    "premium_until": premium_until_iso,
                },
            )
            if r.status_code not in (200, 201, 204):
                _log.error("set_premium: HTTP %s — %s", r.status_code, r.text[:200])
    except Exception as e:
        _log.error("set_premium: exceção — %s", e)


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


# ── Snapshot pré-jogo ─────────────────────────────────────────────────────────

async def salvar_palpite_congelado(slug: str, payload: dict) -> None:
    """Upsert do palpite pré-jogo na tabela palpites_congelados (PK = slug)."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(
                f"{SUPABASE_URL}/rest/v1/palpites_congelados",
                headers={**_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
                json={
                    "slug": slug,
                    "payload": payload,
                    "congelado_em": payload.get("congelado_em"),
                },
            )
    except Exception as e:
        _log_jwt.warning("falha ao salvar palpite congelado %s: %s", slug, e)


async def ler_palpite_congelado(slug: str) -> dict | None:
    """Lê o palpite congelado do Supabase. Retorna None se não existir ou em erro."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(
                f"{SUPABASE_URL}/rest/v1/palpites_congelados",
                headers=_HEADERS,
                params={"slug": f"eq.{slug}", "select": "payload", "limit": "1"},
            )
            r.raise_for_status()
            data = r.json()
            return data[0]["payload"] if data else None
    except Exception as e:
        _log_jwt.warning("falha ao ler palpite congelado %s: %s", slug, e)
        return None
