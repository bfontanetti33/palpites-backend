"""
scripts/testar_narrativa.py — Preview da narrativa de produção (5 campos).

Gera a análise de UM jogo com o _SYSTEM de produção do ia_agent.py.
Não toca em produção. Usa dados reais do cache local — zero chamadas à API-Football.

Uso:
  py scripts/testar_narrativa.py                     # brazil-morocco (default)
  py scripts/testar_narrativa.py netherlands-japan
  py scripts/testar_narrativa.py --model haiku        # mais rápido/barato
"""
import json
import math
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

import anthropic

# ── Config ────────────────────────────────────────────────────────────────────
SLUG    = next((a for a in sys.argv[1:] if not a.startswith("--")), "brazil-morocco")
MODEL_S = next((sys.argv[i+1] for i, a in enumerate(sys.argv) if a == "--model"), "sonnet")
MODEL_MAP = {
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",
    "opus":   "claude-opus-4-8",
}
MODEL   = MODEL_MAP.get(MODEL_S, MODEL_S)
MAX_TOK = 1200
SEP     = "─" * 90


# ── DC helper (para calcular over/under quando não está no cache) ─────────────

def _pois(lam, k):
    return (lam ** k) * math.exp(-lam) / math.factorial(k)

def _prob_over(lam_c, lam_f, linha=2.5):
    total = 0.0
    for i in range(12):
        for j in range(12):
            if i + j > linha:
                total += _pois(lam_c, i) * _pois(lam_f, j)
    return round(total * 100)

def _prob_btts(lam_c, lam_f):
    p_c_zero = _pois(lam_c, 0)
    p_f_zero = _pois(lam_f, 0)
    return round((1 - p_c_zero) * (1 - p_f_zero) * 100)


# ── Estatísticas de forma ─────────────────────────────────────────────────────

def _stats_forma(jogos: list[dict]) -> dict:
    """Extrai sequências e totais dos últimos jogos de forma."""
    if not jogos:
        return {}
    ultimos5 = jogos[:5]
    resultados = [j.get("resultado", "?") for j in ultimos5]
    gols_marc  = [j.get("placar_proprio",  j.get("gols_marcados", 0))  for j in ultimos5]
    gols_sofr  = [j.get("placar_adversario", j.get("gols_sofridos", 0)) for j in ultimos5]

    # Sequência invicto (sem derrota desde o início da lista)
    invicto = 0
    for j in jogos:
        if j.get("resultado") in ("W", "V", "D", "E"):
            invicto += 1
        else:
            break

    # Sequência sem sofrer gol (clean sheets consecutivos)
    clean = 0
    for j in jogos:
        if (j.get("placar_adversario") or j.get("gols_sofridos") or 0) == 0:
            clean += 1
        else:
            break

    # Sequência marcando
    marcando = 0
    for j in jogos:
        if (j.get("placar_proprio") or j.get("gols_marcados") or 0) > 0:
            marcando += 1
        else:
            break

    return {
        "ultimos5":     " ".join(resultados),
        "gols_marc5":   sum(gols_marc),
        "gols_sofr5":   sum(gols_sofr),
        "invicto":      invicto,
        "clean_streak": clean,
        "marcando":     marcando,
        "ultimo_adv":   jogos[0].get("adversario", ""),
        "ultimo_res":   f"{jogos[0].get('placar_proprio',0)}-{jogos[0].get('placar_adversario',0)}",
    }


def _forma_str(stats: dict, nome: str) -> str:
    """Monta string legível de forma para o prompt."""
    if not stats:
        return f"{nome}: sem dados de forma"
    partes = [f"Últimos 5: {stats['ultimos5']}",
              f"marcou {stats['gols_marc5']} gols e sofreu {stats['gols_sofr5']}"]
    curiosidades = []
    if stats["invicto"] >= 4:
        curiosidades.append(f"invicto há {stats['invicto']} jogos")
    if stats["clean_streak"] >= 3:
        curiosidades.append(f"não sofreu gol em {stats['clean_streak']} jogos seguidos")
    if stats["marcando"] >= 5:
        curiosidades.append(f"marcou em todos os últimos {stats['marcando']} jogos")
    if curiosidades:
        partes.append("🔥 DESTAQUE: " + " | ".join(curiosidades))
    return f"{nome}: " + " | ".join(partes)


# ── Formato de jogadores para o prompt ───────────────────────────────────────

def _jogadores_str(jd: dict | None, time_nome: str) -> str:
    """
    Formata os jogadores destaque para o prompt.
    Usa SOMENTE campos com 100% de cobertura:
      nome, clube, caps, categoria, stat_label, stat_total, minutos_jogados, mercado_sugerido
    Usa condicionalmente (31% cobertura): stat_p90, liga_nome
    NUNCA cita: odd_mercado (sempre null), títulos, troféus (não existem no schema).
    """
    if not jd:
        return f"{time_nome}: sem dados de jogadores"
    jogadores = jd.get("jogadores", [])[:3]  # top 3
    if not jogadores:
        return f"{time_nome}: sem jogadores destacados"
    linhas = [f"{time_nome} — DESTAQUES:"]
    for j in jogadores:
        nome     = j.get("nome", "")
        clube    = j.get("clube", "")
        caps     = j.get("caps")
        cat      = j.get("categoria", "")        # goleadores / assistentes
        slabel   = j.get("stat_label", "")       # "gols/90" ou "assists/90"
        stotal   = j.get("stat_total", 0)
        minutos  = j.get("minutos_jogados", 0)
        mercado  = j.get("mercado_sugerido", "")
        sp90     = j.get("stat_p90")             # pode ser null (31%)
        lig      = j.get("liga_nome", "")

        stat_str = (
            f"{sp90:.2f} {slabel} ({stotal} total em {minutos} min)"
            if sp90 else
            f"{stotal} {slabel.replace('/90','s')} em {minutos} min"
        )
        caps_str = f" | {caps} jogos pela seleção" if caps else ""
        lig_str  = f" [{lig}]" if lig and sp90 else ""
        linhas.append(
            f"  • {nome} ({clube}){caps_str}: {stat_str}{lig_str}"
            + (f" → mercado: '{mercado}'" if mercado else "")
        )
    return "\n".join(linhas)


# ── Monta o prompt do usuário (IGUAL para A, B e C) ──────────────────────────

def build_prompt(slug: str) -> tuple[str, dict]:
    """Retorna (prompt_str, context_summary) a partir do cache."""
    cache = json.load(open(ROOT / "seeds" / "cache_partidas.json", encoding="utf-8"))
    entry = cache.get(slug, {})
    pj    = entry.get("partida") or entry
    if not pj:
        raise ValueError(f"Slug '{slug}' não encontrado no cache. Rode o prewarm primeiro.")

    nome_c = pj.get("time_casa_nome", "Casa")
    nome_f = pj.get("time_fora_nome", "Fora")
    prob   = pj.get("probabilidades") or {}
    odds   = pj.get("odds") or {}
    h2h    = pj.get("head_to_head") or []

    # Probabilidades — o cache pode ter 'vitoria_casa' (int) ou 'prob_vitoria_casa' (float)
    vc  = prob.get("prob_vitoria_casa") or prob.get("vitoria_casa") or 0
    vf  = prob.get("prob_vitoria_fora") or prob.get("vitoria_fora") or 0
    emp = prob.get("prob_empate")       or prob.get("empate")       or 0
    lc  = prob.get("lambda_casa", 1.2)
    lf  = prob.get("lambda_fora", 1.2)

    # Over/under calculados frescos se não estiver no cache
    over15 = prob.get("prob_over15") or _prob_over(lc, lf, 1.5)
    over25 = prob.get("prob_over25") or _prob_over(lc, lf, 2.5)
    btts   = prob.get("prob_btts")   or _prob_btts(lc, lf)

    # Favorito
    if vc > vf + 10:
        fav_txt = f"{nome_c} favorito ({vc:.0f}% vitória)"
    elif vf > vc + 10:
        fav_txt = f"{nome_f} favorito ({vf:.0f}% vitória)"
    else:
        fav_txt = f"Jogo equilibrado — {nome_c} {vc:.0f}% / Empate {emp:.0f}% / {nome_f} {vf:.0f}%"

    # Top placares
    top_placares = prob.get("top5_placares") or []
    placar_str = ""
    if top_placares:
        p0 = top_placares[0]
        placar_str = f"Placar mais provável: {p0.get('placar','?')} ({p0.get('prob',0):.1f}%)"

    # Odds de mercado
    oc  = odds.get("vitoria_casa")
    oe  = odds.get("empate")
    of_ = odds.get("vitoria_fora")
    if oc and oe and of_:
        odds_txt = (f"Odds de mercado (Pinnacle): {nome_c} {oc:.2f} | "
                    f"Empate {oe:.2f} | {nome_f} {of_:.2f}")
    else:
        odds_txt = "⚠️ Odds não disponíveis — consulte as casas antes de apostar"

    # Forma
    fc = _stats_forma(pj.get("forma_casa") or [])
    ff = _stats_forma(pj.get("forma_fora")  or [])
    forma_c = _forma_str(fc, nome_c)
    forma_f = _forma_str(ff, nome_f)

    # H2H
    h2h_txt = (f"{len(h2h)} confronto(s) direto(s) registrado(s)"
               if h2h else "Sem histórico de confrontos diretos")

    # Jogadores
    jd_c = _jogadores_str(pj.get("jogadores_destaque_casa"), nome_c)
    jd_f = _jogadores_str(pj.get("jogadores_destaque_fora"), nome_f)

    # Contexto
    ctx = pj.get("contexto") or {}
    contexto_items = []
    if ctx.get("home_advantage"):
        contexto_items.append(f"{ctx.get('home_advantage_time','?')} joga em casa (sede da Copa)")
    if ctx.get("primeira_rodada"):
        contexto_items.append("1ª rodada — times costumam ser mais cautelosos")
    if ctx.get("fadiga_casa"):
        contexto_items.append(f"{nome_c} pode estar cansado (jogo nos últimos 4 dias)")
    if ctx.get("fadiga_fora"):
        contexto_items.append(f"{nome_f} pode estar cansado (jogo nos últimos 4 dias)")
    if not contexto_items:
        contexto_items.append("1ª rodada da Copa — primeiro teste de cada seleção")
    contexto_str = "\n".join(f"  • {x}" for x in contexto_items)

    # Zebra
    zebra = ""
    if ctx.get("zebra_alerta"):
        zebra = f"\n🚨 ALERTA DE ZEBRA: {ctx.get('zebra_descricao','')}\n"

    prompt = f"""Escreva a análise dessa partida da Copa 2026 para um apostador brasileiro.

JOGO: {nome_c} x {nome_f}
{pj.get('rodada','')} | {pj.get('estadio','')} | {(pj.get('horario') or '')[:10]}

--- FAVORITO E PROBABILIDADES ---
{fav_txt}
{nome_c}: {vc:.0f}% vitória | Empate: {emp:.0f}% | {nome_f}: {vf:.0f}%
{placar_str}

--- GOLS E MERCADOS ---
Gols esperados: {lc:.1f} ({nome_c}) e {lf:.1f} ({nome_f})
Over 1.5 gols: {over15:.0f}% | Over 2.5 gols: {over25:.0f}%
Ambos marcam (BTTS): {btts:.0f}%

{odds_txt}

--- FORMA RECENTE ---
{forma_c}
{forma_f}
Histórico: {h2h_txt}

--- FATORES DO JOGO ---
{contexto_str}{zebra}
--- JOGADORES DESTAQUE ---
{jd_c}

{jd_f}
"""

    summary = {
        "jogo": f"{nome_c} x {nome_f}",
        "favorito": fav_txt,
        "vc": vc, "emp": emp, "vf": vf,
        "lc": lc, "lf": lf,
        "over15": over15, "over25": over25, "btts": btts,
        "odds": (oc, oe, of_),
        "forma_c_inv": fc.get("invicto", 0),
        "forma_f_clean": ff.get("clean_streak", 0),
    }
    return prompt, summary


# ── _SYSTEM de produção (espelho de ia_agent._SYSTEM) ────────────────────────

from app.agents.ia_agent import _SYSTEM as _SYSTEM_PROD


# ── Parser (5 campos) ─────────────────────────────────────────────────────────

def parse_campos(texto: str) -> dict:
    campos = {
        "NARRATIVA": "", "RESUMO_RAPIDO": "", "ALERTAS": "",
        "ANALISE_COMPLETA": "", "INSIGHT_JOGADORES": "",
    }
    ordem  = list(campos.keys())
    linhas = texto.splitlines()
    atual  = None
    buf: list[str] = []
    for linha in linhas:
        achado = next((c for c in ordem if linha.startswith(f"{c}:")), None)
        if achado:
            if atual:
                campos[atual] = " ".join(buf).strip()
            atual = achado
            buf = [linha[len(achado)+1:].strip()]
        elif atual:
            buf.append(linha.strip())
    if atual:
        campos[atual] = " ".join(buf).strip()
    return campos


# ── Runner ────────────────────────────────────────────────────────────────────

def chamar_claude(system: str, prompt: str) -> tuple[dict, str]:
    print(f"  → chamando Claude ({MODEL})...", end=" ", flush=True)
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOK,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text
    print("OK")
    return parse_campos(raw), raw


def imprimir_resultado(campos: dict, raw: str) -> None:
    print(f"\n{'═'*90}")
    print("  RESULTADO — SISTEMA DE PRODUÇÃO (5 campos)")
    print(f"{'═'*90}")
    for campo, valor in campos.items():
        print(f"\n  ┌─ {campo}")
        # Quebra em linhas de 85 chars para legibilidade
        texto = valor or "(vazio)"
        fatias = [texto[i:i+85] for i in range(0, len(texto), 85)]
        for fatia in fatias:
            print(f"  │  {fatia}")
    print(f"\n  ({len(raw.split())} palavras / {len(raw)} chars)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print(SEP)
    print(f"  testar_narrativa.py — {SLUG} — modelo: {MODEL}")
    print(SEP)

    try:
        prompt, ctx = build_prompt(SLUG)
    except ValueError as e:
        print(f"\nERRO: {e}")
        return

    print(f"\n  JOGO: {ctx['jogo']}")
    print(f"  FAVORITO: {ctx['favorito']}")
    print(f"  PROBS: casa={ctx['vc']:.0f}% empt={ctx['emp']:.0f}% fora={ctx['vf']:.0f}%")
    print(f"  LAMBDAS: lc={ctx['lc']:.2f} lf={ctx['lf']:.2f}")
    print(f"  MERCADOS: Over1.5={ctx['over15']}% Over2.5={ctx['over25']}% BTTS={ctx['btts']}%")
    oc, oe, of_ = ctx["odds"]
    if oc:
        print(f"  ODDS MERCADO: casa={oc:.2f} empate={oe:.2f} fora={of_:.2f}")
    print(f"  FORMA: casa invicto={ctx['forma_c_inv']}j | fora clean_streak={ctx['forma_f_clean']}j")

    campos, raw = chamar_claude(_SYSTEM_PROD, prompt)
    imprimir_resultado(campos, raw)

    print(f"\n{SEP}")
    print("  FIM — revise os 5 campos. Nada foi alterado em produção.")
    print(SEP)


if __name__ == "__main__":
    main()
