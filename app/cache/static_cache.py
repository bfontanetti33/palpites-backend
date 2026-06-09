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

TTL_OK        = 8  * 3600   # 8h — partida completa (compat legado)
TTL_INSUF     = 4  * 3600   # 4h  — dados_insuficientes, re-tenta 6×/dia
TTL_NARRATIVE = 8  * 3600   # 8h — narrativa Claude (texto muda pouco)

# TTLs diferenciados por tipo de dado
TTL_TEAM_STATS   = 30 * 24 * 3600  # 30 dias — Copa 2022/2018 é imutável
TTL_PLAYER_STATS =  7 * 24 * 3600  # 7 dias  — stats de jogador (temporada encerrada)
TTL_FORMA        = 72 * 3600       # 72h     — forma recente (evento-based + fallback)
TTL_H2H          =  7 * 24 * 3600  # 7 dias  — H2H histórico


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
                raw = json.load(f)
            # Formato canônico: {slug: {...}}
            # Formato legado snapshot: {"entradas": N, "dados": {slug: {...}}}
            # Qualquer outro formato desconhecido → {} com warning, nunca crasha.
            if isinstance(raw, dict) and "dados" in raw and isinstance(raw.get("dados"), dict):
                _store = raw["dados"]
                log.warning("static_cache: formato snapshot detectado — desembrulhando 'dados'")
            elif isinstance(raw, dict):
                _store = raw
            else:
                log.warning("static_cache: formato inválido em %s — descartado", _CACHE_PATH)
                _store = {}
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


def _component_age(slug: str, key: str) -> float:
    """Segundos desde o timestamp de um componente específico, ou inf se ausente."""
    entry = _store.get(slug)
    if not entry:
        return float("inf")
    ts = entry.get(key)
    if not ts:
        return float("inf")
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds()
    except Exception:
        return float("inf")


def is_team_stats_fresh(slug: str) -> bool:
    """Stats históricas do time (Copa cascata) — imutáveis, TTL 30 dias."""
    return _component_age(slug, "team_stats_cached_at") < TTL_TEAM_STATS


def is_player_stats_fresh(slug: str) -> bool:
    """Stats de jogador da temporada — TTL 7 dias (temporada encerrada = imutável)."""
    return _component_age(slug, "player_stats_cached_at") < TTL_PLAYER_STATS


def is_h2h_fresh(slug: str) -> bool:
    """H2H histórico — TTL 7 dias (muda só quando os times se enfrentam)."""
    return _component_age(slug, "h2h_cached_at") < TTL_H2H


def is_forma_fresh(slug: str) -> bool:
    """Forma recente — TTL 72h + invalidação por evento (novo jogo detectado).

    Evento-based: se ultimo_jogo_casa/fora é posterior a forma_cached_at,
    o time jogou um novo jogo desde o último fetch → stale imediatamente.
    Callers externos podem usar invalidate_if_stale() com novas datas de jogo.
    """
    if _component_age(slug, "forma_cached_at") >= TTL_FORMA:
        return False
    entry = _store.get(slug)
    if not entry:
        return False
    forma_ts = entry.get("forma_cached_at")
    if not forma_ts:
        return False
    try:
        forma_dt = datetime.fromisoformat(str(forma_ts).replace("Z", "+00:00"))
        for key in ("ultimo_jogo_casa", "ultimo_jogo_fora"):
            uj = entry.get(key)
            if uj:
                uj_dt = datetime.fromisoformat(str(uj))
                if uj_dt.tzinfo is None:
                    uj_dt = uj_dt.replace(tzinfo=timezone.utc)
                if uj_dt > forma_dt:
                    return False  # time jogou depois do último fetch de forma
    except Exception:
        pass
    return True


def is_fresh(slug: str) -> bool:
    if slug not in _store:
        return False
    entry = _store[slug]
    if not isinstance(entry, dict):
        return False
    age = _age_seconds(entry)
    ttl = TTL_INSUF if entry.get("dados_insuficientes") else TTL_OK
    return age < ttl


def get_partida_raw(slug: str) -> dict | None:
    """Retorna o dict da Partida SEM verificar TTL — para reuso de componentes frescos."""
    entry = _store.get(slug)
    if not entry or not isinstance(entry, dict):
        return None
    return entry.get("partida")


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


def put_partida(
    slug: str,
    partida_dict: dict,
    *,
    update_team_stats: bool = True,
    update_player_stats: bool = True,
    update_forma: bool = True,
    update_h2h: bool = True,
) -> None:
    """Salva Partida no cache disco. partida_dict = partida.model_dump(mode='json').

    Flags update_* controlam quais timestamps de componente são atualizados.
    Componentes não re-buscados preservam seus timestamps antigos (TTL longo continua válido).
    """
    agora = datetime.now(timezone.utc).isoformat()
    existing = _store.get(slug, {})

    def _ultimo_jogo(forma: list[dict]) -> str | None:
        datas = [j.get("data") for j in forma if j.get("data")]
        return max(datas) if datas else None

    _store[slug] = {
        # Campos raiz (compat legado)
        "cached_at":           agora,
        "dados_insuficientes": partida_dict.get("dados_insuficientes", False),
        "ultimo_jogo_casa":    _ultimo_jogo(partida_dict.get("forma_casa") or []),
        "ultimo_jogo_fora":    _ultimo_jogo(partida_dict.get("forma_fora") or []),
        # Dado principal
        "partida":             partida_dict,
        # Sub-caches preservados (recomendacao, stats, narrativa não são tocados aqui)
        "recomendacao":        existing.get("recomendacao"),
        "stats":               existing.get("stats"),
        "narrativa":           existing.get("narrativa"),
        # Timestamps por componente — só atualiza o que foi re-buscado
        "team_stats_cached_at":   agora if update_team_stats   else existing.get("team_stats_cached_at"),
        "player_stats_cached_at": agora if update_player_stats else existing.get("player_stats_cached_at"),
        "forma_cached_at":        agora if update_forma        else existing.get("forma_cached_at"),
        "h2h_cached_at":          agora if update_h2h          else existing.get("h2h_cached_at"),
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


def invalidate_player_stats(slug: str, *, save: bool = True) -> None:
    """Limpa timestamp de player stats para forçar re-fetch na próxima chamada.

    save=False para operações em batch — chame save_to_disk() manualmente depois.
    """
    entry = _store.get(slug)
    if entry:
        entry["player_stats_cached_at"] = None
    if save:
        save_to_disk()


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
