from dotenv import load_dotenv
load_dotenv()  # antes de qualquer import que leia os.getenv() no nível de módulo

import asyncio
import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from app.limiter import limiter
from app.routes.partidas import router as partidas_router
from app.routes.admin import router as admin_router

app = FastAPI(
    title="Palpites da IA — Copa do Mundo 2026",
    description=(
        "API focada na Copa do Mundo FIFA 2026. "
        "Stats históricas reais de cada seleção, H2H, forma recente e "
        "probabilidades calculadas por modelo de Poisson. "
        "Nunca inventa dados — dados_insuficientes=true quando a API não retorna."
    ),
    version="2.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


# ── Middleware: rastreia erros 500 e envia alerta Telegram ────────────────────

class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            if response.status_code >= 500:
                from app.monitoring.telegram_bot import alertar_erro_500
                asyncio.create_task(
                    alertar_erro_500(request.url.path, f"HTTP {response.status_code}")
                )
            return response
        except Exception as exc:
            from app.monitoring.telegram_bot import alertar_erro_500
            asyncio.create_task(
                alertar_erro_500(request.url.path, f"{type(exc).__name__}: {exc}"[:300])
            )
            return JSONResponse(status_code=500, content={"detail": str(exc)})


app.add_middleware(ErrorTrackingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"https://.*\.lovable\.app|https://.*\.lovableproject\.com",
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(partidas_router, prefix="/api/v1", tags=["Partidas"])
app.include_router(admin_router,    prefix="/api/v1", tags=["Admin"])


# ── Startup: inicia loop de resumo diário Telegram ───────────────────────────

@app.on_event("startup")
async def startup():
    from app.monitoring.telegram_bot import loop_resumo_diario
    asyncio.create_task(loop_resumo_diario())


@app.get("/health")
def health():
    return {"status": "ok", "service": "palpites-da-ia"}
