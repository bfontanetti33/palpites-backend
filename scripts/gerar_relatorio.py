"""
Gera a matriz completa de placares (Poisson puro vs Dixon-Coles)
para incluir no relatório técnico.
"""
import asyncio, sys, os, math
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

from app.agents.ia_agent import _poisson, _tau, _dc_matrix, _fat_tail_matrix, _probs_do_matrix

LAM = 1.330
MU  = 1.379
DC_RHO = -0.1

def poisson_puro(lam, mu, max_goals=6):
    raw = {}
    for i in range(max_goals):
        for j in range(max_goals):
            raw[f"{i}-{j}"] = _poisson(lam, i) * _poisson(mu, j)
    total = sum(raw.values())
    return {k: round(v/total*100, 2) for k, v in raw.items()}

puro = poisson_puro(LAM, MU)
dc   = _dc_matrix(LAM, MU)

# Top 10 de cada
top10_puro = sorted(puro.items(), key=lambda x: -x[1])[:10]
top10_dc   = sorted(dc.items(),   key=lambda x: -x[1])[:10]

# Comparativo dos baixos scores
baixos = ["0-0", "0-1", "1-0", "1-1"]

print("=== TOP 10 POISSON PURO ===")
for k, v in top10_puro:
    print(f"  {k}: {v}%")

print("\n=== TOP 10 DIXON-COLES ===")
for k, v in top10_dc:
    print(f"  {k}: {v}%")

print("\n=== COMPARATIVO SCORES BAIXOS (DC vs Poisson) ===")
for k in baixos:
    delta = round(dc[k] - puro[k], 2)
    sinal = "+" if delta >= 0 else ""
    print(f"  {k}: Poisson={puro[k]}%  DC={dc[k]}%  delta={sinal}{delta}pp  fator_tau={round(dc[k]/puro[k],3)}")

print("\n=== DELTAS FAT TAIL ===")
ft = _fat_tail_matrix(dc, LAM, MU)
probs_dc = _probs_do_matrix(dc)
probs_ft = _probs_do_matrix(ft)
for key in ["vitoria_casa","empate","vitoria_fora","over15","over25","over35","btts"]:
    d = round(probs_ft[key] - probs_dc[key], 2)
    print(f"  {key}: DC={probs_dc[key]}%  FT={probs_ft[key]}%  delta={'+' if d>=0 else ''}{d}pp")

print("\n=== TAU CORRECTION VALUES ===")
for i,j in [(0,0),(0,1),(1,0),(1,1)]:
    t = 1 - LAM*MU*DC_RHO if i==0 and j==0 else \
        1 + LAM*DC_RHO if i==0 and j==1 else \
        1 + MU*DC_RHO  if i==1 and j==0 else \
        1 - DC_RHO
    print(f"  tau({i},{j}) = {round(t,4)}")
