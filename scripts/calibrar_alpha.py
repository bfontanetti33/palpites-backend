"""
scripts/calibrar_alpha.py — Calibração estatística do alpha de regressão à média.

Fase 1: calibra contra probabilidades implícitas do mercado (odds sem margem).
Não modifica nenhum código — só análise.

Semântica do alpha:
  alpha=1.0 → sem regressão (baseline atual, lambda puro do modelo)
  alpha=0.0 → regressão total (todos os lambdas = GLOBAL_AVG = 1.2)
  alpha=x   → lambda_novo = x * lambda_base + (1-x) * GLOBAL_AVG

Simulação fiel ao código real:
  1. Lê lambda_final do cache (já inclui home boost + fatigue)
  2. Reverte home boost (divisão pelos fatores conhecidos)
  3. Aplica regressão: lambda_base_reg = alpha * base + (1-alpha) * GLOBAL_AVG
  4. Reaplica home boost
  5. Recalcula DC probs e compara com implied do mercado

Métricas:
  Brier score = MSE das 3 probs (casa/empate/fora) — penaliza desvios quadráticos
  Log-loss    = cross-entropy modelo|mercado — penaliza mais os erros de favorito
  n_inv       = número de favoritos invertidos vs mercado

Uso:
  py scripts/calibrar_alpha.py
  py scripts/calibrar_alpha.py --verbose    # mostra quais jogos invertem por alpha
"""
import argparse
import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT      = Path(__file__).parent.parent
SEEDS     = ROOT / "seeds"

GLOBAL_AVG   = 1.2
HOME_BOOST   = 1.25
AWAY_PENALTY = 0.80
DC_RHO       = -0.1
MAX_GOALS    = 6

_HOST_NATIONS = {"Mexico", "USA", "United States", "Canada"}
_CIDADE_TO_PAIS = {
    "Toronto": "Canada",    "Vancouver": "Canada",
    "Mexico City": "Mexico","Zapopan": "Mexico",
    "Monterrey": "Mexico",  "Guadalajara": "Mexico",
    "Los Angeles": "USA",   "Inglewood": "USA",
    "San Jose": "USA",      "Santa Clara": "USA",
    "Seattle": "USA",       "Arlington": "USA",
    "Dallas": "USA",        "Houston": "USA",
    "Kansas City": "USA",   "Philadelphia": "USA",
    "East Rutherford": "USA","Foxborough": "USA",
    "Boston": "USA",        "Miami": "USA",
    "Miami Gardens": "USA", "Atlanta": "USA",
}


# ── DC local ──────────────────────────────────────────────────────────────────

def _poisson(lam: float, k: int) -> float:
    return (lam ** k) * math.exp(-lam) / math.factorial(k)

def _tau(x, y, lam, mu, rho):
    if x == 0 and y == 0: return 1 - lam * mu * rho
    if x == 0 and y == 1: return 1 + lam * rho
    if x == 1 and y == 0: return 1 + mu * rho
    if x == 1 and y == 1: return 1 - rho
    return 1.0

def dc_probs(lam: float, mu: float) -> tuple[float, float, float]:
    """Retorna (p_casa, p_empate, p_fora) via Dixon-Coles."""
    raw = {}
    for i in range(MAX_GOALS):
        for j in range(MAX_GOALS):
            p = _poisson(lam, i) * _poisson(mu, j) * _tau(i, j, lam, mu, DC_RHO)
            raw[(i, j)] = max(p, 0.0)
    total = sum(raw.values()) or 1.0
    mat = {k: v / total for k, v in raw.items()}
    vc = sum(v for (i, j), v in mat.items() if i > j)
    e  = sum(v for (i, j), v in mat.items() if i == j)
    vf = sum(v for (i, j), v in mat.items() if i < j)
    return vc, e, vf


# ── Market implied ────────────────────────────────────────────────────────────

def implied(oc: float, oe: float, of_: float) -> tuple[float, float, float] | None:
    """Remove a margem da casa e retorna probs implícitas normalizadas."""
    if not (oc and oe and of_):
        return None
    r = [1/oc, 1/oe, 1/of_]
    t = sum(r)
    return r[0]/t, r[1]/t, r[2]/t


# ── Métricas ──────────────────────────────────────────────────────────────────

def brier(pm: tuple, qi: tuple) -> float:
    """Mean squared error entre vetor de probs modelo e mercado."""
    return sum((pm[i] - qi[i])**2 for i in range(3)) / 3

def logloss(pm: tuple, qi: tuple) -> float:
    """Cross-entropy tratando qi como distribuição 'verdade'."""
    eps = 1e-9
    return -sum(qi[i] * math.log(max(pm[i], eps)) for i in range(3))


# ── Carrega jogos ─────────────────────────────────────────────────────────────

def carregar_jogos(verbose: bool = False) -> list[dict]:
    cache = json.load(open(SEEDS / "cache_partidas.json", encoding="utf-8"))
    copa  = json.load(open(SEEDS / "copa_2026.json",       encoding="utf-8"))

    slug_to_cidade = {j["slug"]: j.get("cidade", "") for j in copa["jogos"]}

    jogos = []
    pulados = []
    for slug, entry in cache.items():
        pj   = entry.get("partida") or entry
        prob = pj.get("probabilidades") or {}
        odds = pj.get("odds") or {}

        lc = prob.get("lambda_casa")
        lf = prob.get("lambda_fora")
        oc = odds.get("vitoria_casa")
        oe = odds.get("empate")
        of_= odds.get("vitoria_fora")

        if not all([lc, lf, oc, oe, of_]):
            pulados.append(slug)
            continue

        imp = implied(oc, oe, of_)
        if imp is None:
            pulados.append(slug)
            continue

        home = pj.get("time_casa_nome", "")
        away = pj.get("time_fora_nome", "")

        # Detecta e reverte home boost
        cidade     = slug_to_cidade.get(slug, "")
        pais_sede  = _CIDADE_TO_PAIS.get(cidade)
        boost_appl = bool(pais_sede and home in _HOST_NATIONS)

        if boost_appl:
            # lambda_cache = lambda_base * HOME_BOOST
            # lambda_fora_cache = lambda_base_fora * AWAY_PENALTY
            lc_base = lc / HOME_BOOST
            lf_base = lf / AWAY_PENALTY
        else:
            lc_base = lc
            lf_base = lf

        jogos.append({
            "slug":        slug,
            "home":        home,
            "away":        away,
            "cidade":      cidade,
            "lc_base":     lc_base,
            "lf_base":     lf_base,
            "lc_final":    lc,
            "lf_final":    lf,
            "boost_appl":  boost_appl,
            "imp":         imp,
            "odds":        (oc, oe, of_),
        })

    if verbose:
        print(f"  Jogos carregados: {len(jogos)}  |  Pulados (sem odds/lambdas): {len(pulados)}")
        if pulados:
            print(f"  Pulados: {pulados}")
        for g in jogos:
            boost_tag = f" [boost: lc={g['lc_base']:.3f}→{g['lc_final']:.2f}, lf={g['lf_base']:.3f}→{g['lf_final']:.2f}]" if g["boost_appl"] else ""
            print(f"  {g['slug'][:36]:<36} lc_base={g['lc_base']:.3f} lf_base={g['lf_base']:.3f}{boost_tag}")
        print()

    return jogos


# ── Calibração por alpha ──────────────────────────────────────────────────────

def calibrar(jogos: list[dict], alpha: float) -> dict:
    briers, lls, invertidos = [], [], []

    for g in jogos:
        # Regressão à média
        lc_reg = alpha * g["lc_base"] + (1 - alpha) * GLOBAL_AVG
        lf_reg = alpha * g["lf_base"] + (1 - alpha) * GLOBAL_AVG

        # Reaplica home boost se estava presente
        if g["boost_appl"]:
            lc_reg = lc_reg * HOME_BOOST
            lf_reg = lf_reg * AWAY_PENALTY

        # DC probs
        pm = dc_probs(max(0.3, lc_reg), max(0.3, lf_reg))
        qi = g["imp"]

        briers.append(brier(pm, qi))
        lls.append(logloss(pm, qi))

        # Favorito invertido?
        if pm.index(max(pm)) != qi.index(max(qi)):
            invertidos.append(g["slug"])

    n = len(jogos)
    return {
        "brier":      sum(briers) / n,
        "logloss":    sum(lls) / n,
        "n_inv":      len(invertidos),
        "invertidos": invertidos,
        "n":          n,
    }


# ── Comparação lado a lado ────────────────────────────────────────────────────

def comparar_alphas(jogos: list[dict], alpha_b: float) -> bool:
    """
    Imprime tabela: alpha=1.0 (atual) vs alpha_b vs mercado, por jogo.
    Retorna True se qualquer jogo piorar (sinal de bloqueio antes de aplicar).

    Critérios de piora:
      PIORA: alpha=1.0 batia o mercado, alpha_b inverte o favorito
      afasta: ambos batem o mercado mas alpha_b fica mais longe (distância L1 > +0.04)
    """
    labs = ["casa", "empt", "fora"]

    def _run(g: dict, alpha: float) -> tuple:
        lc = alpha * g["lc_base"] + (1 - alpha) * GLOBAL_AVG
        lf = alpha * g["lf_base"] + (1 - alpha) * GLOBAL_AVG
        if g["boost_appl"]:
            lc *= HOME_BOOST
            lf *= AWAY_PENALTY
        return dc_probs(max(0.3, lc), max(0.3, lf))

    pioras:   list[str] = []
    melhoras: list[str] = []
    afasta:   list[str] = []
    ok_n = inv_n = 0

    hdr = (f"{'Jogo':<36} | {'lc_b':>5} {'lf_b':>5} | "
           f"{'fav@1.0':>7} {'p':>4} | {'fav@'+str(alpha_b):>6} {'p':>4} | "
           f"{'fav@mkt':>7} {'p':>4} | status")
    print()
    print(hdr)
    print("-" * len(hdr))

    for g in jogos:
        pm1 = _run(g, 1.0)
        pmb = _run(g, alpha_b)
        qi  = g["imp"]

        fav1 = labs[pm1.index(max(pm1))]
        favb = labs[pmb.index(max(pmb))]
        favm = labs[qi.index(max(qi))]

        p1 = max(pm1) * 100
        pb = max(pmb) * 100
        pm = max(qi)  * 100

        d1 = sum(abs(pm1[i] - qi[i]) for i in range(3))
        db = sum(abs(pmb[i] - qi[i]) for i in range(3))

        ok1 = fav1 == favm
        okb = favb == favm

        if ok1 and not okb:
            status = "PIORA !!!"
            pioras.append(g["slug"])
        elif not ok1 and okb:
            status = "melhora"
            melhoras.append(g["slug"])
        elif not ok1 and not okb:
            status = "mantém inv."
            inv_n += 1
        elif db > d1 + 0.04:
            status = "afasta"
            afasta.append(g["slug"])
            ok_n += 1
        else:
            status = "OK"
            ok_n += 1

        jogo = f"{g['home'][:16]} x {g['away'][:16]}"
        print(f"{jogo:<36} | {g['lc_base']:>5.2f} {g['lf_base']:>5.2f} | "
              f"{fav1:>7} {p1:>3.0f}% | {favb:>6} {pb:>3.0f}% | "
              f"{favm:>7} {pm:>3.0f}% | {status}")

    print()
    print(f"  OK (sem mudança):            {ok_n - len(afasta)}")
    print(f"  Melhora (inv. corrigido):    {len(melhoras)}")
    print(f"  Mantém invertido:            {inv_n}")
    print(f"  Afasta do mercado (fav ok):  {len(afasta)}")
    print(f"  PIORA (inverte fav correto): {len(pioras)}")

    if pioras:
        print(f"\n  Jogos que pioram: {pioras}")
        print(f"\n  ATENCAO: alpha={alpha_b} introduz novas inversoes — nao aplicar.")
        return True

    if afasta:
        print(f"\n  Jogos que afastam (fav ok, distancia aumenta): {afasta}")

    verde = "SEGURO" if not pioras else "BLOQUEADO"
    print(f"\n  Veredicto: {verde} — alpha={alpha_b} pode ser aplicado.")
    return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--compare", type=float, metavar="ALPHA",
                        help="Mostra tabela comparativa alpha=1.0 vs ALPHA vs mercado, por jogo.")
    args = parser.parse_args()

    print("=" * 70)
    print("calibrar_alpha.py — Fase 1: calibração contra mercado")
    print("Nota: mercado = piso de sanidade, não verdade absoluta.")
    print("Fase 2 (resultados reais) disponível após os jogos da Copa 2026.")
    print("=" * 70)
    print()

    jogos = carregar_jogos(verbose=args.verbose)
    if not jogos:
        print("Nenhum jogo com lambdas + odds encontrado. Rode o prewarm primeiro.")
        return

    print(f"Jogos na amostra: {len(jogos)}")
    print(f"GLOBAL_AVG = {GLOBAL_AVG}  |  HOME_BOOST = {HOME_BOOST}  |  AWAY_PENALTY = {AWAY_PENALTY}")
    print()

    if args.compare is not None:
        print(f"MODO COMPARAÇÃO: alpha=1.0 (atual) vs alpha={args.compare} vs mercado")
        comparar_alphas(jogos, args.compare)
        return


    alphas = [round(i * 0.05, 2) for i in range(21)]
    resultados = [(a, calibrar(jogos, a)) for a in alphas]

    # Referências
    ref = calibrar(jogos, 1.0)  # baseline atual (sem regressão)

    best_brier_a  = min(resultados, key=lambda x: x[1]["brier"])[0]
    best_ll_a     = min(resultados, key=lambda x: x[1]["logloss"])[0]

    print(f"{'alpha':>6} | {'Brier':>8} | {'LogLoss':>8} | {'N_inv':>5} | {'Brier d%':>9} | notas")
    print("-" * 72)

    for alpha, r in resultados:
        db    = (r["brier"]   - ref["brier"])   / ref["brier"]   * 100
        dl    = (r["logloss"] - ref["logloss"]) / ref["logloss"] * 100
        marks = []
        if alpha == best_brier_a:  marks.append("* min Brier")
        if alpha == best_ll_a:     marks.append("* min LogLoss")
        if alpha == 1.0:           marks.append("(baseline atual)")
        note  = "  ".join(marks)
        arrow = ">>>" if marks and alpha != 1.0 else "   "
        db_s  = f"{db:+.1f}%" if alpha != 1.0 else "   ref"
        print(f"{arrow} {alpha:>4.2f} | {r['brier']:>8.5f} | {r['logloss']:>8.5f} | {r['n_inv']:>5} | {db_s:>9} | {note}")

    print()
    print("=" * 70)
    print(f"Alpha ótimo (Brier):    {best_brier_a}")
    print(f"Alpha ótimo (LogLoss):  {best_ll_a}")
    print(f"Baseline atual alpha=1.0: Brier={ref['brier']:.5f}  LogLoss={ref['logloss']:.5f}  N_inv={ref['n_inv']}")

    if args.verbose:
        print()
        print("=== Favoritos invertidos por alpha ===")
        for alpha, r in resultados[::4]:  # a cada 0.20
            inv = r["invertidos"]
            print(f"  alpha={alpha:.2f}: {len(inv)} invertido(s) {inv}")

    print()
    print("Curva Brier (ASCII):")
    max_b  = max(r["brier"]   for _, r in resultados)
    min_b  = min(r["brier"]   for _, r in resultados)
    height = 8
    rows   = []
    for row in range(height, -1, -1):
        threshold = min_b + (max_b - min_b) * row / height
        line = ""
        for alpha, r in resultados:
            line += "#" if r["brier"] >= threshold else " "
        rows.append(f"  {threshold:.4f} |{line}|")
    print("\n".join(rows))
    print(f"          +{'-'*len(resultados)}+")
    print(f"  alpha:   {''.join(str(int(a*10)).rjust(1) for a,_ in resultados)}")
    print(f"           {''.join(['0','.','.','.','.','5','.','.','.','.','1','.','.','.','.','1','.','.','.','.','2'])}")


if __name__ == "__main__":
    main()
