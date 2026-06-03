from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded


def _get_client_ip(request: Request) -> str:
    # Railway usa proxy — IP real está em X-Forwarded-For
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return (request.client.host if request.client else None) or "unknown"


# Limite global de 200 req/min por IP (proteção de base para todos os endpoints)
limiter = Limiter(key_func=_get_client_ip, default_limits=["200/minute"])


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """429 em PT-BR com cabeçalho Retry-After."""
    retry = getattr(exc, "retry_after", 60)
    return JSONResponse(
        status_code=429,
        content={"detail": "Muitas requisições. Aguarde alguns segundos e tente novamente."},
        headers={"Retry-After": str(retry)},
    )
