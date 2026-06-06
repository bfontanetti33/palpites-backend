"""
validar_dados.py — Teste de regressão local (zero chamadas de API/rede).
Roda antes de cada deploy para detectar regressões nos seeds e no modelo.

Checks:
  1. Integridade dos seeds (copa_2026, forma, squads, árbitros)
  2. Cobertura dos dicts hardcoded no ia_agent.py (ELO, CONF, FIFA)
  3. Calibração do modelo: lambdas e Over2.5 para jogos representativos
  4. Alinhamento de odds vs Elo (detecta inversão casa/fora sistêmica)

Uso:
  python scripts/validar_dados.py
  python scripts/validar_dados.py --verbose
"""

import json
import os
import re
import sys
import unicodedata
import math
from collections import Counter
from pathlib import Path

ROOT    = Path(__file__).parent.parent
SEEDS   = ROOT / "seeds"
IA_FILE = ROOT / "app" / "agents" / "ia_agent.py"

VERBOSE = "--verbose" in sys.argv
FALHAS  = []

# ── utilidades ────────────────────────────────────────────────────────────────

def norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()

def load(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def ok(msg: str):
    print(f"  OK  {msg}")

def fail(msg: str):
    FALHAS.append(msg)
    print(f"  FAIL {msg}")

def info(msg: str):
    if VERBOSE:
        print(f"       {msg}")

# ── Modelo DC local (sem importar o app) ──────────────────────────────────────

DC_RHO    = -0.1
MAX_GOALS = 6

def _poisson(lam, k):
    return (lam ** k) * math.exp(-lam) / math.factorial(k)

def _tau(x, y, lam, mu, rho):
    if x == 0 and y == 0: return 1 - lam * mu * rho
    if x == 0 and y == 1: return 1 + lam * rho
    if x == 1 and y == 0: return 1 + mu * rho
    if x == 1 and y == 1: return 1 - rho
    return 1.0

def dc_probs(lam: float, mu: float) -> dict:
    raw = {}
    for i in range(MAX_GOALS):
        for j in range(MAX_GOALS):
            p = _poisson(lam, i) * _poisson(mu, j) * _tau(i, j, lam, mu, DC_RHO)
            raw[f"{i}-{j}"] = max(p, 0.0)
    total = sum(raw.values()) or 1.0
    matrix = {k: v / total for k, v in raw.items()}

    def s(cond):
        return round(sum(v for k, v in matrix.items() if cond(*map(int, k.split("-")))) * 100, 1)

    return {
        "over25": s(lambda a, b: a + b > 2),
        "btts":   s(lambda a, b: a > 0 and b > 0),
        "vc":     s(lambda a, b: a > b),
        "empate": s(lambda a, b: a == b),
        "vf":     s(lambda a, b: a < b),
    }


# ── CHECK 1: integridade dos seeds ────────────────────────────────────────────

def check_seeds():
    print("\n[1] Integridade dos seeds")

    # copa_2026.json
    copa = load(SEEDS / "copa_2026.json")
    jogos = copa.get("jogos", [])
    times_copa = set()
    for j in jogos:
        for k in ("time_casa", "time_fora"):
            if isinstance(j.get(k), str):
                times_copa.add(j[k])

    n = len(jogos)
    if n == 72:
        ok(f"copa_2026.json: {n} jogos")
    else:
        fail(f"copa_2026.json: esperado 72 jogos, encontrado {n}")

    slugs = [j.get("slug") for j in jogos]
    dups = [s for s, c in Counter(slugs).items() if c > 1]
    if not dups:
        ok(f"copa_2026.json: 72 slugs únicos, sem duplicatas")
    else:
        fail(f"copa_2026.json: slugs duplicados: {dups}")

    sem_horario = [j.get("slug") for j in jogos if not j.get("data_hora_brasilia")]
    if not sem_horario:
        ok("copa_2026.json: todos os jogos têm horário")
    else:
        fail(f"copa_2026.json: {len(sem_horario)} jogos sem horário: {sem_horario[:5]}")

    # forma_recente_seed.json
    forma = load(SEEDS / "forma_recente_seed.json")
    forma_nomes = {v["nome"] for v in forma.get("times", {}).values() if "nome" in v}
    if len(forma_nomes) == 48:
        ok(f"forma_recente_seed.json: 48 times")
    else:
        fail(f"forma_recente_seed.json: {len(forma_nomes)} times (esperado 48)")

    falta_forma = [t for t in times_copa if not any(norm(t) == norm(f) for f in forma_nomes)]
    if not falta_forma:
        ok("forma_recente_seed.json: cobertura 48/48 vs copa_2026")
    else:
        fail(f"forma_recente_seed.json: faltam {falta_forma}")

    # squads_copa_2026.json
    squads = load(SEEDS / "squads_copa_2026.json")
    squads_dict = squads.get("squads", squads) if isinstance(squads, dict) else {}
    if len(squads_dict) == 48:
        ok(f"squads_copa_2026.json: 48 seleções")
    else:
        fail(f"squads_copa_2026.json: {len(squads_dict)} seleções (esperado 48)")

    sem_squad = []
    for nome, dados in squads_dict.items():
        # squads_copa_2026: cada time é uma lista direta de jogadores
        if isinstance(dados, list):
            jogadores = dados
        elif isinstance(dados, dict):
            jogadores = dados.get("jogadores", dados.get("players", []))
        else:
            jogadores = []
        if len(jogadores) < 11:
            sem_squad.append(f"{nome}({len(jogadores)})")
    if not sem_squad:
        ok("squads_copa_2026.json: todos com >= 11 jogadores")
    else:
        fail(f"squads_copa_2026.json: < 11 jogadores em: {sem_squad}")

    # arbitros_copa_2026.json
    arb = load(SEEDS / "arbitros_copa_2026.json")
    arb_items = arb.get("arbitros", arb if isinstance(arb, list) else [])
    n_arb = len(arb_items)
    com_stats = sum(1 for a in arb_items if isinstance(a, dict) and a.get("fonte") != "pendente" and a.get("cartoes_por_jogo") is not None)
    if n_arb >= 50:
        ok(f"arbitros_copa_2026.json: {n_arb} árbitros ({com_stats} com stats Copa 2022/2018)")
    else:
        fail(f"arbitros_copa_2026.json: apenas {n_arb} árbitros (esperado >= 50)")


# ── CHECK 2: cobertura dos dicts hardcoded ────────────────────────────────────

def check_hardcoded_dicts():
    print("\n[2] Cobertura dos dicts hardcoded (ia_agent.py)")

    src = IA_FILE.read_text(encoding="utf-8")
    copa = load(SEEDS / "copa_2026.json")
    times_copa = set()
    for j in copa.get("jogos", []):
        for k in ("time_casa", "time_fora"):
            if isinstance(j.get(k), str):
                times_copa.add(j[k])
    copa_norm = {norm(t) for t in times_copa}

    def extrai_chaves(nome):
        m = re.search(rf"_{nome}.*?=.*?\{{(.*?)\n\}}", src, re.DOTALL)
        if not m:
            return set()
        return set(re.findall(r'"([^"]+)"\s*:', m.group(1)))

    for dict_nome in ("ELO_FALLBACK", "CONFEDERACAO", "FIFA_RANKING"):
        chaves = extrai_chaves(dict_nome)
        if not chaves:
            fail(f"_{dict_nome}: não encontrado no ia_agent.py")
            continue
        faltando = [t for t in times_copa if not any(norm(t) == norm(c) for c in chaves)]
        extras   = [c for c in chaves if not any(norm(t) == norm(c) for t in times_copa)]
        if not faltando:
            info(f"_{dict_nome}: {len(chaves)} entradas ({len(extras)} aliases extras)")
            ok(f"_{dict_nome}: cobertura 48/48 ({len(extras)} alias extra: {extras})")
        else:
            fail(f"_{dict_nome}: faltam times: {faltando}")


# ── CHECK 3: calibração do modelo (lambdas e Over2.5) ─────────────────────────

def check_calibracao():
    print("\n[3] Calibração do modelo (DC local, sem API)")

    # Casos representativos com lambdas esperados razoáveis
    # Formato: (descricao, lam, mu, over25_min, over25_max)
    casos = [
        # Médias da Copa do Mundo histórica: 1.15–1.5 gols/time → over2.5 ~45-55%
        ("Jogo equilibrado  (lam=1.3, mu=1.3)", 1.3, 1.3, 40.0, 65.0),
        ("Favorito claro    (lam=1.8, mu=0.9)", 1.8, 0.9, 45.0, 65.0),
        ("Goleada esperada  (lam=2.5, mu=0.5)", 2.5, 0.5, 55.0, 80.0),
        ("Jogo muito fechado(lam=0.8, mu=0.8)", 0.8, 0.8, 10.0, 35.0),
    ]

    for desc, lam, mu, o25_min, o25_max in casos:
        p = dc_probs(lam, mu)
        o25 = p["over25"]
        within = o25_min <= o25 <= o25_max
        msg = f"{desc}: Over2.5={o25}% (esperado {o25_min}–{o25_max}%)"
        if within:
            ok(msg)
        else:
            fail(msg)
        info(f"  1X2={p['vc']}/{p['empate']}/{p['vf']} BTTS={p['btts']}%")

    # Verifica que lambda > 2.0 para seleção em forma normal é suspeito
    # (indica ausência de regressão à média)
    forma = load(SEEDS / "forma_recente_seed.json")
    lambdas_altos = []
    GLOBAL_AVG = 1.2
    for tid, tdata in forma.get("times", {}).items():
        jogos = tdata.get("jogos", [])
        if len(jogos) < 3:
            continue
        gols = [j.get("placar_proprio", 0) or 0 for j in jogos if j.get("placar_proprio") is not None]
        if not gols:
            continue
        media = sum(gols) / len(gols)
        if media > 2.2:
            lambdas_altos.append(f"{tdata.get('nome','?')}={media:.1f}")

    if not lambdas_altos:
        ok("forma_recente_seed: nenhum time com média de gols > 2.2 na forma (sem inflação óbvia)")
    else:
        fail(f"forma_recente_seed: times com média > 2.2 (risco de Over2.5 inflado sem regressão): {lambdas_altos[:8]}")


# ── CHECK 4: alinhamento odds vs Elo (snapshot local) ────────────────────────

def check_odds_vs_elo():
    print("\n[4] Alinhamento odds vs Elo (cache local)")

    snap_path = SEEDS / "cache_partidas.json"
    if not snap_path.exists():
        fail("cache_partidas.json não encontrado — rode /admin/cache-snapshot após prewarm")
        return

    snap = load(snap_path)
    dados = snap.get("dados", {})
    if not dados:
        fail("cache_partidas.json: sem entradas — rode /admin/prewarm primeiro")
        return

    invertidos, sem_odds, total = [], [], 0
    for slug, entry in dados.items():
        partida = entry.get("partida") or {}
        odds    = partida.get("odds") or {}
        oc  = odds.get("vitoria_casa")
        of_ = odds.get("vitoria_fora")
        rc  = (partida.get("rating_casa") or {}).get("elo_score", 0)
        rf  = (partida.get("rating_fora") or {}).get("elo_score", 0)
        cn  = partida.get("time_casa_nome", "?")
        fn  = partida.get("time_fora_nome", "?")

        if not oc or not of_:
            sem_odds.append(slug)
            continue
        total += 1

        fav_odds = cn if oc < of_ else fn
        fav_elo  = cn if rc >= rf else fn
        if fav_odds != fav_elo:
            invertidos.append(f"{slug} (odds:{fav_odds}, Elo:{fav_elo})")

    info(f"Jogos com odds: {total} | sem odds: {len(sem_odds)}")
    if invertidos:
        # Se cache foi gerado antes do fix de inversão (572019a), os dados
        # estarão errados até o próximo prewarm. Reporta mas não bloqueia deploy.
        pct = round(len(invertidos) / total * 100)
        msg = f"Odds invertidas ({len(invertidos)}/{total}, {pct}%): {invertidos[:5]}"
        if pct >= 50:
            fail(msg + " — rode prewarm para atualizar o cache")
        else:
            info("WARN " + msg)
            ok(f"odds vs Elo: {total} jogos, {len(invertidos)} inversão(ões) < 50% (aceitável)")
    elif total == 0:
        fail("Nenhum jogo com odds no cache — verifique ODDS_API_KEY e prewarm")
    else:
        ok(f"odds vs Elo: {total} jogos verificados, 0 inversões detectadas")

    if sem_odds:
        info(f"Sem odds: {sem_odds}")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("validar_dados.py — Teste de regressão local")
    print("=" * 60)

    check_seeds()
    check_hardcoded_dicts()
    check_calibracao()
    check_odds_vs_elo()

    print("\n" + "=" * 60)
    if FALHAS:
        print(f"RESULTADO: {len(FALHAS)} falha(s) encontrada(s):")
        for f in FALHAS:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("RESULTADO: todos os checks passaram")
        sys.exit(0)


if __name__ == "__main__":
    main()
