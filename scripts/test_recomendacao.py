"""Testa o endpoint de recomendação premium e exibe o output da Camada 5."""
import json, sys, os, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

from app.main import app
from fastapi.testclient import TestClient

TOKEN  = os.getenv("PREMIUM_TOKEN", "")
client = TestClient(app, raise_server_exceptions=True)

print("Chamando /api/v1/copa/jogos/mexico-south-africa/recomendacao...")
r = client.get(
    "/api/v1/copa/jogos/mexico-south-africa/recomendacao",
    headers={"Authorization": f"Bearer {TOKEN}"},
)
print(f"Status: {r.status_code}\n")

if r.status_code != 200:
    print(f"Erro: {r.text[:500]}")
    sys.exit(1)

d = r.json()

sep = "=" * 65

# ── Camada 5 — Narrativa Claude ───────────────────────────────────
print(sep)
print("  CAMADA 5 — NARRATIVA (Claude)")
print(sep)

print(f"\n[NARRATIVA]\n{d.get('narrativa', '---')}\n")
print(f"[RESUMO RAPIDO]\n{d.get('resumo_rapido', '---')}\n")

alertas = d.get("alertas", [])
print(f"[ALERTAS]")
for a in alertas:
    print(f"  • {a}")
print()

print(f"[ANALISE COMPLETA]\n{d.get('analise_completa', '---')}\n")

# ── Top 3 mercados ────────────────────────────────────────────────
print(sep)
print("  TOP 3 MERCADOS RECOMENDADOS")
print(sep)
for i, m in enumerate(d.get("top3", []), 1):
    vs = m.get("value_score")
    vs_str = f"{vs:+.3f}" if vs is not None else "N/A (sem odds)"
    print(f"\n  {i}. [{m['confianca']}] {m['mercado']} — {m['entrada']}")
    print(f"     Prob DC: {m['prob_dc']}%  |  Value: {vs_str}")
    print(f"     Score final: {m['score_final']}/100")

# ── Contexto + Tail Risk ──────────────────────────────────────────
print(f"\n{sep}")
print("  SCORES INTERMEDIARIOS")
print(sep)
ctx = d.get("contexto", {})
tr  = d.get("tail_risk", {})
print(f"\n  Contexto:")
print(f"    campo_neutro:     {ctx.get('campo_neutro')}")
print(f"    home_advantage:   {ctx.get('home_advantage')} ({ctx.get('home_advantage_time','')})")
print(f"    primeira_rodada:  {ctx.get('primeira_rodada')}")
print(f"    confianca_h2h:    {ctx.get('confianca_h2h')}")
print(f"\n  Tail Risk (Taleb):")
print(f"    uncertainty_index:    {tr.get('uncertainty_index')}/100")
print(f"    achatamento:          {tr.get('probabilidades_achatadas')}")
print(f"    fragility_casa:       {tr.get('fragility_score_casa')}")
print(f"    fragility_fora:       {tr.get('fragility_score_fora')}")
print(f"    barbell_sugerido:     {tr.get('barbell_sugerido')}")
print(f"\n  Modelo final (após home advantage + tail risk):")
mg = d.get("modelo_gols", {})
print(f"    lambda casa: {mg.get('lambda_casa')}  |  lambda fora: {mg.get('lambda_fora')}")
print(f"    Mexico: {mg.get('prob_vitoria_casa')}%  Empate: {mg.get('prob_empate')}%  Africa Sul: {mg.get('prob_vitoria_fora')}%")
print(f"    Over 1.5: {mg.get('prob_over15')}%  Over 2.5: {mg.get('prob_over25')}%  BTTS: {mg.get('prob_btts')}%")
print(f"    Top placar: {mg.get('top5_placares',[{}])[0].get('placar','?')} ({mg.get('top5_placares',[{}])[0].get('prob','?')}%)")

print(f"\n{sep}")
