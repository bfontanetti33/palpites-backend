from dotenv import load_dotenv
load_dotenv()

import asyncio
import os
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.limiter import limiter, rate_limit_handler
from app.routes.partidas import router as partidas_router
from app.routes.admin import router as admin_router
from app.payments.mercadopago_webhook import router as mp_router

# ── Sentry (só inicializa se DSN configurado) ─────────────────────────────────
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    import sentry_sdk
    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        traces_sample_rate=0.1,
        environment="production",
    )

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Palpites da IA — Copa do Mundo 2026",
    description=(
        "API focada na Copa do Mundo FIFA 2026. "
        "Stats históricas reais de cada seleção, H2H, forma recente e "
        "probabilidades calculadas por modelo de Poisson. "
        "Nunca inventa dados — dados_insuficientes=true quando a API não retorna."
    ),
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
app.add_middleware(SlowAPIMiddleware)


# ── Middleware: rastreia erros 500 + contagem de requests ─────────────────────

class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        from app.monitoring.telegram_bot import state, alertar_erro_500
        state.requests_timestamps.append(datetime.utcnow())
        try:
            response = await call_next(request)
            if response.status_code >= 500:
                asyncio.create_task(
                    alertar_erro_500(request.url.path, f"HTTP {response.status_code}")
                )
            return response
        except Exception as exc:
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
    allow_origin_regex=(
        r"https://.*\.lovable\.app|"
        r"https://.*\.lovableproject\.com|"
        r"https://palpitesdaia\.com\.br|"
        r"https://www\.palpitesdaia\.com\.br"
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(partidas_router, prefix="/api/v1", tags=["Partidas"])
app.include_router(admin_router,    prefix="/api/v1", tags=["Admin"])
app.include_router(mp_router,       prefix="/api/v1", tags=["Pagamentos"])


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    import logging
    from app.monitoring.telegram_bot import loop_resumo_diario, send_telegram, state
    from app.agents.football_agent import precalcular_proximos_jogos, _partida_cache
    from app.cache import static_cache
    from app.monitoring.cron_jobs import iniciar_cron_jobs
    from app.models.schemas import Partida

    log = logging.getLogger(__name__)
    state.startup_time = datetime.utcnow()

    # Carrega cache disco → popula _partida_cache sem nenhuma chamada API
    n_disk = static_cache.load_from_disk()
    n_ok = 0
    for slug in list(static_cache._store.keys()):
        partida_dict = static_cache.get_partida(slug)
        if partida_dict:
            try:
                _partida_cache[slug] = Partida.model_validate(partida_dict)
                n_ok += 1
            except Exception as e:
                log.warning("startup: falha ao deserializar %s do disco: %s", slug, e)

    asyncio.create_task(loop_resumo_diario())
    asyncio.create_task(iniciar_cron_jobs())
    # Pré-cache API para jogos ainda não cobertos pelo cache disco.
    # Scripts de árbitros e squads são manuais (não rodam aqui).
    asyncio.create_task(precalcular_proximos_jogos(n=8))

    asyncio.create_task(send_telegram(
        "✅ <b>Deploy OK — Palpites da IA</b>\n"
        f"Cache disco: {n_ok}/{n_disk} partidas restauradas (0 chamadas API)\n"
        f"⏰ {datetime.utcnow().strftime('%d/%m %H:%M')} UTC"
    ))


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Sistema"])
def health():
    from app.agents.football_agent import _partida_cache
    return {
        "status": "ok",
        "service": "palpites-da-ia",
        "versao": "1.0.0",
        "regiao": "southamerica-east1",
        "jogos_em_cache": len(_partida_cache),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
