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

TTL_OK        = 8  * 3600   # 8h — partida completa
TTL_INSUF     = 4  * 3600   # 4h  — dados_insuficientes, re-tenta 6×/dia
TTL_NARRATIVE = 8  * 3600   # 8h — narrativa Claude (texto muda pouco)


def _stats_ttl(horario_utc: str | None) -> float:
    """TTL para stats baseado na proximidade do jogo — espelha cron de odds."""
    try:
        dt = datetime.fromisoformat((horario_utc or "").replace("Z", "+00:00"))
        horas = (dt - datetime.now(timezone.utc)).total_seconds() / 3600
        if horas > 12:
            return 24 * 3600   # > 12h: 1×/dia
        if horas > 2:
            return 3600         # 2-12h: 1×/hora
        return 30 * 60          # < 2h: 30min
    except Exception:
        return TTL_OK           # fallback seguro: 8h


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


def get_recomendacao_estado(slug: str) -> tuple[bool, bool, dict | None]:
    """
    Retorna (stats_fresh, narrative_fresh, dados).
    stats_fresh  : stats dentro do TTL tiered por proximidade do jogo.
    narrative_fresh: narrativa Claude dentro de TTL_NARRATIVE (8h).
    dados        : dict do RecomendacaoIA ou None se não existir.
    Entradas no formato antigo (sem stats_cached_at) → ambas stale.
    """
    entry = _store.get(slug)
    if not entry:
        return False, False, None
    rec = entry.get("recomendacao")
    if not rec:
        return False, False, None
    dados = rec.get("dados")
    if not dados:
        return False, False, None

    agora = datetime.now(timezone.utc)

    # Frescor da narrativa (TTL fixo 8h)
    narrative_fresh = False
    try:
        nat = rec.get("narrative_cached_at") or rec.get("cached_at", "")
        nat_dt = datetime.fromisoformat(nat.replace("Z", "+00:00"))
        narrative_fresh = (agora - nat_dt).total_seconds() < TTL_NARRATIVE
    except Exception:
        pass

    # Frescor das stats (TTL tiered por hora do jogo)
    stats_fresh = False
    try:
        sat = rec.get("stats_cached_at")
        if not sat:
            # Formato antigo — trata como stale para forçar recálculo
            return False, narrative_fresh, dados
        sat_dt = datetime.fromisoformat(sat.replace("Z", "+00:00"))
        horario = dados.get("horario_utc") or (entry.get("partida") or {}).get("horario")
        ttl = _stats_ttl(horario)
        stats_fresh = (agora - sat_dt).total_seconds() < ttl
    except Exception:
        pass

    return stats_fresh, narrative_fresh, dados


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


def put_recomendacao(slug: str, rec_dict: dict, update_narrative: bool = True) -> None:
    """
    Salva RecomendacaoIA no cache disco.
    update_narrative=False: atualiza só stats_cached_at (narrativa Claude reutilizada).
    """
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
    existing = _store[slug].get("recomendacao") or {}
    narrative_cached_at = agora if update_narrative else (
        existing.get("narrative_cached_at") or existing.get("cached_at", agora)
    )
    _store[slug]["recomendacao"] = {
        "cached_at":           agora,           # compat legado
        "stats_cached_at":     agora,
        "narrative_cached_at": narrative_cached_at,
        "dados":               rec_dict,
    }
    save_to_disk()


def put_stats(slug: str, stats_dict: dict) -> None:
    """Salva StatsRecomendacao no cache (chave 'stats'). TTL tiered por proximidade do jogo."""
    agora = datetime.now(timezone.utc).isoformat()
    if slug not in _store:
        _store[slug] = {
            "cached_at": agora, "dados_insuficientes": False,
            "ultimo_jogo_casa": None, "ultimo_jogo_fora": None, "partida": None,
        }
    _store[slug]["stats"] = {"cached_at": agora, "dados": stats_dict}
    save_to_disk()


def get_stats(slug: str) -> dict | None:
    """Retorna StatsRecomendacao se dentro do TTL tiered, senão None."""
    entry = _store.get(slug)
    if not entry:
        return None
    stats_entry = entry.get("stats")
    if not stats_entry:
        return None
    try:
        agora = datetime.now(timezone.utc)
        cached_dt = datetime.fromisoformat(stats_entry["cached_at"].replace("Z", "+00:00"))
        horario = (stats_entry.get("dados") or {}).get("horario_utc", "")
        ttl = _stats_ttl(horario)
        if (agora - cached_dt).total_seconds() < ttl:
            return stats_entry.get("dados")
    except Exception:
        pass
    return None


def put_narrativa(slug: str, narrativa_dict: dict) -> None:
    """Salva NarrativaData no cache (chave 'narrativa'). TTL fixo 8h."""
    agora = datetime.now(timezone.utc).isoformat()
    if slug not in _store:
        _store[slug] = {
            "cached_at": agora, "dados_insuficientes": False,
            "ultimo_jogo_casa": None, "ultimo_jogo_fora": None, "partida": None,
        }
    _store[slug]["narrativa"] = {"cached_at": agora, "dados": narrativa_dict}
    save_to_disk()


def get_narrativa(slug: str) -> dict | None:
    """Retorna NarrativaData se dentro de TTL_NARRATIVE e texto real, senão None."""
    entry = _store.get(slug)
    if not entry:
        return None
    narr_entry = entry.get("narrativa")
    if not narr_entry:
        return None
    try:
        agora = datetime.now(timezone.utc)
        nat_dt = datetime.fromisoformat(narr_entry["cached_at"].replace("Z", "+00:00"))
        if (agora - nat_dt).total_seconds() >= TTL_NARRATIVE:
            return None
        dados = narr_entry.get("dados") or {}
        if (dados.get("texto_completo")
                and dados.get("narrativa")
                and "se enfrentam na Copa do Mundo 2026" not in dados.get("narrativa", "")):
            return dados
    except Exception:
        pass
    return None


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
    total    = len(_store)
    frescos  = sum(1 for s in _store if is_fresh(s))
    com_rec  = sum(1 for s in _store if _store[s].get("recomendacao") or _store[s].get("stats"))
    com_narr = sum(1 for s in _store if _store[s].get("narrativa"))
    insuf    = sum(1 for s in _store if _store[s].get("dados_insuficientes"))
    return {
        "total": total,
        "frescos": frescos,
        "stale": total - frescos,
        "com_stats": com_rec,
        "com_narrativa": com_narr,
        "dados_insuficientes": insuf,
        "arquivo": str(_CACHE_PATH),
    }
