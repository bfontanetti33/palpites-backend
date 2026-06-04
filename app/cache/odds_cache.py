"""
Cache dinâmico de odds — memória (TTL 30min, max 16 jogos).

Só armazena odds para jogos hoje/amanhã (janela de interesse real).
Atualizado pelo cron job a cada 30 minutos.
"""
from cachetools import TTLCache
from datetime import datetime, timezone, timedelta

_odds_cache: TTLCache = TTLCache(maxsize=16, ttl=1800)  # 30min


def get_odds_dinamicas(slug: str) -> dict | None:
    return _odds_cache.get(slug)


def set_odds_dinamicas(slug: str, odds_dict: dict) -> None:
    _odds_cache[slug] = odds_dict


def invalidate(slug: str) -> None:
    _odds_cache.pop(slug, None)


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
