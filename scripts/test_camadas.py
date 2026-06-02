"""
Testa todas as camadas estatísticas (sem Claude).
Mostra scores intermediários em JSON.
"""
import asyncio, json, sys, os, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

from app.agents import football_agent as fa
from app.agents.ia_agent import (
    _buscar_fifa_ranking_wikipedia, _calcular_rating,
    _calcular_modelo_gols, _calcular_value_bets,
    _calcular_contexto, _calcular_tail_risk, _score_final,
    _COPA_FIFA_RANK, _STATS_REGIONAIS,
)


async def main():
    print("Carregando partida mexico-south-africa...")
    partida = await fa.buscar_detalhe_partida("mexico-south-africa")
    if not partida:
        print("Partida nao encontrada."); return
    print(f"  {partida.time_casa_nome} x {partida.time_fora_nome}")
    print(f"  Odds API: {partida.odds}")

    print("\n[CAMADA 1] Ratings (Elo + Pi + FIFA + Regional)...")
    wiki = await _buscar_fifa_ranking_wikipedia()
    print(f"  Wikipedia: {len(wiki)} times encontrados")

    rating_c, rating_f = await asyncio.gather(
        _calcular_rating(partida.time_casa_nome, partida.forma_casa, partida.horario, wiki),
        _calcular_rating(partida.time_fora_nome, partida.forma_fora, partida.horario, wiki),
    )

    print("\n[CAMADA 2] Dixon-Coles + Skellam...")
    modelo = _calcular_modelo_gols(
        rating_c, rating_f,
        partida.stats_casa, partida.stats_fora,
        partida.forma_casa, partida.forma_fora,
    )

    print("[CAMADA 3] Value bets...")
    odds_disp, value_bets = _calcular_value_bets(modelo, partida.odds)

    print("[CAMADA 4] Contexto...")
    ctx, modelo_c4 = _calcular_contexto(partida, rating_c, rating_f, modelo)

    print("[CAMADA 4B] Tail Risk...")
    tail_risk, modelo_final = _calcular_tail_risk(
        modelo_c4, partida, rating_c, rating_f, ctx, odds_disp, value_bets
    )

    top3 = _score_final(modelo_final, odds_disp, value_bets, ctx, partida.odds)

    # Stats regionais
    print("\n[INFO] Stats regionais (Elo na Copa):")
    for conf, stats in _STATS_REGIONAIS.items():
        print(f"  {conf}: média={stats['media']} std={stats['std']} n={stats['n']}")

    resultado = {
        "partida": {
            "slug": partida.slug, "rodada": partida.rodada,
            "horario": partida.horario, "estadio": partida.estadio,
            "odds_reais": partida.odds,
        },
        "camada_1_ratings": {
            partida.time_casa_nome: rating_c.model_dump(),
            partida.time_fora_nome: rating_f.model_dump(),
        },
        "camada_2_modelo_gols_bruto": {
            "lambda_casa": modelo.lambda_casa, "lambda_fora": modelo.lambda_fora,
            "vitoria_casa": modelo.prob_vitoria_casa, "empate": modelo.prob_empate,
            "vitoria_fora": modelo.prob_vitoria_fora,
            "over25": modelo.prob_over25, "btts": modelo.prob_btts,
        },
        "camada_3": {
            "odds_disponiveis": odds_disp,
            "value_bets": value_bets,
        },
        "camada_4_contexto": ctx.model_dump(),
        "camada_4b_tail_risk": tail_risk.model_dump(),
        "camada_2_modelo_final": {
            "lambda_casa": modelo_final.lambda_casa, "lambda_fora": modelo_final.lambda_fora,
            "vitoria_casa": modelo_final.prob_vitoria_casa, "empate": modelo_final.prob_empate,
            "vitoria_fora": modelo_final.prob_vitoria_fora,
            "over25": modelo_final.prob_over25, "btts": modelo_final.prob_btts,
            "skellam_vitoria": modelo_final.skellam_vitoria,
            "top5": modelo_final.top5_placares,
        },
        "score_final_top3": [m.model_dump() for m in top3],
        "camada_5_claude": "PENDENTE (crédito Anthropic necessário)",
    }

    print("\n" + "=" * 70)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


asyncio.run(main())
