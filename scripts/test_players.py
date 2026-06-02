"""
Testa o players_agent com México e África do Sul.
Mostra o squad completo e os jogadores de destaque com métricas P90.
"""
import asyncio, json, sys, os, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

from app.agents.players_agent import buscar_squad, buscar_jogadores_destaque


async def main():

    for team in ["Mexico", "South Africa"]:
        print(f"\n{'='*60}")
        print(f"  {team}")
        print('='*60)

        # Passo 1: squad
        print(f"\n[1] Squad da Wikipedia...")
        squad = await buscar_squad(team)
        print(f"    Total: {len(squad)} jogadores")
        if squad:
            for p in squad[:5]:
                print(f"    #{p['no']} {p['pos']} {p['nome']} ({p['clube']}) — {p['caps']} caps")
            if len(squad) > 5:
                print(f"    ... e mais {len(squad)-5} jogadores")
        else:
            print("    Nenhum jogador encontrado — verificar scraping")

        # Passos 2-4: destaques
        print(f"\n[2-4] Jogadores de destaque (P90 stats)...")
        dest = await buscar_jogadores_destaque(team)
        print(f"    Squad: {dest.get('total_squad',0)} jogadores")
        print(f"    Analisados: {dest.get('jogadores_analisados',0)}")
        print(f"    Fonte: {dest.get('fonte_squad','?')}")
        print(f"    Destaques encontrados: {len(dest.get('jogadores',[]))}")

        for j in dest.get("jogadores", []):
            status = "⚠️ insuf." if j.get("dados_insuficientes") else "✅"
            print(f"\n    {status} [{j['icone_categoria']}] {j['nome']} ({j['posicao']}, {j['clube']})")
            print(f"       {j['resumo']}")
            print(f"       Mercado: {j['mercado_sugerido']}")

    # JSON completo do México
    print(f"\n{'='*60}")
    print("JSON completo — México destaque:")
    dest_mx = await buscar_jogadores_destaque("Mexico")
    print(json.dumps(dest_mx, ensure_ascii=False, indent=2))


asyncio.run(main())
