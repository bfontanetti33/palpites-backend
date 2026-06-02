"""
Renderiza a página completa de um jogo no terminal —
mesmo layout do site palpitesdaia.lovable.app/partida/{slug}
"""
import json, sys, os, warnings
from pathlib import Path

# Garante que o módulo 'app' é encontrado independente de onde o script é rodado
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app, raise_server_exceptions=True)

# ─── busca dados ──────────────────────────────────────────────────────────────
SLUG = "mexico-south-africa"
r = client.get(f"/api/v1/copa/jogos/{SLUG}")
d = r.json()

# ─── odds mock (API ainda não disponibiliza para Copa 2026) ───────────────────
ODDS = {
    "1X2": [
        {"label": "Vitoria Mexico",      "odd": 2.60, "prob": d["probabilidades"]["vitoria_casa"]},
        {"label": "Empate",              "odd": 3.20, "prob": d["probabilidades"]["empate"]},
        {"label": "Vitoria Africa do Sul","odd": 2.80, "prob": d["probabilidades"]["vitoria_fora"]},
    ],
    "Ambas Marcam": [
        {"label": "Sim",  "odd": 2.50, "prob": 38},
        {"label": "Nao",  "odd": 1.52, "prob": 62},
    ],
    "Total de Gols": [
        {"label": "Mais de 2.5", "odd": 2.30, "prob": d["probabilidades"]["vitoria_fora"]},  # reuso Over
        {"label": "Menos de 2.5","odd": 1.62, "prob": 100 - d["probabilidades"]["vitoria_fora"]},
    ],
    "Dupla Hipotese": [
        {"label": "1X (Mexico ou Empate)",    "odd": 1.48, "prob": d["probabilidades"]["vitoria_casa"] + d["probabilidades"]["empate"]},
        {"label": "X2 (Empate ou Africa Sul)","odd": 1.52, "prob": d["probabilidades"]["empate"] + d["probabilidades"]["vitoria_fora"]},
    ],
}

# ─── helpers de renderizacao ──────────────────────────────────────────────────
W = 72

def linha(c="─", n=W): return c * n
def sep(c="═"):  print(c * W)
def sep2(c="─"): print(c * W)

def barra(pct, w=22):
    n = round(pct / 100 * w)
    return "█" * n + "░" * (w - n)

def nivel(pct):
    if pct >= 65: return "\033[92mALTA\033[0m"
    if pct >= 50: return "\033[93mMEDIA\033[0m"
    return "\033[91mBAIXA\033[0m"

def resultado_cor(r):
    cores = {"W": "\033[92mW\033[0m", "D": "\033[93mD\033[0m", "L": "\033[91mL\033[0m"}
    return cores.get(r, r)

def pct_bar(val_h, val_a, label, sfx=""):
    if val_h is None and val_a is None:
        return
    sh = f"{val_h}{sfx}" if val_h is not None else "---"
    sa = f"{val_a}{sfx}" if val_a is not None else "---"
    try:
        vh, va = float(str(val_h).replace("%","")), float(str(val_a).replace("%",""))
        total = vh + va
        if total > 0:
            bh = round(vh / total * 20)
            ba = 20 - bh
        else:
            bh = ba = 10
        bar = f"\033[94m{'█'*bh}\033[0m\033[91m{'█'*ba}\033[0m"
    except:
        bar = "─" * 20
    print(f"  {sh:>7}  {bar}  {sa:<7}  {label}")

# ═════════════════════════════════════════════════════════════════════════════
# CABEÇALHO
# ═════════════════════════════════════════════════════════════════════════════
print()
sep()
print(f"  \033[1mCOPA DO MUNDO FIFA 2026\033[0m  │  {d['rodada']}")
sep2()
print()

# Times e placar
casa = d["time_casa_nome"]
fora = d["time_fora_nome"]
data_br = d["horario"][8:10] + "/" + d["horario"][5:7] + "/" + d["horario"][:4]
hora_br = d["horario"][11:16]

print(f"  {'🇲🇽  ' + casa:^30}  VS  {fora + '  🇿🇦':^30}")
print()
print(f"  {'📅 ' + data_br + '  ⏰ ' + hora_br + ' (Brasilia)':^{W-2}}")
print(f"  {'📍 ' + (d['estadio'] or 'A confirmar') + ', ' + (d['cidade'] or ''):^{W-2}}")
print()
sep()

# ═════════════════════════════════════════════════════════════════════════════
# PALPITE DA IA
# ═════════════════════════════════════════════════════════════════════════════
print()
print(f"  \033[1m⚽ PALPITE DA IA\033[0m")
sep2()

prob = d["probabilidades"]
lc, lf = prob["lambda_casa"], prob["lambda_fora"]
favorito = casa if prob["vitoria_casa"] > prob["vitoria_fora"] else \
           (fora if prob["vitoria_fora"] > prob["vitoria_casa"] else "Empate")

print(f"  Favorito         :  \033[1m{favorito}\033[0m")
print(f"  Metodo           :  Distribuicao de Poisson  (λ {casa}={lc} │ λ {fora}={lf})")
print(f"  Entrada sugerida :  Empate ou vitoria {fora}  (Over combinado)")
print()

# Barras de probabilidade
print(f"  {'':>8}  {'Mexico':^22}  {'Africa do Sul':^22}")
print(f"  {'Vitoria':>8}  {barra(prob['vitoria_casa'],22)}  {prob['vitoria_casa']:>3}%")
print(f"  {'Empate':>8}  {barra(prob['empate'],22)}  {prob['empate']:>3}%")
print(f"  {'Derrota':>8}  {barra(prob['vitoria_fora'],22)}  {prob['vitoria_fora']:>3}%")
print()

# Placares mais prováveis
print(f"  TOP 3 PLACARES MAIS PROVAVEIS (Poisson):")
for i, pl in enumerate(d["placares_provaveis"], 1):
    bar = barra(pl["probabilidade"], 16)
    print(f"  {i}. {pl['placar']:^6}  {bar}  {pl['probabilidade']:.1f}%")
print()

# ═════════════════════════════════════════════════════════════════════════════
# ODDS DE APOSTAS  (mock — API-Football não retorna pré-Copa 2026)
# ═════════════════════════════════════════════════════════════════════════════
sep()
print()
print(f"  \033[1m💰 ODDS DE APOSTAS\033[0m  \033[90m(simuladas — odds reais disponíveis dias antes do jogo)\033[0m")
sep2()
print(f"  {'Mercado':<20}  {'Entrada':<26}  {'Prob':>4}  {'Barra':<22}  {'Odd':>5}  Nivel")
sep2()

for mercado, entradas in ODDS.items():
    for e in entradas:
        pct = e["prob"]
        print(f"  {mercado:<20}  {e['label']:<26}  {pct:>3}%  {barra(pct):<22}  @{e['odd']:<4}  {nivel(pct)}")
    print()

# ═════════════════════════════════════════════════════════════════════════════
# ESTATÍSTICAS COMPARATIVAS
# ═════════════════════════════════════════════════════════════════════════════
sep()
print()
sc = d["stats_casa"]
sf = d["stats_fora"]
print(f"  \033[1m📊 ESTATISTICAS COMPARATIVAS\033[0m")
print(f"  {casa}: {sc['fonte']}   │   {fora}: {sf['fonte']}")
sep2()
print(f"  {'Mexico':>7}  {'─'*20}  {'Africa do Sul':<13}  Estatistica")
sep2()

pct_bar(sc["jogos"],               sf["jogos"],               "Jogos na Copa")
pct_bar(sc["vitorias"],            sf["vitorias"],            "Vitorias")
pct_bar(sc["empates"],             sf["empates"],             "Empates")
pct_bar(sc["derrotas"],            sf["derrotas"],            "Derrotas")
sep2()
pct_bar(sc["media_gols_marcados"], sf["media_gols_marcados"], "Media Gols Marcados / jogo")
pct_bar(sc["media_gols_sofridos"], sf["media_gols_sofridos"], "Media Gols Sofridos / jogo")
pct_bar(sc["clean_sheets"],        sf["clean_sheets"],        "Clean Sheets")
sep2()
pct_bar(sc["media_amarelos"],      sf["media_amarelos"],      "Media Amarelos / jogo")
pct_bar(sc["penaltis_total"],      sf["penaltis_total"],      "Penaltis Total")
print()

# Performance casa/fora — ignorada para Copa (campo neutro)
if sc.get("sede_neutra"):
    print(f"  \033[90m  ⚠ Split casa/fora omitido — Copa disputada em campo neutro (sede)\033[0m")
print()

# ═════════════════════════════════════════════════════════════════════════════
# BTTS / OVER-UNDER (forma recente)
# ═════════════════════════════════════════════════════════════════════════════
sep()
print()
print(f"  \033[1m🎯 TENDENCIAS (ultimos 5 jogos)\033[0m")
sep2()

def tend_row(label, vm, vf):
    bm = barra(vm or 0, 12) if vm is not None else "─" * 12
    bf = barra(vf or 0, 12) if vf is not None else "─" * 12
    sm = f"{vm}%" if vm is not None else "---"
    sf2 = f"{vf}%" if vf is not None else "---"
    print(f"  {label:<22}  Mexico: {sm:>4} {bm}   Africa Sul: {sf2:>4} {bf}")

tend_row("Ambas Marcam (BTTS)",  sc["btts_pct"],   sf["btts_pct"])
tend_row("Over 2.5 Gols",        sc["over25_pct"],  sf["over25_pct"])
tend_row("Under 2.5 Gols",       sc["under25_pct"], sf["under25_pct"])
print()

# ═════════════════════════════════════════════════════════════════════════════
# FORMA RECENTE
# ═════════════════════════════════════════════════════════════════════════════
sep()
print()
print(f"  \033[1m📈 FORMA RECENTE\033[0m")
sep2()

def imprimir_forma(nome, forma):
    letras = " ".join(resultado_cor(j["resultado"]) for j in forma)
    print(f"\n  {nome}  →  {letras}\n")
    for j in forma:
        pl = f"{j['placar_proprio']}-{j['placar_adversario']}" if j["placar_proprio"] is not None else "---"
        icone = "✔" if j["resultado"] == "W" else ("—" if j["resultado"] == "D" else "✘")
        print(f"  {icone} {j['data']}  vs {j['adversario']:<22}  {pl:^5}  [{j['resultado']}]  {j['competicao']}")

imprimir_forma(casa, d["forma_casa"])
imprimir_forma(fora, d["forma_fora"])

# ═════════════════════════════════════════════════════════════════════════════
# HISTORICO H2H
# ═════════════════════════════════════════════════════════════════════════════
sep()
print()
h2h = d["head_to_head"]
print(f"  \033[1m🤝 HISTORICO DE CONFRONTOS (H2H)\033[0m")
sep2()

if h2h:
    mx_v  = sum(1 for h in h2h if (h["vencedor"] == casa or (h["casa"] == casa and h["vencedor"] == casa) or (h["fora"] == casa and h["vencedor"] == casa)))
    sa_v  = sum(1 for h in h2h if h["vencedor"] == fora or (h["casa"] == fora and h["vencedor"] == fora) or (h["fora"] == fora and h["vencedor"] == fora))
    emp   = sum(1 for h in h2h if h["vencedor"] == "empate")
    print(f"\n  {casa} {mx_v}V  ─  Empates {emp}  ─  {sa_v}V {fora}\n")
    for h in h2h:
        gols = f"{h['gols_casa']} x {h['gols_fora']}"
        print(f"  {h['data']}  {h['casa']:<22}  {gols:^7}  {h['fora']:<22}  [{h['competicao']}]")
else:
    print("\n  Sem confrontos anteriores registrados na API.\n")

# ═════════════════════════════════════════════════════════════════════════════
# ARBITRO
# ═════════════════════════════════════════════════════════════════════════════
sep()
print()
print(f"  \033[1m🟨 ARBITRO\033[0m")
sep2()
arb = d.get("arbitro")
if arb:
    print(f"  Nome             :  {arb['nome']}")
    print(f"  Jogos apitados   :  {arb['jogos_apitados'] or '---'}")
    print(f"  Media amarelos   :  {arb['media_amarelos'] or '---'}")
    print(f"  Media penaltis   :  {arb['media_penaltis'] or '---'}")
else:
    print("  Arbitro ainda nao definido pela FIFA.")
print()

# ═════════════════════════════════════════════════════════════════════════════
# RODAPE
# ═════════════════════════════════════════════════════════════════════════════
sep()
print(f"  \033[90mhttps://palpitesdaia.lovable.app/partida/{SLUG}\033[0m")
print(f"  \033[90mDados: API-Football v3 + seed Copa 2026  │  Odds: simuladas\033[0m")
sep()
print()
