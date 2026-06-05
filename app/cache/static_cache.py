"""
Cache estático de partidas — disco (seeds/cache_partidas.json).

Sobrevive redeploys sem re-consumir quota API-Football.
TTL: 8h (dados completos) | 24h (dados_insuficientes, re-tenta após 24h com quota nova)
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_CACHE_PATH = Path(__file__).parent.parent.parent / "seeds" / "cache_partidas.json"
_store: dict[str, dict] = {}

TTL_OK    = 8  * 3600   # 8h
TTL_INSUF = 24 * 3600   # 24h — tenta re-fetch após 24h quando dados_insuficientes


def load_from_disk() -> int:
    """Carrega cache do disco na inicialização. Retorna número de entradas carregadas."""
    global _store
    try:
        if _CACHE_PATH.exists():
            with open(_CACHE_PATH, encoding="utf-8") as f:
                _store = json.load(f)
            log.info("static_cache: %d entradas carregadas de %s", len(_store), _CACHE_PATH)
            return len(_store)
    except Exception as e:
        log.warning("static_cache: falha ao carregar disco: %s", e)
        _store = {}
    return 0


def save_to_disk() -> bool:
    """Persiste o cache em disco. Retorna True se sucesso."""
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_store, f, ensure_ascii=False, default=str)
        return True
    except Exception as e:
        log.warning("static_cache: falha ao salvar disco: %s", e)
        return False


def _age_seconds(entry: dict) -> float:
    try:
        cached_at = datetime.fromisoformat(entry["cached_at"].replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - cached_at).total_seconds()
    except Exception:
        return float("inf")


def is_fresh(slug: str) -> bool:
    if slug not in _store:
        return False
    entry = _store[slug]
    age = _age_seconds(entry)
    ttl = TTL_INSUF if entry.get("dados_insuficientes") else TTL_OK
    return age < ttl


def get_partida(slug: str) -> dict | None:
    """Retorna dict da Partida se estiver frescos no cache, senão None."""
    if not is_fresh(slug):
        return None
    return _store[slug].get("partida")


def get_recomendacao(slug: str) -> dict | None:
    """Retorna dict da RecomendacaoIA se existir e for recente (TTL_OK), senão None."""
    entry = _store.get(slug)
    if not entry:
        return None
    rec = entry.get("recomendacao")
    if not rec:
        return None
    try:
        rec_at = datetime.fromisoformat(rec["cached_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - rec_at).total_seconds()
        if age >= TTL_OK:
            return None
    except Exception:
        return None
    return rec.get("dados")


def put_partida(slug: str, partida_dict: dict) -> None:
    """Salva Partida no cache disco. partida_dict = partida.model_dump(mode='json')."""
    agora = datetime.now(timezone.utc).isoformat()

    def _ultimo_jogo(forma: list[dict]) -> str | None:
        datas = [j.get("data") for j in forma if j.get("data")]
        return max(datas) if datas else None

    _store[slug] = {
        "cached_at": agora,
        "dados_insuficientes": partida_dict.get("dados_insuficientes", False),
        "ultimo_jogo_casa": _ultimo_jogo(partida_dict.get("forma_casa") or []),
        "ultimo_jogo_fora": _ultimo_jogo(partida_dict.get("forma_fora") or []),
        "partida": partida_dict,
        "recomendacao": _store.get(slug, {}).get("recomendacao"),  # preserva rec existente
    }
    save_to_disk()


def put_recomendacao(slug: str, rec_dict: dict) -> None:
    """Salva RecomendacaoIA no cache disco. rec_dict = rec.model_dump(mode='json')."""
    agora = datetime.now(timezone.utc).isoformat()
    if slug not in _store:
        _store[slug] = {
            "cached_at": agora,
            "dados_insuficientes": False,
            "ultimo_jogo_casa": None,
            "ultimo_jogo_fora": None,
            "partida": None,
            "recomendacao": None,
        }
    _store[slug]["recomendacao"] = {"cached_at": agora, "dados": rec_dict}
    save_to_disk()


def invalidate(slug: str) -> bool:
    """Remove slug do cache. Retorna True se existia."""
    if slug in _store:
        del _store[slug]
        save_to_disk()
        return True
    return False


def invalidate_if_stale(slug: str, nova_data_casa: str | None, nova_data_fora: str | None) -> bool:
    """Invalida se um time jogou novo jogo após o cached_at. Retorna True se invalidado."""
    if slug not in _store:
        return False
    try:
        cached_at = datetime.fromisoformat(_store[slug]["cached_at"].replace("Z", "+00:00"))
    except Exception:
        invalidate(slug)
        return True

    def _newer(dt_str: str | None) -> bool:
        if not dt_str:
            return False
        try:
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt > cached_at
        except Exception:
            return False

    if _newer(nova_data_casa) or _newer(nova_data_fora):
        del _store[slug]
        save_to_disk()
        return True
    return False


def summary() -> dict:
    total  = len(_store)
    frescos = sum(1 for s in _store if is_fresh(s))
    com_rec = sum(1 for s in _store if _store[s].get("recomendacao"))
    insuf   = sum(1 for s in _store if _store[s].get("dados_insuficientes"))
    return {
        "total": total,
        "frescos": frescos,
        "stale": total - frescos,
        "com_recomendacao": com_rec,
        "dados_insuficientes": insuf,
        "arquivo": str(_CACHE_PATH),
    }
