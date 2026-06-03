#!/usr/bin/env python3
"""
Validação completa — Palpites da IA / Copa do Mundo 2026
Roda standalone (sem servidor). Gera relatório em texto e JSON.

Uso:
    python scripts/validacao_completa.py

Usa ~20-30 requests da API-Football e ~3 da Odds API.
"""
import asyncio
import json
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Força UTF-8 no terminal Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import httpx

from app.agents.football_agent import buscar_detalhe_partida
from app.agents.ia_agent import (
    _dc_matrix, _market_probs, _tau, _fat_tail_matrix, _probs_do_matrix,
    _calcular_contexto, _uncertainty_index, _fragility_score,
    _achatar_probabilidades, _ELO_FALLBACK, _CONFEDERACAO, _STATS_REGIONAIS,
    DC_RHO,
)
from app.agents.players_agent import calcular_p90, _lss_da_liga
from app.models.schemas import (
    Partida, RatingDinamico, ModeloGols, EstatisticasTemporada, EntradaForma,
)

try:
    from app.agents.odds_engine import shin_probabilities, calcular_z_score
    ODDS_ENGINE_OK = True
except ImportError:
    ODDS_ENGINE_OK = False

API_FB_KEY   = os.getenv("API_FOOTBALL_KEY", "")
API_ODDS_KEY = os.getenv("ODDS_API_KEY", "")
FB_BASE      = "https://v3.football.api-sports.io"
FB_HDR       = {"x-apisports-key": API_FB_KEY}

# ── Contadores globais ────────────────────────────────────────────────────────
_criticos: list[str] = []
_warnings: list[str] = []


def _ok(msg: str):       print(f"    ✅ {msg}")
def _warn(msg: str):     _warnings.append(msg); print(f"    ⚠️  {msg}")
def _err(msg: str):      _criticos.append(msg); print(f"    ❌ {msg}")

def _chk(cond: bool, ok_msg: str, fail_msg: str, critico: bool = False) -> bool:
    if cond:
        _ok(ok_msg)
    elif critico:
        _err(fail_msg)
    else:
        _warn(fail_msg)
    return cond


# ── Implementações inline (para quando odds_engine.py não existe ainda) ───────
def _shin_inline(odds_list: list[float]) -> list[float]:
    """Shin (1993) iterativo — remove margem da casa."""
    K = sum(1.0 / o for o in odds_list)

    def compute(z: float) -> list[float]:
        out = []
        for o in odds_list:
            qi = 1.0 / o
            try:
                num = math.sqrt(z * z + 4 * (1 - z) * (qi / K) ** 2) - z
                den = 2 * (1 - z)
                out.append(num / den if den > 1e-10 else qi / K)
            except (ValueError, ZeroDivisionError):
                out.append(qi / K)
        return out

    lo, hi = 0.0, 1.0 - 1e-9
    for _ in range(100):
        z = (lo + hi) / 2
        probs = compute(z)
        s = sum(probs)
        if abs(s - 1.0) < 1e-7:
            break
        if s > 1.0:
            lo = z
        else:
            hi = z

    probs = compute((lo + hi) / 2)
    total = sum(probs) or 1.0
    return [p / total for p in probs]


def _zscore_inline(prob_modelo: float, prob_consenso: float, n_casas: int) -> float:
    se = math.sqrt(prob_consenso * (1 - prob_consenso) / n_casas)
    return (prob_modelo - prob_consenso) / se if se > 1e-10 else 0.0


# Se odds_engine existe, usa as funções reais; caso contrário, usa inline
_shin_fn   = shin_probabilities if ODDS_ENGINE_OK else _shin_inline
_zscore_fn = calcular_z_score   if ODDS_ENGINE_OK else _zscore_inline


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO 1 — SEED
# ═══════════════════════════════════════════════════════════════════════════════

def validar_seed() -> dict:
    print("\n📋 BLOCO 1 — VALIDAÇÃO DO SEED")
    problemas: list[str] = []
    stats: dict = {}

    seed_path = ROOT / "seeds" / "copa_2026.json"
    if not seed_path.exists():
        _err("seeds/copa_2026.json não encontrado")
        return {"status": "error", "problemas": ["arquivo não encontrado"], "stats": {}}

    seed  = json.loads(seed_path.read_text(encoding="utf-8"))
    jogos = seed.get("jogos", [])
    times = seed.get("times", {})

    # 1. Total de jogos
    total = len(jogos)
    stats["total_jogos"] = total
    _chk(total == 72, f"72 jogos encontrados", f"Esperado 72, encontrado {total}", critico=True)
    if total != 72:
        problemas.append(f"total_jogos={total} (esperado 72)")

    # 2. Campos obrigatórios (IDs, slugs, times)
    campos_criticos = ["api_fixture_id", "slug", "rodada", "data_hora_brasilia",
                       "time_casa", "time_casa_id", "time_fora", "time_fora_id"]
    campos_opcionais = ["estadio", "cidade", "time_casa_logo", "time_fora_logo"]

    incompletos_crit = []
    for j in jogos:
        faltando = [c for c in campos_criticos if not j.get(c) and j.get(c) != 0]
        if faltando:
            incompletos_crit.append(f"{j.get('slug','?')}: {faltando}")
    _chk(not incompletos_crit, "Campos críticos presentes (id/slug/times)",
         f"{len(incompletos_crit)} jogos sem campos críticos: {incompletos_crit[:2]}")
    problemas.extend(incompletos_crit[:5])

    # Campos opcionais — apenas warning
    sem_opt: dict = {c: 0 for c in campos_opcionais}
    for j in jogos:
        for c in campos_opcionais:
            if not (j.get(c) or ""):
                sem_opt[c] += 1
    for c, n in sem_opt.items():
        if n > 0:
            _warn(f"{n} jogos sem '{c}' (campo opcional — pode ser enriquecido no seed)")

    # 3. Slugs únicos
    slugs = [j.get("slug", "") for j in jogos]
    dups  = [s for s in set(slugs) if slugs.count(s) > 1 and s]
    _chk(not dups, "Slugs únicos", f"Slugs duplicados: {dups}")
    if dups:
        problemas.append(f"slugs duplicados: {dups}")

    # 4. Formato de horário ISO com timezone
    re_iso = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[-+]\d{2}:\d{2}$")
    h_inv  = [j["slug"] for j in jogos if not re_iso.match(j.get("data_hora_brasilia", ""))]
    _chk(not h_inv, "Horários em formato ISO com timezone",
         f"{len(h_inv)} horários com formato inválido: {h_inv[:3]}")

    # 5. Horários a partir de 11/06/2026
    copa_inicio = datetime(2026, 6, 11)
    h_fora = []
    for j in jogos:
        try:
            dt = datetime.strptime(j.get("data_hora_brasilia", "")[:19], "%Y-%m-%dT%H:%M:%S")
            if dt < copa_inicio:
                h_fora.append(j["slug"])
        except Exception:
            pass
    _chk(not h_fora, "Todos os horários >= 11/06/2026",
         f"{len(h_fora)} jogos com data antes da Copa: {h_fora[:3]}")

    # 6. Cidades preenchidas
    sem_cidade = [j["slug"] for j in jogos if not (j.get("cidade") or "").strip()]
    _chk(not sem_cidade, "Todas as cidades preenchidas",
         f"{len(sem_cidade)} jogos sem cidade")

    # 7. IDs de times positivos
    ids_inv = [j["slug"] for j in jogos
               if not isinstance(j.get("time_casa_id"), int) or j.get("time_casa_id", 0) <= 0]
    _chk(not ids_inv, "IDs de times são inteiros positivos",
         f"{len(ids_inv)} IDs inválidos: {ids_inv[:3]}")

    # 8. URLs de logos
    logos_inv = [j["slug"] for j in jogos
                 if j.get("time_casa_logo") and "api-sports.io" not in j["time_casa_logo"]]
    _chk(not logos_inv, "Logos com URL api-sports.io",
         f"{len(logos_inv)} logos com URL suspeita")

    # 9. Rodadas nomeadas com "Rodada"
    rod_inv = [j["slug"] for j in jogos if "Rodada" not in j.get("rodada", "")]
    _chk(not rod_inv, "Rodadas com nomenclatura correta",
         f"{len(rod_inv)} rodadas com nomenclatura incorreta: {rod_inv[:3]}")

    # 10. Grupos A–L
    grupos = {j.get("grupo_letra", "") for j in jogos if j.get("grupo_letra")}
    stats["grupos"] = sorted(grupos)
    _chk(len(grupos) == 12, f"12 grupos (A-L): {sorted(grupos)}",
         f"Grupos encontrados ({len(grupos)}): {sorted(grupos)}")

    stats.update({
        "total_times": len(times),
        "total_cidades": len({j.get("cidade", "") for j in jogos if j.get("cidade")}),
    })
    has_critico = total != 72
    status = "error" if has_critico else ("warning" if problemas else "ok")
    return {"status": status, "problemas": problemas, "stats": stats}


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO 2 — SQUADS
# ═══════════════════════════════════════════════════════════════════════════════

def validar_squads() -> dict:
    print("\n👥 BLOCO 2 — VALIDAÇÃO DOS SQUADS")
    problemas: list[str] = []

    sq_path = ROOT / "seeds" / "squads_copa_2026.json"
    if not sq_path.exists():
        _warn("squads_copa_2026.json não encontrado — será gerado no primeiro uso")
        return {"status": "warning", "problemas": ["arquivo não encontrado"],
                "stats": {"total_selecoes": 0, "total_jogadores": 0}}

    data     = json.loads(sq_path.read_text(encoding="utf-8"))
    squads   = data.get("squads", {})
    n_sel    = len(squads)
    n_total  = sum(len(v) for v in squads.values())

    _chk(n_sel >= 40, f"{n_sel} seleções no cache",
         f"Apenas {n_sel} seleções (esperado >= 40 das 48)")

    # Verifica cada seleção
    sel_problemas = []
    for nome, jogadores in squads.items():
        if not (20 <= len(jogadores) <= 26):
            sel_problemas.append(f"{nome}: {len(jogadores)} jogadores (esperado 20-26)")
            continue
        # Campos obrigatórios
        for j in jogadores:
            if not j.get("nome") or not j.get("pos") or not j.get("clube"):
                sel_problemas.append(f"{nome}: jogador sem nome/pos/clube")
                break
        # Posições válidas
        pos_validas = {"GK", "DF", "MF", "FW"}
        pos_inv = [j["pos"] for j in jogadores if j.get("pos") not in pos_validas]
        if pos_inv:
            sel_problemas.append(f"{nome}: posições inválidas {set(pos_inv)}")
        # Nomes duplicados
        nomes = [j["nome"] for j in jogadores if j.get("nome")]
        if len(nomes) != len(set(nomes)):
            sel_problemas.append(f"{nome}: nomes duplicados")

    _chk(not sel_problemas, f"Todos os {n_sel} squads com estrutura válida",
         f"{len(sel_problemas)} problemas nos squads: {sel_problemas[:3]}")
    problemas.extend(sel_problemas[:10])

    media = round(n_total / n_sel, 1) if n_sel else 0
    _ok(f"Total: {n_sel} seleções · {n_total} jogadores · média {media}/seleção")

    status = "ok" if not problemas else ("warning" if n_sel >= 40 else "error")
    return {"status": status, "problemas": problemas,
            "stats": {"total_selecoes": n_sel, "total_jogadores": n_total, "media_por_selecao": media}}


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO 3 — API-FOOTBALL (usa cache do Bloco 6)
# ═══════════════════════════════════════════════════════════════════════════════

async def validar_api_football(partidas_cache: dict) -> dict:
    print("\n⚽ BLOCO 3 — VALIDAÇÃO DA API-FOOTBALL")
    problemas: list[str] = []
    quota_restante = "?"
    tempos: dict = {}

    # Verifica quota via /status
    try:
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{FB_BASE}/status", headers=FB_HDR)
        tempos["status"] = round((time.perf_counter() - t0) * 1000)
        if r.status_code == 200:
            info      = r.json().get("response", {})
            requests  = info.get("requests", {})
            quota_dia = requests.get("day", {})
            usado     = quota_dia.get("current", "?")
            limite    = quota_dia.get("limit", "?")
            quota_restante = f"{usado}/{limite}"
            _ok(f"API-Football acessível | Quota do dia: {usado}/{limite}")
        else:
            _warn(f"Status endpoint retornou HTTP {r.status_code}")
    except Exception as e:
        _warn(f"Não foi possível verificar quota: {e}")

    if not partidas_cache:
        _warn("Nenhuma partida em cache — Bloco 6 deve rodar antes")
        return {"status": "warning", "problemas": ["sem cache do bloco 6"],
                "quota_restante": quota_restante, "tempos_resposta": tempos, "times_sem_dados": []}

    times_sem_dados: list[str] = []

    for slug, p in partidas_cache.items():
        if p is None:
            continue
        nome = f"{p.time_casa_nome} x {p.time_fora_nome}"

        # 3a. Forma recente
        n_fc = len(p.forma_casa)
        n_ff = len(p.forma_fora)
        _chk(n_fc >= 3, f"{p.time_casa_nome}: {n_fc} jogos na forma",
             f"{p.time_casa_nome}: apenas {n_fc} jogos na forma (esperado >= 3)")
        _chk(n_ff >= 3, f"{p.time_fora_nome}: {n_ff} jogos na forma",
             f"{p.time_fora_nome}: apenas {n_ff} jogos na forma (esperado >= 3)")

        # Valida consistência das formas
        for entry in p.forma_casa + p.forma_fora:
            if entry.placar_proprio is not None and entry.placar_adversario is not None:
                g_p = entry.placar_proprio
                g_a = entry.placar_adversario
                if not (0 <= g_p <= 15 and 0 <= g_a <= 15):
                    problemas.append(f"{nome}: placar inválido {g_p}-{g_a}")
                res_esperado = ("W" if g_p > g_a else ("L" if g_p < g_a else "D"))
                if entry.resultado != res_esperado:
                    problemas.append(f"{nome}: resultado {entry.resultado} inconsistente com placar {g_p}-{g_a}")

        # 3b. Stats históricas
        if p.stats_casa.dados_insuficientes:
            times_sem_dados.append(p.time_casa_nome)
            _warn(f"{p.time_casa_nome}: stats_insuficientes (sem histórico internacional encontrado)")
        else:
            mg = p.stats_casa.media_gols_marcados
            ms = p.stats_casa.media_gols_sofridos
            if mg is not None and not (0.0 <= mg <= 5.0):
                problemas.append(f"{p.time_casa_nome}: media_gols_marcados={mg} fora do range")
            if ms is not None and not (0.0 <= ms <= 5.0):
                problemas.append(f"{p.time_fora_nome}: media_gols_sofridos={ms} fora do range")
            _ok(f"{p.time_casa_nome}: stats de '{p.stats_casa.fonte}' | {p.stats_casa.jogos} jogos")

        if p.stats_fora.dados_insuficientes:
            times_sem_dados.append(p.time_fora_nome)
        else:
            _ok(f"{p.time_fora_nome}: stats de '{p.stats_fora.fonte}' | {p.stats_fora.jogos} jogos")

        # 3c. H2H
        n_h2h = len(p.head_to_head)
        _ok(f"H2H {nome}: {n_h2h} confronto(s)")
        for h in p.head_to_head:
            gc = h.get("gols_casa", 0) or 0
            gf = h.get("gols_fora", 0) or 0
            if not (0 <= gc <= 15 and 0 <= gf <= 15):
                problemas.append(f"H2H {nome}: placar inválido {gc}-{gf}")

    times_sem_dados_uniq = list(set(times_sem_dados))
    if times_sem_dados_uniq:
        _ok(f"Times sem histórico internacional completo: {times_sem_dados_uniq} (normal para estreantes)")

    status = "error" if any(c in " ".join(_criticos) for c in ["API-Football"]) else \
             ("warning" if problemas else "ok")
    return {
        "status":          "ok" if not problemas else "warning",
        "problemas":       problemas,
        "quota_restante":  quota_restante,
        "tempos_resposta": tempos,
        "times_sem_dados": times_sem_dados_uniq,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO 4 — ODDS API
# ═══════════════════════════════════════════════════════════════════════════════

async def validar_odds_api() -> dict:
    print("\n📊 BLOCO 4 — VALIDAÇÃO DA ODDS API")
    problemas: list[str] = []
    req_restantes = "?"
    n_jogos = 0
    shin_ok = False
    zscore_ok = False

    if ODDS_ENGINE_OK:
        _ok("odds_engine.py importado com sucesso")
    else:
        _warn("odds_engine.py não encontrado — usando implementações inline para testes")

    # 4a. Conectividade
    sport = "soccer_fifa_world_cup"
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(
                f"https://api.the-odds-api.com/v4/sports/{sport}/odds",
                params={"apiKey": API_ODDS_KEY, "regions": "eu",
                        "markets": "h2h", "oddsFormat": "decimal"},
            )
        req_restantes = r.headers.get("x-requests-remaining", "?")
        req_usados    = r.headers.get("x-requests-used", "?")

        if r.status_code == 200:
            eventos = r.json()
            n_jogos = len(eventos) if isinstance(eventos, list) else 0
            _ok(f"Odds API acessível | Requests restantes: {req_restantes} | {n_jogos} jogos com odds")

            # 4b. Qualidade das odds
            margem_problemas = 0
            for ev in (eventos if isinstance(eventos, list) else []):
                for bm in ev.get("bookmakers", []):
                    for mkt in bm.get("markets", []):
                        if mkt.get("key") != "h2h":
                            continue
                        outcomes = mkt.get("outcomes", [])
                        if len(outcomes) != 3:
                            problemas.append(f"h2h com {len(outcomes)} outcomes (esperado 3)")
                        for o in outcomes:
                            odd = float(o.get("price", 0))
                            if odd <= 1.0:
                                problemas.append(f"Odd inválida: {odd}")
                        if outcomes:
                            soma_impl = sum(1 / float(o["price"]) for o in outcomes if float(o.get("price", 0)) > 0)
                            if soma_impl > 1.15:
                                margem_problemas += 1
            if margem_problemas:
                _warn(f"{margem_problemas} evento(s) com margem > 15% — casas recreativas")
            else:
                _ok("Margens dentro do esperado (< 15%)")

            # Pega odds do primeiro jogo para testes de Shin e z-score
            odds_teste: list[float] = []
            for ev in (eventos if isinstance(eventos, list) else []):
                for bm in ev.get("bookmakers", []):
                    for mkt in bm.get("markets", []):
                        if mkt.get("key") == "h2h" and len(mkt.get("outcomes", [])) == 3:
                            odds_teste = [float(o["price"]) for o in mkt["outcomes"]]
                            break
                    if odds_teste:
                        break
                if odds_teste:
                    break

            # 4c. Shin Method
            if odds_teste:
                probs_shin = _shin_fn(odds_teste)
                soma_shin  = sum(probs_shin)
                shin_ok    = (
                    abs(soma_shin - 1.0) < 0.01
                    and all(0.0 < p < 1.0 for p in probs_shin)
                )
                # Probs Shin devem ser menores que implied (margem removida)
                impl_probs = [1.0 / o for o in odds_teste]
                K          = sum(impl_probs)
                shin_menor = all(ps < pi for ps, pi in zip(probs_shin, impl_probs))
                _chk(abs(soma_shin - 1.0) < 0.01,
                     f"Shin Method: soma={soma_shin:.4f} ≈ 1.0",
                     f"Shin Method: soma={soma_shin:.4f} ≠ 1.0", critico=True)
                _chk(all(0.0 < p < 1.0 for p in probs_shin),
                     f"Shin Method: todas as probs em (0,1): {[round(p,3) for p in probs_shin]}",
                     "Shin Method: probabilidade negativa ou >= 1.0 detectada", critico=True)
                _chk(shin_menor,
                     f"Shin Method: probs < implied (margem removida) ✓",
                     f"Shin Method: probs shin >= implied — margem NÃO foi removida")
            else:
                _warn("Nenhum jogo h2h disponível para testar Shin Method")

        elif r.status_code == 422:
            _warn(f"Odds API: Copa 2026 não disponível ainda (422) — normal antes do torneio")
        else:
            _warn(f"Odds API retornou HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        _warn(f"Odds API não acessível: {e}")

    # 4d. Z-score — testa com valores conhecidos
    # Fórmula: z = (p_modelo - p_consenso) / sqrt(p_consenso * (1-p_consenso) / n)
    try:
        z1 = _zscore_fn(0.60, 0.50, 10)
        # Com n=10: SE = sqrt(0.25/10) = 0.1581, z = 0.10/0.1581 ≈ 0.632
        z1_esperado = 0.10 / math.sqrt(0.50 * 0.50 / 10)
        z1_ok = abs(z1 - z1_esperado) < 0.01

        z2 = _zscore_fn(0.51, 0.50, 5)
        # Com n=5: z = 0.01 / sqrt(0.25/5) ≈ 0.063
        z2_esperado = 0.01 / math.sqrt(0.50 * 0.50 / 5)
        z2_ok = abs(z2 - z2_esperado) < 0.01

        zscore_ok = z1_ok and z2_ok and z1 > z2  # maior diferença/amostra = mais significativo
        _chk(z1_ok, f"Z-score(0.60, 0.50, n=10) = {z1:.3f} (esperado ≈ {z1_esperado:.3f})",
             f"Z-score(0.60, 0.50, n=10) = {z1:.3f} ≠ esperado {z1_esperado:.3f}", critico=True)
        _chk(z2 < z1, f"Z-score menor com menor diferença/amostra: {z2:.3f} < {z1:.3f}",
             f"Z-score não decresce com menor diferença: z2={z2:.3f} >= z1={z1:.3f}", critico=True)

        # Nota: o spec menciona z≈2.11 para n=10, que seria correto para n≈111
        _ok(f"Nota: z(n=10)≈0.63, z(n=111)≈2.11 — fórmula matematicamente correta")
    except Exception as e:
        _err(f"Z-score com erro matemático: {e}")

    return {
        "status":             "ok" if not [p for p in problemas if "inválida" in p] else "warning",
        "problemas":          problemas,
        "requests_remaining": req_restantes,
        "jogos_com_odds":     n_jogos,
        "shin_ok":            shin_ok,
        "zscore_ok":          zscore_ok,
        "odds_engine_importado": ODDS_ENGINE_OK,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO 5 — MODELO ESTATÍSTICO (sem API)
# ═══════════════════════════════════════════════════════════════════════════════

def validar_modelo_estatistico() -> dict:
    print("\n🔬 BLOCO 5 — VALIDAÇÃO DO MODELO ESTATÍSTICO")
    passaram = 0
    falharam = 0
    detalhes: list[str] = []

    def _t(nome, cond, detalhe=""):
        nonlocal passaram, falharam
        if cond:
            passaram += 1
            _ok(f"{nome}")
        else:
            falharam += 1
            msg = f"{nome}: {detalhe}"
            detalhes.append(msg)
            _warn(msg)
        return cond

    # 5a. Dixon-Coles: time forte (λ=2.0) vs fraco (λ=0.5)
    m_forte  = _dc_matrix(2.0, 0.5)
    p_forte  = _market_probs(m_forte, 2.0, 0.5)
    soma_forte = sum(m_forte.values())
    _t("DC — soma total ≈ 100%", abs(soma_forte - 100.0) < 1.0, f"soma={soma_forte:.1f}%")
    _t("DC — vitoria_casa > 70% (forte em casa)", p_forte["vitoria_casa"] > 70,
       f"vitoria_casa={p_forte['vitoria_casa']}%")
    _t("DC — vitoria_fora < 10% (fraco fora)", p_forte["vitoria_fora"] < 10,
       f"vitoria_fora={p_forte['vitoria_fora']}%")
    # Dixon-Coles aumenta P(placares baixos via tau), então com λ_total=2.5
    # o Over 2.5 fica em ~44-47% (abaixo de 50%) — threshold ajustado para > 40%
    _t("DC — over25 > 40% (λ total=2.5, DC corrige p/ baixo)", p_forte["over25"] > 40,
       f"over25={p_forte['over25']}%")
    _t("DC — nenhuma prob negativa",
       all(v >= 0 for v in m_forte.values()),
       "prob negativa detectada")
    # Placar mais provável
    top_placar = max(m_forte.items(), key=lambda x: x[1])
    _t(f"DC — placar mais provável razoável ({top_placar[0]} = {top_placar[1]:.1f}%)",
       top_placar[0] not in ("0-0", "0-1"), f"placar mais provável inesperado: {top_placar[0]}")

    # Partida equilibrada (λ_casa=1.3, λ_fora=1.2)
    m_eq = _dc_matrix(1.3, 1.2)
    p_eq = _market_probs(m_eq, 1.3, 1.2)
    soma_eq = sum(v for k, v in p_eq.items() if k in ("vitoria_casa", "empate", "vitoria_fora"))
    _t("DC equilibrado — probs 1X2 somam 100%", abs(soma_eq - 100.0) < 1.0, f"soma={soma_eq:.1f}%")
    _t("DC equilibrado — vitoria_casa entre 35% e 50%",
       35 <= p_eq["vitoria_casa"] <= 50, f"vitoria_casa={p_eq['vitoria_casa']}%")
    _t("DC equilibrado — empate entre 20% e 35%",
       20 <= p_eq["empate"] <= 35, f"empate={p_eq['empate']}%")

    # 5b. Correção DC para placares baixos (tau)
    lam, mu = 1.5, 1.2
    tau_00 = _tau(0, 0, lam, mu, DC_RHO)
    tau_11 = _tau(1, 1, lam, mu, DC_RHO)
    tau_33 = _tau(3, 3, lam, mu, DC_RHO)
    _t(f"DC correção — tau(0,0) > 1.0 (aumenta P(0-0)): {tau_00:.3f}",
       tau_00 > 1.0, f"tau(0,0)={tau_00:.3f}")
    _t(f"DC correção — tau(1,1) > 1.0 (aumenta P(1-1)): {tau_11:.3f}",
       tau_11 > 1.0, f"tau(1,1)={tau_11:.3f}")
    _t(f"DC correção — tau(3,3) == 1.0 (não afeta placares altos): {tau_33:.3f}",
       tau_33 == 1.0, f"tau(3,3)={tau_33:.3f}")

    # 5c. Fat Tail Correction
    matrix_dc = _dc_matrix(1.5, 1.2)
    matrix_ft = _fat_tail_matrix(matrix_dc, 1.5, 1.2)
    soma_ft   = sum(matrix_ft.values())
    p40_dc    = matrix_dc.get("4-0", 0)
    p40_ft    = matrix_ft.get("4-0", 0)
    p10_dc    = matrix_dc.get("1-0", 0)
    p10_ft    = matrix_ft.get("1-0", 0)
    _t(f"Fat Tail — soma ≈ 100% após correção: {soma_ft:.1f}%",
       abs(soma_ft - 100.0) < 1.5, f"soma={soma_ft:.1f}%")
    _t(f"Fat Tail — P(4-0) aumenta: {p40_dc:.2f}% → {p40_ft:.2f}%",
       p40_ft >= p40_dc, f"P(4-0) não aumentou: {p40_dc:.2f}% → {p40_ft:.2f}%")
    _t(f"Fat Tail — P(1-0) não muda muito: Δ={abs(p10_ft - p10_dc):.2f}%",
       abs(p10_ft - p10_dc) < 3.0, f"Δ P(1-0) = {abs(p10_ft-p10_dc):.2f}% (esperado < 3pp)")

    # 5d. Context Engine — Home advantage México
    forma_vazia: list[EntradaForma] = []
    stats_empty = EstatisticasTemporada(dados_insuficientes=False, jogos=5,
                                        media_gols_marcados_recente=1.5,
                                        media_gols_sofridos_recente=0.8)
    modelo_base = ModeloGols(
        lambda_casa=1.5, lambda_fora=0.8,
        prob_vitoria_casa=55.0, prob_empate=25.0, prob_vitoria_fora=20.0,
        prob_btts=40.0, prob_over15=80.0, prob_under15=20.0,
        prob_over25=52.0, prob_under25=48.0, prob_over35=22.0, prob_under35=78.0,
        top5_placares=[{"placar": "1-0", "prob": 15.0}, {"placar": "2-0", "prob": 12.0},
                       {"placar": "1-1", "prob": 11.0}, {"placar": "0-0", "prob": 8.0},
                       {"placar": "2-1", "prob": 7.0}],
        skellam_vitoria=55.0, skellam_empate=25.0, skellam_derrota=20.0,
    )
    rating_mex = RatingDinamico(elo_score=1841.0, pi_rating=0.3, rating_combinado=1.5)
    rating_sa  = RatingDinamico(elo_score=1641.0, pi_rating=-0.2, rating_combinado=-0.3)

    partida_mex = Partida(
        id=1, slug="mexico-south-africa",
        rodada="Rodada 1 — Grupo A",
        horario="2026-06-11T20:00:00-03:00",
        status="NS", estadio="Estadio Azteca", cidade="Mexico City",
        time_casa_nome="Mexico", time_casa_logo="",
        time_casa_id=16,
        time_fora_nome="South Africa", time_fora_logo="",
        time_fora_id=1531,
        stats_casa=stats_empty, stats_fora=stats_empty,
        forma_casa=forma_vazia, forma_fora=forma_vazia,
    )

    try:
        ctx_mex, modelo_mex = _calcular_contexto(partida_mex, rating_mex, rating_sa, modelo_base)
        _t("Context Engine — Home advantage México detectado",
           ctx_mex.home_advantage, "home_advantage=False para México em casa")
        _t(f"Context Engine — λ_casa boost: {modelo_mex.lambda_casa:.3f} >= {modelo_base.lambda_casa * 1.20:.3f}",
           modelo_mex.lambda_casa >= modelo_base.lambda_casa * 1.20,
           f"λ_casa={modelo_mex.lambda_casa:.3f} não foi aumentado (base={modelo_base.lambda_casa})")
        _t(f"Context Engine — λ_fora penalty: {modelo_mex.lambda_fora:.3f} <= {modelo_base.lambda_fora * 0.85:.3f}",
           modelo_mex.lambda_fora <= modelo_base.lambda_fora * 0.85,
           f"λ_fora={modelo_mex.lambda_fora:.3f} não foi reduzido (base={modelo_base.lambda_fora})")
    except Exception as e:
        falharam += 1
        detalhes.append(f"Context Engine erro: {e}")
        _warn(f"Context Engine erro: {e}")

    # Campo neutro: França vs Senegal (nenhum é sede)
    partida_neu = partida_mex.model_copy(update={
        "time_casa_nome": "France", "time_fora_nome": "Senegal",
        "time_casa_id": 2, "time_fora_id": 25,
        "cidade": "New York",
    })
    try:
        ctx_neu, _ = _calcular_contexto(partida_neu, rating_mex, rating_sa, modelo_base)
        _t("Context Engine — campo neutro para França x Senegal",
           not ctx_neu.home_advantage, "home_advantage=True para jogo neutro")
    except Exception as e:
        falharam += 1
        detalhes.append(f"Context Engine campo neutro erro: {e}")

    # Rodada 1 — Under25 deve aumentar
    try:
        ctx_r1, modelo_r1 = _calcular_contexto(partida_mex, rating_mex, rating_sa, modelo_base)
        _t("Context Engine — Rodada 1 detectada",
           ctx_r1.primeira_rodada, "primeira_rodada=False para jogo 'Rodada 1'")
        _t(f"Context Engine — Under25 ajustado na Rodada 1: {modelo_r1.prob_under25:.1f}% > {modelo_base.prob_under25:.1f}%",
           modelo_r1.prob_under25 > modelo_base.prob_under25,
           f"Under25 não aumentou: {modelo_base.prob_under25}% → {modelo_r1.prob_under25}%")
    except Exception as e:
        falharam += 1
        detalhes.append(f"Context Engine Rodada 1 erro: {e}")

    # 5e. Uncertainty Index
    h2h_vazio:  list[dict] = []
    h2h_1:      list[dict] = [{"data": "2020-01-01"}]

    ui_sem_h2h, fat_sem = _uncertainty_index(h2h_vazio, 200.0, forma_vazia, forma_vazia, False, 30.0, 30.0)
    _t(f"Uncertainty — H2H vazio adiciona >= 20pts: {ui_sem_h2h:.0f}",
       ui_sem_h2h >= 20, f"ui={ui_sem_h2h:.0f}")

    ui_r1, _ = _uncertainty_index(h2h_vazio, 200.0, forma_vazia, forma_vazia, True, 30.0, 30.0)
    _t(f"Uncertainty — H2H vazio + Rodada 1 >= 30pts: {ui_r1:.0f}",
       ui_r1 >= 30, f"ui={ui_r1:.0f}")

    ui_elo, _ = _uncertainty_index([{"d": 1}], 80.0, forma_vazia, forma_vazia, False, 30.0, 30.0)
    _t(f"Uncertainty — Elo diff < 100 adiciona pts: {ui_elo:.0f}",
       ui_elo >= 15, f"ui={ui_elo:.0f}")

    # Achatamento quando ui > 60
    p_vc, p_e, p_vf = _achatar_probabilidades(65.0, 20.0, 15.0, 0.375)
    soma_ach = p_vc + p_e + p_vf
    _t(f"Achatamento — soma mantida: {soma_ach:.1f}%", abs(soma_ach - 100.0) < 1.0, f"soma={soma_ach}")
    _t(f"Achatamento — probs aproximam 33%: {p_vc:.1f}/{p_e:.1f}/{p_vf:.1f}",
       p_vc < 65.0 and p_e > 20.0, f"sem movimento em direção a 33%")
    _t("Achatamento — não chegou exatamente a 33%",
       p_vc != 33.3, "achatamento absoluto (errado)")

    # 5f. Normalização Elo regional
    conf_mex   = _CONFEDERACAO.get("Mexico", "")
    conf_bra   = _CONFEDERACAO.get("Brazil", "")
    stats_conc = _STATS_REGIONAIS.get("CONCACAF", {})
    stats_csb  = _STATS_REGIONAIS.get("CONMEBOL", {})
    elo_mex    = _ELO_FALLBACK.get("Mexico", 0)
    elo_bra    = _ELO_FALLBACK.get("Brazil", 0)
    _t(f"Elo Regional — México é CONCACAF: {conf_mex}", conf_mex == "CONCACAF")
    _t(f"Elo Regional — Brasil é CONMEBOL: {conf_bra}", conf_bra == "CONMEBOL")
    if stats_conc:
        z_mex = (elo_mex - stats_conc["media"]) / max(stats_conc["std"], 1.0)
        _t(f"Elo Regional — México z-score CONCACAF > 0: {z_mex:.2f}",
           z_mex > 0, f"México não é o melhor da CONCACAF? z={z_mex:.2f}")

    # 5g. P90 + LSS
    lss_pl = _lss_da_liga("Premier League")
    lss_mx = _lss_da_liga("Liga MX")
    _t(f"LSS Premier League = 1.0: {lss_pl}", lss_pl == 1.0, f"LSS PL={lss_pl}")
    _t(f"LSS Liga MX = 0.75: {lss_mx}", lss_mx == 0.75, f"LSS MX={lss_mx}")

    raw_pl = {
        "goals": 10, "assists": 5, "shots_on_goal": 30,
        "key_passes": 20, "dribbles": 15, "yellow_cards": 3,
        "minutes": 2700, "appearances": 30,
        "clube_nome": "Arsenal", "clube_logo": "", "liga_nome": "Premier League",
        "liga_lss": 1.00, "_lss_min_weighted": 2700.0,
        "_minutos_liga": 2700, "copa_apenas": False, "foto": "", "api_nome": "Player A",
    }
    raw_mx = {
        "goals": 15, "assists": 3, "shots_on_goal": 45,
        "key_passes": 18, "dribbles": 20, "yellow_cards": 5,
        "minutes": 2700, "appearances": 30,
        "clube_nome": "Club America", "clube_logo": "", "liga_nome": "Liga MX",
        "liga_lss": 0.75, "_lss_min_weighted": 2025.0,
        "_minutos_liga": 2700, "copa_apenas": False, "foto": "", "api_nome": "Player B",
    }
    p90_pl = calcular_p90(raw_pl)
    p90_mx = calcular_p90(raw_mx)

    g90_pl  = p90_pl.get("goals_p90", 0) or 0
    g90_mx  = p90_mx.get("goals_p90", 0) or 0
    gadj_pl = p90_pl.get("goals_p90_adj", 0) or 0
    gadj_mx = p90_mx.get("goals_p90_adj", 0) or 0

    _t(f"P90 — Player A (PL): goals_p90={g90_pl:.3f} ≈ 0.333",
       abs(g90_pl - 0.333) < 0.01, f"g90={g90_pl:.3f}")
    _t(f"P90 — Player A adj = {gadj_pl:.3f} ≈ 0.333 (PL LSS=1.0)",
       abs(gadj_pl - 0.333) < 0.01, f"adj={gadj_pl:.3f}")
    _t(f"P90 — Player B (MX): goals_p90={g90_mx:.3f} ≈ 0.500",
       abs(g90_mx - 0.500) < 0.01, f"g90={g90_mx:.3f}")
    _t(f"P90 — Player B adj = {gadj_mx:.3f} ≈ 0.375 (MX LSS=0.75)",
       abs(gadj_mx - 0.375) < 0.01, f"adj={gadj_mx:.3f}")
    _t(f"P90 — Player B adj ({gadj_mx:.3f}) > Player A adj ({gadj_pl:.3f}) — mais gols brutos compensa liga fraca",
       gadj_mx > gadj_pl, f"adj B={gadj_mx:.3f} <= adj A={gadj_pl:.3f}")

    status = "ok" if falharam == 0 else ("warning" if falharam <= 3 else "error")
    return {
        "status":          status,
        "testes_passaram": passaram,
        "testes_falharam": falharam,
        "detalhes":        detalhes,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO 6 — END-TO-END
# ═══════════════════════════════════════════════════════════════════════════════

async def validar_end_to_end() -> dict:
    print("\n🔄 BLOCO 6 — VALIDAÇÃO END-TO-END")
    problemas: list[str] = []
    jogos_ok: dict = {}
    partidas_cache: dict = {}

    test_slugs = ["mexico-south-africa", "brazil-morocco", "france-senegal"]

    for slug in test_slugs:
        print(f"\n  Buscando {slug}...")
        t0 = time.perf_counter()
        try:
            p = await buscar_detalhe_partida(slug)
            elapsed = round((time.perf_counter() - t0), 1)
        except Exception as e:
            _err(f"{slug}: exceção ao buscar partida: {e}")
            problemas.append(f"{slug}: {e}")
            jogos_ok[slug] = False
            partidas_cache[slug] = None
            continue

        if p is None:
            _err(f"{slug}: retornou None (slug não encontrado no seed)")
            problemas.append(f"{slug}: partida não encontrada")
            jogos_ok[slug] = False
            partidas_cache[slug] = None
            continue

        partidas_cache[slug] = p
        jogo_problemas: list[str] = []

        # 6a. Campos obrigatórios
        campos_req = {
            "id": p.id, "slug": p.slug, "rodada": p.rodada,
            "horario": p.horario, "estadio": p.estadio, "cidade": p.cidade,
            "time_casa_nome": p.time_casa_nome, "time_fora_nome": p.time_fora_nome,
            "time_casa_logo": p.time_casa_logo, "time_fora_logo": p.time_fora_logo,
        }
        nulos = [k for k, v in campos_req.items() if not v]
        if nulos:
            jogo_problemas.append(f"campos nulos: {nulos}")

        # 6b. Consistência das probabilidades
        if p.probabilidades:
            soma_probs = (p.probabilidades.vitoria_casa +
                          p.probabilidades.empate +
                          p.probabilidades.vitoria_fora)
            if abs(soma_probs - 100.0) > 1.0:
                jogo_problemas.append(f"probs somam {soma_probs:.1f}% (esperado 100%)")
                _err(f"{slug}: probs somam {soma_probs:.1f}%")
            else:
                _ok(f"{slug}: probs={p.probabilidades.vitoria_casa}%/{p.probabilidades.empate}%/"
                    f"{p.probabilidades.vitoria_fora}% — soma={soma_probs:.0f}%")

            if p.probabilidades.lambda_casa <= 0 or p.probabilidades.lambda_fora <= 0:
                jogo_problemas.append("lambda <= 0")
        else:
            _warn(f"{slug}: sem probabilidades")

        # Placares prováveis
        if len(p.placares_provaveis) >= 3:
            _ok(f"{slug}: {len(p.placares_provaveis)} placares prováveis")
        else:
            _warn(f"{slug}: apenas {len(p.placares_provaveis)} placares (esperado >= 3)")

        # Ratings
        for nome, rating in [(p.time_casa_nome, p.rating_casa), (p.time_fora_nome, p.rating_fora)]:
            if rating is None:
                _warn(f"{slug}: rating de {nome} é None")
                continue
            if rating.elo_score is None:
                _warn(f"{slug}: elo_score de {nome} é None (usando fallback)")
            if not rating.confederacao:
                _warn(f"{slug}: confederação de {nome} não mapeada")
            else:
                _ok(f"{slug}: {nome} — Elo={rating.elo_score} | Conf={rating.confederacao} | "
                    f"Combinado={rating.rating_combinado}")

        # H2H — verifica h2h_exibir (não deve ser condição de dados_insuficientes)
        n_h2h = len(p.head_to_head)
        h2h_exibir = n_h2h >= 3
        _ok(f"{slug}: H2H={n_h2h} confronto(s) — exibir={h2h_exibir} "
            f"({'OK para análise' if h2h_exibir else 'histórico insuficiente — exibir mensagem'})")

        # dados_insuficientes não deve ser causado por H2H vazio
        if p.dados_insuficientes and n_h2h == 0 and len(p.forma_casa) >= 3 and len(p.forma_fora) >= 3:
            _warn(f"{slug}: dados_insuficientes=True apesar de ter forma — possível bug no campo")

        # 6c. Stats e forma
        _ok(f"{slug}: stats_casa='{p.stats_casa.fonte}' | insuf={p.stats_casa.dados_insuficientes}")
        _ok(f"{slug}: stats_fora='{p.stats_fora.fonte}' | insuf={p.stats_fora.dados_insuficientes}")
        _ok(f"{slug}: forma_casa={len(p.forma_casa)} jogos | forma_fora={len(p.forma_fora)} jogos | {elapsed}s")

        # 6d. Critérios de Zebra (simulação)
        _ok(f"  {slug} processado em {elapsed}s")
        jogos_ok[slug] = len(jogo_problemas) == 0
        problemas.extend(jogo_problemas)

    # 6d. Zebra — valida critérios com dados sintéticos
    print("\n  Validando critérios de Zebra (sintético)...")

    def _e_zebra(value_score, z_score, odds_disp, prob_azarao, forma_wr, elo_diff, sharp_contra=False):
        if not odds_disp:        return False
        if value_score <= 0.15:  return False
        if z_score <= 1.96:      return False
        if prob_azarao <= 0.25:  return False
        if sharp_contra:         return False
        return forma_wr > 0.60 or elo_diff < 150

    zebra_tp = _e_zebra(0.22, 2.1, True,  0.32, 0.80, 180)
    zebra_fn1 = _e_zebra(0.05, 2.1, True,  0.32, 0.80, 180)  # value baixo
    zebra_fn2 = _e_zebra(0.22, 1.5, True,  0.32, 0.80, 180)  # z baixo
    zebra_fn3 = _e_zebra(0.22, 2.1, False, 0.32, 0.80, 180)  # sem odds
    zebra_fn4 = _e_zebra(0.22, 2.1, True,  0.32, 0.80, 180, sharp_contra=True)  # sharp contra

    _chk(zebra_tp,  "Zebra TP: value=0.22, z=2.1, forma=80%, elo_diff=180 → IS zebra", "Zebra TP não detectada")
    _chk(not zebra_fn1, "Zebra FN1: value=0.05 → NÃO é zebra", "Zebra FN1 falhou (value baixo não filtrou)", critico=True)
    _chk(not zebra_fn2, "Zebra FN2: z=1.5 → NÃO é zebra", "Zebra FN2 falhou (z baixo não filtrou)", critico=True)
    _chk(not zebra_fn3, "Zebra FN3: odds indisponíveis → NÃO é zebra", "Zebra FN3 falhou (sem odds não filtrou)", critico=True)
    _chk(not zebra_fn4, "Zebra FN4: sharp money contra → NÃO é zebra", "Zebra FN4 falhou")

    zebra_ok = zebra_tp and not zebra_fn1 and not zebra_fn2 and not zebra_fn3

    # 6e. Bingo — valida composição
    print("\n  Validando critérios de Bingo (sintético)...")

    def _e_bingo_cand(prob_modelo, fair_odd, value_score, z_score, mercado):
        proibidos = ["under", "vitoria_fora", "placar exato"]
        if any(p in mercado.lower() for p in proibidos):
            return False
        return prob_modelo > 60 and fair_odd > 1.30 and value_score >= 0 and z_score > 1.65

    candidatos = [
        {"slug": "jogo1", "mercado": "over15",         "prob": 78, "odd": 1.35, "value": 0.05, "z": 2.1},
        {"slug": "jogo2", "mercado": "vitoria_casa",   "prob": 68, "odd": 1.50, "value": 0.02, "z": 1.8},
        {"slug": "jogo3", "mercado": "btts_sim",       "prob": 65, "odd": 1.60, "value": 0.04, "z": 1.9},
        {"slug": "jogo4", "mercado": "over25",         "prob": 62, "odd": 1.70, "value": 0.05, "z": 2.0},
        {"slug": "jogo1", "mercado": "empate",         "prob": 30, "odd": 3.20, "value": -0.04, "z": 1.2},
        {"slug": "jogo5", "mercado": "under25",        "prob": 70, "odd": 1.40, "value": 0.05, "z": 2.0},  # proibido
        {"slug": "jogo5", "mercado": "vitoria_fora",   "prob": 72, "odd": 1.45, "value": 0.04, "z": 2.1},  # proibido
        {"slug": "jogo6", "mercado": "over15",         "prob": 55, "odd": 1.40, "value": 0.03, "z": 1.8},  # prob < 60
    ]

    validos = [c for c in candidatos if _e_bingo_cand(c["prob"], c["odd"], c["value"], c["z"], c["mercado"])]
    # Remove duplicatas de slug (mesmo jogo)
    slugs_vistos: set = set()
    bingo_final = []
    for c in sorted(validos, key=lambda x: -(x["z"] * x["value"] if x["value"] > 0 else 0)):
        if c["slug"] not in slugs_vistos:
            bingo_final.append(c)
            slugs_vistos.add(c["slug"])
        if len(bingo_final) == 5:
            break

    odd_total = 1.0
    for c in bingo_final:
        odd_total *= c["odd"]

    _chk(3 <= len(bingo_final) <= 5, f"Bingo: {len(bingo_final)} seleções (entre 3 e 5)",
         f"Bingo: {len(bingo_final)} seleções fora do range 3-5")
    _chk(len(set(c["slug"] for c in bingo_final)) == len(bingo_final),
         "Bingo: todos de jogos diferentes",
         "Bingo: mesmo jogo selecionado 2x", critico=True)
    _chk(2.0 <= odd_total <= 8.0, f"Bingo: odd total={odd_total:.2f} (entre 2.0 e 8.0)",
         f"Bingo: odd total={odd_total:.2f} fora do range")
    under_no_bingo = any("under" in c["mercado"].lower() for c in bingo_final)
    _chk(not under_no_bingo, "Bingo: nenhum mercado Under",
         "Bingo: mercado Under incluído", critico=True)

    bingo_ok = 3 <= len(bingo_final) <= 5 and not under_no_bingo and len(set(c["slug"] for c in bingo_final)) == len(bingo_final)

    status = "error" if any(c in " ".join(_criticos[-10:]) for c in ["Zebra FN", "Bingo"]) \
             else ("warning" if problemas else "ok")

    return {
        "status":          "ok" if not problemas else "warning",
        "problemas":       problemas,
        "jogos_testados":  jogos_ok,
        "zebra_ok":        zebra_ok,
        "bingo_ok":        bingo_ok,
        "partidas_cache":  partidas_cache,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCO 7 — RELATÓRIO FINAL
# ═══════════════════════════════════════════════════════════════════════════════

def gerar_relatorio(resultados: dict) -> int:
    seed   = resultados["seed"]
    squads = resultados["squads"]
    api_fb = resultados["api_football"]
    odds   = resultados["odds_api"]
    modelo = resultados["modelo"]
    e2e    = resultados["end_to_end"]
    ts     = resultados["timestamp"]

    def icone(status):
        return {"ok": "✅", "warning": "⚠️ ", "error": "❌"}.get(status, "❓")

    n_criticos = len(_criticos)
    n_warnings = len(_warnings)

    if n_criticos > 0:
        resultado_geral = "❌ REPROVADO"
        exit_code = 1
    elif n_warnings > 3:
        resultado_geral = "⚠️  APROVADO COM RESSALVAS"
        exit_code = 0
    else:
        resultado_geral = "✅ APROVADO"
        exit_code = 0

    sep = "═" * 64

    print(f"\n\n╔{sep}╗")
    print(f"║{'RELATÓRIO DE VALIDAÇÃO — PALPITES DA IA':^64}║")
    print(f"║{'Copa do Mundo 2026  —  ' + ts[:19]:^64}║")
    print(f"╚{sep}╝")

    # Bloco 1
    s1 = seed.get("stats", {})
    print(f"\nBLOCO 1 — SEED                    [{icone(seed['status'])} {seed['status'].upper()}]")
    print(f"  • {s1.get('total_jogos', '?')} jogos · {s1.get('total_times', '?')} times · {s1.get('total_cidades', '?')} cidades")
    print(f"  • Grupos: {', '.join(s1.get('grupos', [])[:6])}{'...' if len(s1.get('grupos', [])) > 6 else ''}")
    probs = seed.get("problemas", [])
    print(f"  • Problemas: {', '.join(probs[:3]) if probs else 'Nenhum'}")

    # Bloco 2
    s2 = squads.get("stats", {})
    print(f"\nBLOCO 2 — SQUADS                  [{icone(squads['status'])} {squads['status'].upper()}]")
    print(f"  • {s2.get('total_selecoes', 0)} seleções · {s2.get('total_jogadores', 0)} jogadores · média {s2.get('media_por_selecao', 0)}/seleção")
    probs2 = squads.get("problemas", [])
    print(f"  • Problemas: {', '.join(probs2[:2]) if probs2 else 'Nenhum'}")

    # Bloco 3
    print(f"\nBLOCO 3 — API-FOOTBALL            [{icone(api_fb['status'])} {api_fb['status'].upper()}]")
    print(f"  • Quota dia: {api_fb.get('quota_restante', '?')} | Tempo status: {api_fb.get('tempos_resposta', {}).get('status', '?')}ms")
    sem_dados = api_fb.get("times_sem_dados", [])
    print(f"  • Times sem histórico completo: {', '.join(sem_dados) if sem_dados else 'Nenhum'}")
    probs3 = api_fb.get("problemas", [])
    print(f"  • Problemas: {', '.join(probs3[:2]) if probs3 else 'Nenhum'}")

    # Bloco 4
    print(f"\nBLOCO 4 — ODDS API               [{icone(odds['status'])} {odds['status'].upper()}]")
    print(f"  • Requests restantes: {odds.get('requests_remaining', '?')} | {odds.get('jogos_com_odds', 0)} jogos com odds")
    shin_s = "✅" if odds.get("shin_ok") else "⚠️ "
    zs_s   = "✅" if odds.get("zscore_ok") else "⚠️ "
    oe_s   = "✅ importado" if odds.get("odds_engine_importado") else "⚠️  não encontrado (inline usado)"
    print(f"  • Shin Method: {shin_s} | Z-score: {zs_s} | odds_engine.py: {oe_s}")
    probs4 = odds.get("problemas", [])
    print(f"  • Problemas: {', '.join(probs4[:2]) if probs4 else 'Nenhum'}")

    # Bloco 5
    tp = modelo.get("testes_passaram", 0)
    tf = modelo.get("testes_falharam", 0)
    print(f"\nBLOCO 5 — MODELO ESTATÍSTICO     [{icone(modelo['status'])} {modelo['status'].upper()}]")
    print(f"  • {tp}/{tp+tf} testes passaram")
    falhas = modelo.get("detalhes", [])
    print(f"  • Falhas: {', '.join(falhas[:3]) if falhas else 'Nenhuma'}")

    # Bloco 6
    print(f"\nBLOCO 6 — END-TO-END             [{icone(e2e['status'])} {e2e['status'].upper()}]")
    for slug, ok in e2e.get("jogos_testados", {}).items():
        print(f"  • {slug}: {'✅' if ok else '❌'}")
    zebra_s = "✅" if e2e.get("zebra_ok") else "❌"
    bingo_s = "✅" if e2e.get("bingo_ok") else "❌"
    print(f"  • Critérios Zebra: {zebra_s} | Critérios Bingo: {bingo_s}")
    probs6 = e2e.get("problemas", [])
    print(f"  • Problemas: {', '.join(probs6[:2]) if probs6 else 'Nenhum'}")

    # Resultado geral
    print(f"\n{sep}")
    print(f"RESULTADO GERAL: {resultado_geral}")
    print(f"Críticos (bloqueiam deploy): {n_criticos}")
    print(f"Warnings (monitorar)       : {n_warnings}")
    if _criticos:
        print("Críticos:")
        for c in _criticos:
            print(f"  ❌ {c}")
    if _warnings:
        print("Warnings:")
        for w in _warnings[:5]:
            print(f"  ⚠️  {w}")
        if len(_warnings) > 5:
            print(f"  ... e mais {len(_warnings)-5} warnings")
    print(sep)

    # Salva JSON
    relatorio_path = ROOT / "scripts" / "relatorio_validacao.json"
    output = {
        "timestamp":      ts,
        "resultado_geral": resultado_geral.replace("✅ ", "").replace("⚠️  ", "").replace("❌ ", ""),
        "exit_code":      exit_code,
        "n_criticos":     n_criticos,
        "n_warnings":     n_warnings,
        "criticos":       _criticos,
        "warnings":       _warnings,
        "blocos": {
            "seed":           seed,
            "squads":         squads,
            "api_football":   api_fb,
            "odds_api":       odds,
            "modelo":         modelo,
            "end_to_end":     {k: v for k, v in e2e.items() if k != "partidas_cache"},
        },
    }
    relatorio_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nRelatório JSON salvo em: {relatorio_path}")
    return exit_code


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

async def main() -> int:
    print("=" * 64)
    print("  VALIDAÇÃO COMPLETA — Palpites da IA / Copa 2026")
    print("  (usa ~20-30 requests API-Football + ~3 Odds API)")
    print("=" * 64)

    # Blocos síncronos primeiro (sem API)
    seed_r   = validar_seed()
    squads_r = validar_squads()
    modelo_r = validar_modelo_estatistico()

    # Bloco 6 primeiro (popula cache para Bloco 3)
    e2e_r = await validar_end_to_end()

    # Bloco 3 usa cache do Bloco 6
    api_fb_r = await validar_api_football(e2e_r.get("partidas_cache", {}))

    # Bloco 4 — Odds API
    odds_r = await validar_odds_api()

    resultados = {
        "timestamp":    datetime.now().isoformat(),
        "seed":         seed_r,
        "squads":       squads_r,
        "api_football": api_fb_r,
        "odds_api":     odds_r,
        "modelo":       modelo_r,
        "end_to_end":   e2e_r,
    }

    return gerar_relatorio(resultados)


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
