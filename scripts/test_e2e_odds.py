"""Teste end-to-end: mexico-south-africa + odds_engine."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.agents.football_agent import buscar_detalhe_partida
from app.agents.odds_engine import processar_odds


async def main():
    p = await buscar_detalhe_partida("mexico-south-africa")
    print(f"Partida: {p.time_casa_nome} x {p.time_fora_nome}")

    if p.odds:
        bms = p.odds.get("bookmakers_h2h", [])
        print(f"Bookmakers h2h disponíveis: {len(bms)}")
        for bm in bms[:5]:
            print(f"  {bm['key']}: home={bm['home']} draw={bm['draw']} away={bm['away']}")
    else:
        print("AVISO: sem odds — odds_engine retornará odds_disponiveis=False")

    prob_mod = {
        "vitoria_casa": p.probabilidades.vitoria_casa / 100 if p.probabilidades else 0.47,
        "empate":       p.probabilidades.empate       / 100 if p.probabilidades else 0.25,
        "vitoria_fora": p.probabilidades.vitoria_fora / 100 if p.probabilidades else 0.29,
        "btts": 0.45, "over15": 0.80, "under15": 0.20,
        "over25": 0.52, "under25": 0.48, "over35": 0.22, "under35": 0.78,
    }

    r = processar_odds(p.odds, prob_mod)

    print(f"\nodds_disponiveis : {r['odds_disponiveis']}")
    print(f"n_casas          : {r['n_casas']}")
    print(f"margem_media     : {r['margem_media']}")

    if r["odds_disponiveis"]:
        c = r["consensus"]
        print(f"\nConsensus (Shin + mediana ponderada):")
        print(f"  home={c['home']:.4f}  draw={c['draw']:.4f}  away={c['away']:.4f}  sum={c['home']+c['draw']+c['away']:.4f}")
        print(f"\nFair Odds: {r['fair_odds']}")
        print(f"\nDivergência modelo vs consenso:")
        for res, d in r["divergencia"].items():
            print(f"  {res}: modelo={d['prob_modelo']:.3f}  consenso={d['prob_consenso']:.3f}  z={d['z_score']:.3f}  sig={d['significativo']}")
        print(f"\nValue Bets (z > 1.65):")
        if r["value_bets"]:
            for vb in r["value_bets"]:
                print(f"  {vb}")
        else:
            print("  Nenhum — divergência não é estatisticamente significativa com estas odds")
        print(f"\nSharp Money: {r['sharp_money']}")
    else:
        print("Odds não disponíveis — verifique Odds API")


if __name__ == "__main__":
    asyncio.run(main())
