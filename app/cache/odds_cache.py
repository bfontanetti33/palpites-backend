"""
Cache dinâmico de odds — memória (TTL 25h, max 16 jogos).

Só armazena odds para jogos hoje/amanhã (janela de interesse real).
Intervalo de atualização via cron é tiered por proximidade do jogo:
  > 12h → 1×/dia | 2h–12h → 1×/hora | < 2h → a cada 30min
"""
from cachetools import TTLCache
from datetime import datetime, timezone, timedelta

_odds_cache: TTLCache = TTLCache(maxsize=80, ttl=90000)  # 25h — cron controla frequência
_last_updated: dict[str, datetime] = {}  # rastreia quando cada slug foi buscado na API


def get_odds_dinamicas(slug: str) -> dict | None:
    return _odds_cache.get(slug)


def set_odds_dinamicas(slug: str, odds_dict: dict) -> None:
    _odds_cache[slug] = odds_dict
    _last_updated[slug] = datetime.now(timezone.utc)


def get_last_updated(slug: str) -> datetime | None:
    return _last_updated.get(slug)


def invalidate(slug: str) -> None:
    _odds_cache.pop(slug, None)
    _last_updated.pop(slug, None)


def get_today_tomorrow_slugs() -> list[str]:
    """Retorna slugs dos jogos que ocorrem hoje ou amanhã (para atualização de odds)."""
    from app.agents.football_agent import _JOGOS
    agora = datetime.now(timezone.utc)
    hoje_inicio = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    amanha_fim  = hoje_inicio + timedelta(days=2)

    slugs = []
    for j in _JOGOS:
        try:
            dt_str = j.get("data_hora_utc") or j.get("data_hora_brasilia", "")
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if hoje_inicio <= dt < amanha_fim:
                slugs.append(j["slug"])
        except Exception:
            pass
    return slugs
