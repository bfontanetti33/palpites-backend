"""
Testa as 4 camadas estatísticas sem chamar o Claude.
Mostra todos os scores intermediários em JSON.
"""
import asyncio, json, sys, os, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.agents import football_agent as fa
from app.agents.ia_agent import (
    _calcular_rating, _calcular_modelo_gols,
    _calcular_value_bets, _calcular_contexto,
    _calcular_tail_risk, _score_final,
)

async def main():
    # Carrega a partida via agente de futebol
    print("Carregando partida mexico-south-africa...")
    partida = await fa.buscar_detalhe_partida("mexico-south-africa")
    if not partida:
        print("Partida nao encontrada.")
        return
    print(f"Partida carregada: {partida.time_casa_nome} x {partida.time_fora_nome}")
    print(f"  Odds da API: {partida.odds}")
    print(f"  Forma casa ({len(partida.forma_casa)} jogos), fora ({len(partida.forma_fora)} jogos)")

    # Camada 1 — Ratings
    print("\n[CAMADA 1] Calculando ratings...")
    rating_c, rating_f = await asyncio.gather(
        _calcular_rating(partida.time_casa_nome, partida.forma_casa, partida.horario),
        _calcular_rating(partida.time_fora_nome, partida.forma_fora, partida.horario),
    )

    # Camada 2 — Modelo de Gols
    print("[CAMADA 2] Calculando Dixon-Coles + Skellam...")
    modelo = _calcular_modelo_gols(
        rating_c, rating_f,
        partida.stats_casa, partida.stats_fora,
        partida.forma_casa, partida.forma_fora,
    )

    # Camada 3 — Value Bets
    print("[CAMADA 3] Verificando odds e value bets...")
    odds_disp, value_bets = _calcular_value_bets(modelo, partida.odds)

    # Camada 4 — Contexto
    print("[CAMADA 4] Calculando contexto...")
    ctx, modelo_c4 = _calcular_contexto(partida, rating_c, rating_f, modelo)

    # Camada 4B — Tail Risk
    print("[CAMADA 4B] Tail Risk Engine (Fat Tail + Fragility + Uncertainty + Barbell)...")
    tail_risk, modelo_final = _calcular_tail_risk(
        modelo_c4, partida, rating_c, rating_f, ctx, odds_disp, value_bets
    )

    # Score Final
    top3 = _score_final(modelo_final, odds_disp, value_bets, ctx, partida.odds)

    # Comparativo antes/depois das correções
    comparativo = {
        "DC_puro (Camada 2)": {
            "vitoria_casa": modelo.prob_vitoria_casa,
            "empate":       modelo.prob_empate,
            "vitoria_fora": modelo.prob_vitoria_fora,
            "over25":       modelo.prob_over25,
            "over35":       modelo.prob_over35,
        },
        "Apos_Contexto (Camada 4)": {
            "vitoria_casa": modelo_c4.prob_vitoria_casa,
            "empate":       modelo_c4.prob_empate,
            "vitoria_fora": modelo_c4.prob_vitoria_fora,
            "over25":       modelo_c4.prob_over25,
            "over35":       modelo_c4.prob_over35,
        },
        "Apos_TailRisk (Camada 4B — FINAL)": {
            "vitoria_casa": modelo_final.prob_vitoria_casa,
            "empate":       modelo_final.prob_empate,
            "vitoria_fora": modelo_final.prob_vitoria_fora,
            "over25":       modelo_final.prob_over25,
            "over35":       modelo_final.prob_over35,
        },
        "fat_tail_deltas": tail_risk.fat_tail_delta,
    }

    # Output JSON completo
    resultado = {
        "partida": {
            "id": partida.id,
            "slug": partida.slug,
            "rodada": partida.rodada,
            "horario": partida.horario,
            "estadio": partida.estadio,
            "time_casa": partida.time_casa_nome,
            "time_fora": partida.time_fora_nome,
        },
        "camada_1_ratings": {
            partida.time_casa_nome: rating_c.model_dump(),
            partida.time_fora_nome: rating_f.model_dump(),
        },
        "camada_2_modelo_gols_bruto": modelo.model_dump(),
        "camada_3_value_bets": {
            "odds_disponiveis": odds_disp,
            "motivo": "odds reais da API presentes" if odds_disp else "odds nao disponíveis na API para este jogo (Copa 2026 futura)",
            "value_bets": value_bets,
        },
        "camada_4_contexto": ctx.model_dump(),
        "camada_4b_tail_risk": tail_risk.model_dump(),
        "comparativo_probabilidades": comparativo,
        "camada_2_modelo_gols_final": modelo_final.model_dump(),
        "score_final_top3": [m.model_dump() for m in top3],
        "camada_5_claude": "PENDENTE — conta Anthropic sem crédito (adicionar créditos em console.anthropic.com)",
    }

    print("\n" + "=" * 70)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))

asyncio.run(main())
