"""Teste rápido do odds_engine."""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from app.agents.odds_engine import shin_probabilities, processar_odds, calcular_z_score

# Shin
probs = shin_probabilities([1.55, 4.00, 6.50])
impl  = [1/1.55, 1/4.00, 1/6.50]
print(f"Shin [1.55, 4.00, 6.50]: {[round(p,4) for p in probs]} | soma={sum(probs):.6f}")
assert abs(sum(probs) - 1.0) < 0.001, "soma != 1"
assert all(ps < pi for ps, pi in zip(probs, impl)), "probs nao sao < implied"
print("Shin OK: soma=1 e probs < implied")

# z-score
z = calcular_z_score(0.60, 0.50, 10)
print(f"z_score(0.60, 0.50, n=10) = {z:.4f}  (esperado ~0.6325)")
z2 = calcular_z_score(0.51, 0.50, 5)
print(f"z_score(0.51, 0.50, n=5)  = {z2:.4f}  (esperado ~0.0447)")
assert z > z2, "z1 deve ser > z2"
print("z_score OK")

# processar_odds sem odds
r = processar_odds(None, {})
assert not r["odds_disponiveis"]
print("processar_odds(None) OK")

# processar_odds com 2 bookmakers
odds_mock = {
    "bookmaker": "pinnacle",
    "vitoria_casa": 1.55, "empate": 4.00, "vitoria_fora": 6.50,
    "bookmakers_h2h": [
        {"key": "pinnacle", "home": 1.55, "draw": 4.00, "away": 6.50},
        {"key": "bet365",   "home": 1.52, "draw": 4.10, "away": 6.80},
    ]
}
prob_mod = {
    "vitoria_casa": 0.65, "empate": 0.20, "vitoria_fora": 0.15,
    "btts": 0.45, "over15": 0.80, "under15": 0.20,
    "over25": 0.52, "under25": 0.48, "over35": 0.22, "under35": 0.78,
}
r2 = processar_odds(odds_mock, prob_mod)
print(f"\nprocessar_odds com 2 bookmakers:")
print(f"  odds_disponiveis: {r2['odds_disponiveis']}")
print(f"  n_casas:          {r2['n_casas']}")
print(f"  margem_media:     {r2['margem_media']}")
cons = r2["consensus"]
print(f"  consensus:        home={cons['home']:.4f} draw={cons['draw']:.4f} away={cons['away']:.4f}")
print(f"  fair_odds:        {r2['fair_odds']}")
print(f"  divergencia home: {r2['divergencia']['home']}")
print(f"  divergencia draw: {r2['divergencia']['draw']}")
print(f"  divergencia away: {r2['divergencia']['away']}")
print(f"  value_bets:       {r2['value_bets']}")
print(f"  sharp_money:      {r2['sharp_money']}")

assert r2["odds_disponiveis"]
assert r2["n_casas"] == 2
assert abs(cons["home"] + cons["draw"] + cons["away"] - 1.0) < 0.01

print("\nTodos os testes passaram!")
