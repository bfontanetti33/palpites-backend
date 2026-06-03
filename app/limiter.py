from fastapi import Request
from slowapi import Limiter


def _get_client_ip(request: Request) -> str:
    # Railway (e a maioria dos proxies) envia o IP real em X-Forwarded-For.
    # Pega sempre o primeiro item (IP original do cliente).
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    return (request.client.host if request.client else None) or "unknown"


limiter = Limiter(key_func=_get_client_ip)
