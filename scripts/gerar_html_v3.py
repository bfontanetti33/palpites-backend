"""
Gera seeds/test_mexico_southafrica_v3.html
Usa dados reais da API para calcular stats de temporada e home/away.
"""
import asyncio, sys, os, json, warnings
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); os.chdir(ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
warnings.filterwarnings("ignore")
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")

from app.agents import football_agent as fa


def stats_ultimos_n(forma, n=5):
    """Calcula stats dos últimos N jogos da forma recente."""
    ultimos = forma[-n:] if len(forma) >= n else forma
    wins = sum(1 for j in ultimos if j.resultado == "W")
    draws = sum(1 for j in ultimos if j.resultado == "D")
    losses = sum(1 for j in ultimos if j.resultado == "L")
    gols_m = sum((j.placar_proprio or 0) for j in ultimos)
    gols_s = sum((j.placar_adversario or 0) for j in ultimos)
    return {
        "jogos": len(ultimos), "vitorias": wins, "empates": draws,
        "derrotas": losses, "gols_marcados": gols_m, "gols_sofridos": gols_s,
        "media_gols_m": round(gols_m / len(ultimos), 1) if ultimos else 0,
        "media_gols_s": round(gols_s / len(ultimos), 1) if ultimos else 0,
    }


def stats_home_away(forma_raw, team_id):
    """
    Separa os jogos da forma recente em casa e fora usando dados brutos da API.
    Retorna {casa: {...}, fora: {...}}.
    """
    # forma_raw = lista de dicts crus da API (não EntradaForma)
    casa, fora = [], []
    for f in forma_raw:
        is_home = f["teams"]["home"]["id"] == team_id
        gols_pro    = f["goals"]["home"] if is_home else f["goals"]["away"]
        gols_contra = f["goals"]["away"] if is_home else f["goals"]["home"]
        adv  = f["teams"]["away"]["name"] if is_home else f["teams"]["home"]["name"]
        venc = f["teams"]["home"]["winner"] if is_home else f["teams"]["away"]["winner"]
        res  = "W" if venc is True else ("L" if venc is False else "D")
        game = {"adv": adv, "gols_pro": gols_pro or 0, "gols_contra": gols_contra or 0, "res": res}
        (casa if is_home else fora).append(game)

    def resumo(jogos):
        if not jogos:
            return {"jogos": 0, "vitorias": 0, "empates": 0, "derrotas": 0,
                    "gols_m": 0, "gols_s": 0, "media_gols_m": 0, "media_gols_s": 0}
        w = sum(1 for j in jogos if j["res"] == "W")
        d = sum(1 for j in jogos if j["res"] == "D")
        l = sum(1 for j in jogos if j["res"] == "L")
        gm = sum(j["gols_pro"] for j in jogos)
        gs = sum(j["gols_contra"] for j in jogos)
        n  = len(jogos)
        return {"jogos": n, "vitorias": w, "empates": d, "derrotas": l,
                "gols_m": gm, "gols_s": gs,
                "media_gols_m": round(gm/n, 1), "media_gols_s": round(gs/n, 1)}

    return {"casa": resumo(casa), "fora": resumo(fora)}


async def main():
    import httpx

    print("Buscando partida e forma recente...")
    partida = await fa.buscar_detalhe_partida("mexico-south-africa")
    if not partida:
        print("Partida não encontrada"); return

    MX_ID = partida.time_casa_id   # 16
    SA_ID = partida.time_fora_id   # 1531

    # Busca dados brutos da forma (com home/away info)
    async with httpx.AsyncClient(timeout=20) as client:
        raw_mx = await fa._get(client, "/fixtures", {"team": MX_ID, "last": 10})
        raw_sa = await fa._get(client, "/fixtures", {"team": SA_ID, "last": 10})

    forma_mx_raw = raw_mx.get("response", [])
    forma_sa_raw = raw_sa.get("response", [])

    # Stats dos últimos 5 jogos (para a seção de "temporada")
    st5_mx = stats_ultimos_n(partida.forma_casa, 5)
    st5_sa = stats_ultimos_n(partida.forma_fora, 5)

    # Home/away dos últimos 10
    ha_mx = stats_home_away(forma_mx_raw, MX_ID)
    ha_sa = stats_home_away(forma_sa_raw, SA_ID)

    print(f"México últimos 5: {st5_mx}")
    print(f"África do Sul últimos 5: {st5_sa}")
    print(f"México casa/fora: {ha_mx}")
    print(f"África do Sul casa/fora: {ha_sa}")

    # Forma raw para debug
    ultimos5_mx = partida.forma_casa[-5:]
    ultimos5_sa = partida.forma_fora[-5:]

    # Gera HTML
    html = gerar_html(partida, st5_mx, st5_sa, ha_mx, ha_sa, ultimos5_mx, ultimos5_sa)
    out = ROOT / "seeds" / "test_mexico_southafrica_v3.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nHTML salvo em: {out}")


def _badge(j):
    c = {"W": "#22c55e", "D": "#f59e0b", "L": "#ef4444"}.get(j.resultado, "#94a3b8")
    l = {"W": "V", "D": "E", "L": "D"}.get(j.resultado, "?")
    return f'<span style="display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:{c}22;color:{c};font-size:11px;font-weight:800;margin:1px">{l}</span>'


def gerar_html(p, st5_mx, st5_sa, ha_mx, ha_sa, f5_mx, f5_sa):
    def res_color(r):
        return {"W": "#22c55e", "D": "#f59e0b", "L": "#ef4444"}.get(r, "#94a3b8")

    def forma_badges(forma):
        badges = ""
        for j in forma:
            c = res_color(j.resultado)
            letra = "V" if j.resultado=="W" else ("E" if j.resultado=="D" else "D")
            badges += f'<span style="display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:{c}22;color:{c};font-size:11px;font-weight:800;margin:2px">{letra}</span>'
        return badges

    def forma_rows(forma):
        rows = ""
        for j in sorted(forma, key=lambda x: x.data):
            gc = res_color(j.resultado)
            pl = f"{j.placar_proprio}-{j.placar_adversario}" if j.placar_proprio is not None else "—"
            rows += f"""<div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid #2e3347;font-size:12px">
              <span style="color:#94a3b8;width:80px;flex-shrink:0">{j.data}</span>
              <span style="flex:1">vs {j.adversario}</span>
              <span style="font-weight:700;width:40px;text-align:center;color:{gc}">{pl}</span>
              <span style="color:#94a3b8;font-size:11px;text-align:right;width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{j.competicao}</span>
            </div>"""
        return rows

    mx_casa = ha_mx["casa"]
    mx_fora = ha_mx["fora"]
    sa_casa = ha_sa["casa"]
    sa_fora = ha_sa["fora"]

    h2h = p.head_to_head

    # Pre-compute complex HTML fragments outside the main f-string
    badges_mx = "".join(_badge(j) for j in sorted(f5_mx, key=lambda x: x.data))
    badges_sa = "".join(_badge(j) for j in sorted(f5_sa, key=lambda x: x.data))

    rows_mx = forma_rows(f5_mx)
    rows_sa = forma_rows(f5_sa)

    if h2h:
        h2h_rows = "".join(
            f'<div class="h2h-row">'
            f'<span style="color:var(--muted);font-size:11px;width:80px;flex-shrink:0">{h["data"]}</span>'
            f'<span style="flex:1">{h["casa"]} x {h["fora"]}</span>'
            f'<span style="font-weight:800;font-size:16px;color:#f59e0b;width:50px;text-align:center">{h["gols_casa"]} x {h["gols_fora"]}</span>'
            f'<span style="color:var(--muted);font-size:11px">{h["competicao"]}</span>'
            f'</div>'
            for h in h2h
        )
    else:
        h2h_rows = '<div style="text-align:center;color:var(--muted);padding:16px">Apenas 1 confronto (Copa 2010, 1x1)</div>'

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>México x África do Sul — Palpites da IA v3</title>
<style>
  :root{{--bg:#0f1117;--card:#1a1d27;--card2:#21253a;--border:#2e3347;--green:#22c55e;--amber:#f59e0b;--orange:#f97316;--red:#ef4444;--blue:#3b82f6;--text:#f1f5f9;--muted:#94a3b8;--accent:#6366f1}}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Inter','Segoe UI',sans-serif;font-size:15px;line-height:1.6}}
  nav{{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;background:#12151f;border-bottom:1px solid var(--border);position:sticky;top:0;z-index:100}}
  .logo{{font-weight:800;font-size:18px;color:var(--accent)}}
  .nav-tag{{background:var(--accent);color:#fff;font-size:11px;font-weight:700;padding:3px 10px;border-radius:99px}}
  .page{{max-width:900px;margin:0 auto;padding:24px 16px 64px}}
  .badge{{display:inline-flex;align-items:center;gap:6px;background:var(--card2);border:1px solid var(--border);border-radius:99px;padding:4px 12px;font-size:12px;font-weight:600;color:var(--muted);margin-bottom:20px}}
  .dot{{width:6px;height:6px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}}
  @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
  .match-header{{background:linear-gradient(135deg,#1a1d27 0%,#1e2235 100%);border:1px solid var(--border);border-radius:16px;padding:32px 24px 24px;margin-bottom:16px;text-align:center}}
  .league-label{{font-size:12px;font-weight:700;color:var(--accent);letter-spacing:1px;text-transform:uppercase;margin-bottom:24px}}
  .teams-row{{display:flex;align-items:center;justify-content:center;gap:24px;margin-bottom:20px}}
  .team-block{{display:flex;flex-direction:column;align-items:center;gap:10px;flex:1}}
  .team-logo{{width:72px;height:72px;border-radius:50%;background:#2a2d3e;padding:8px;object-fit:contain}}
  .team-name{{font-size:18px;font-weight:800}}
  .vs-pill{{background:var(--card2);border:1px solid var(--border);border-radius:99px;padding:8px 18px;font-size:13px;font-weight:700;color:var(--muted);flex-shrink:0}}
  .match-meta{{display:flex;flex-wrap:wrap;justify-content:center;gap:16px}}
  .meta-item{{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted)}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:24px;margin-bottom:16px}}
  .card-title{{font-size:13px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;margin-bottom:20px;display:flex;align-items:center;gap:8px}}
  .card-title::after{{content:'';flex:1;height:1px;background:var(--border)}}
  .source-line{{font-size:11px;color:#64748b;margin-top:6px;font-style:italic}}
  .missing{{color:var(--red);font-weight:700}}
  .grid2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
  .inner-card{{background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px}}
  .inner-title{{font-size:14px;font-weight:800;margin-bottom:12px}}
  .stat-row{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}
  .stat-label{{font-size:12px;color:var(--muted)}}
  .stat-value{{font-size:14px;font-weight:700}}
  .alerta-card{{display:flex;align-items:flex-start;gap:12px;border-radius:12px;padding:14px 16px;border:1px solid;margin-bottom:10px}}
  .alerta-card.amber{{background:#1c1a0f;border-color:#92400e}}
  .alerta-card.orange{{background:#1c140f;border-color:#9a3412}}
  .alerta-card.yellow{{background:#1a1c0f;border-color:#713f12}}
  .alerta-card.blue{{background:#0f1629;border-color:#1e3a5f}}
  .alerta-card.green{{background:#0f1a0f;border-color:#166534}}
  .alerta-icon{{font-size:18px;flex-shrink:0;margin-top:1px}}
  .alerta-title{{font-weight:700;font-size:13px;margin-bottom:2px}}
  .alerta-card.amber .alerta-title{{color:#fbbf24}}
  .alerta-card.orange .alerta-title{{color:#fb923c}}
  .alerta-card.yellow .alerta-title{{color:#fde68a}}
  .alerta-card.blue .alerta-title{{color:#60a5fa}}
  .alerta-card.green .alerta-title{{color:#4ade80}}
  .alerta-desc{{font-size:12px;color:var(--muted)}}
  .triplet{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:10px}}
  .tri-item{{background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:14px 10px;text-align:center}}
  .tri-item.best{{border-color:var(--accent);background:#1a1d3a}}
  .tri-label{{font-size:11px;color:var(--muted);margin-bottom:6px}}
  .tri-val{{font-size:24px;font-weight:900}}
  .tri-sub{{font-size:10px;color:var(--muted);margin-top:3px}}
  .prob-bar-bg{{height:8px;background:var(--card2);border-radius:99px;overflow:hidden;margin:6px 0}}
  .prob-bar{{height:100%;border-radius:99px}}
  .market-row{{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}}
  .market-pct{{font-size:18px;font-weight:800}}
  .conf{{font-size:10px;font-weight:700;padding:2px 7px;border-radius:99px;text-transform:uppercase}}
  .conf-alta{{background:#14532d;color:#4ade80}}
  .conf-media{{background:#451a03;color:#fb923c}}
  .conf-baixa{{background:#450a0a;color:#f87171}}
  .odds-box{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px}}
  .odds-item{{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:12px;text-align:center}}
  .odds-label{{font-size:11px;color:var(--muted);margin-bottom:4px}}
  .odds-val{{font-size:20px;font-weight:900}}
  .odds-impl{{font-size:10px;color:var(--muted);margin-top:2px}}
  .scores-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}}
  .score-item{{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:10px 6px;text-align:center}}
  .score-item.top{{border-color:var(--accent);background:#1a1d3a}}
  .score-placar{{font-size:17px;font-weight:800}}
  .score-item.top .score-placar{{color:var(--accent)}}
  .score-prob{{font-size:11px;color:var(--muted);margin-top:2px}}
  .h2h-summary{{display:flex;align-items:center;justify-content:center;margin-bottom:16px}}
  .h2h-stat{{text-align:center;flex:1}}
  .h2h-num{{font-size:26px;font-weight:900}}
  .h2h-lbl{{font-size:10px;color:var(--muted);text-transform:uppercase}}
  .h2h-div{{width:1px;height:36px;background:var(--border)}}
  .h2h-row{{display:flex;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border);font-size:13px}}
  .player-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}}
  .player-card{{background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:12px}}
  .player-name{{font-size:12px;font-weight:700;margin-bottom:4px}}
  .player-pos{{font-size:10px;color:var(--muted)}}
  .player-stat{{font-size:11px;color:var(--accent);margin-top:6px;font-weight:600}}
  footer{{text-align:center;padding:32px 16px;font-size:12px;color:#475569;border-top:1px solid var(--border);margin-top:32px}}
  footer a{{color:var(--accent);text-decoration:none}}
</style>
</head>
<body>

<nav>
  <div class="logo">Palpites da IA</div>
  <span class="nav-tag">COPA 2026</span>
</nav>

<div class="page">
  <div class="badge"><span class="dot"></span>v3 · Elo + Pi + FIFA + Regional + Tail Risk + Jogadores · dados reais da API</div>

  <!-- CABEÇALHO -->
  <div class="match-header">
    <div class="league-label">⚽ Copa do Mundo FIFA 2026 · Grupo A · Rodada 1</div>
    <div class="teams-row">
      <div class="team-block">
        <img class="team-logo" src="https://media.api-sports.io/football/teams/16.png" alt="México">
        <div class="team-name">México</div>
      </div>
      <div class="vs-pill">VS</div>
      <div class="team-block">
        <img class="team-logo" src="https://media.api-sports.io/football/teams/1531.png" alt="África do Sul">
        <div class="team-name">África do Sul</div>
      </div>
    </div>
    <div class="match-meta">
      <div class="meta-item">📅 11 de junho de 2026 · 16h00 (Brasília)</div>
      <div class="meta-item">📍 Estadio Banorte · Cidade do México · México (2.240m altitude)</div>
    </div>
  </div>

  <!-- ALERTAS -->
  <div class="alerta-card blue">
    <div class="alerta-icon">📊</div>
    <div class="alerta-text">
      <div class="alerta-title">Odds Pinnacle — México forte favorito</div>
      <div class="alerta-desc">México @1.45 (69% impl.) · Empate @4.50 (22%) · África do Sul @8.02 (12%). Nosso modelo com home advantage: México 50.1% / Empate 26.4% / África do Sul 23.5%.</div>
    </div>
  </div>
  <div class="alerta-card orange">
    <div class="alerta-icon">🏠</div>
    <div class="alerta-text">
      <div class="alerta-title">México joga em casa — altitude 2.240m + 85.000 torcedores</div>
      <div class="alerta-desc">Home advantage aplicado: λ México ×1.25, λ África do Sul ×0.80. Altitude favorece times aclimatados. Nosso modelo ainda subestima México vs Pinnacle — gap residual: altitude isolada não modelada.</div>
    </div>
  </div>
  <div class="alerta-card amber">
    <div class="alerta-icon">⚠️</div>
    <div class="alerta-text">
      <div class="alerta-title">H2H escasso · Uncertainty Index 40/100</div>
      <div class="alerta-desc">Apenas 1 confronto histórico (Copa 2010, 1×1). Confiança penalizada em 15%. UI=40 abaixo do limiar 60 — probabilidades não achatadas.</div>
    </div>
  </div>

  <!-- PROBABILIDADES 1X2 -->
  <div class="card">
    <div class="card-title">⚽ Resultado Final — Modelo vs Mercado</div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px">
      <div style="background:var(--card2);border:1px solid #1e3a5f;border-radius:10px;padding:12px;text-align:center">
        <div style="font-size:10px;color:var(--muted)">Nosso Modelo (DC+Home)</div>
        <div style="font-size:12px;font-weight:700;color:#3b82f6;margin:4px 0">50.1%</div><div style="font-size:10px;color:var(--muted)">México</div>
        <div style="font-size:12px;font-weight:700;color:#f59e0b;margin:4px 0">26.4%</div><div style="font-size:10px;color:var(--muted)">Empate</div>
        <div style="font-size:12px;font-weight:700;color:#6366f1;margin:4px 0">23.5%</div><div style="font-size:10px;color:var(--muted)">África do Sul</div>
      </div>
      <div style="background:var(--card2);border:1px solid var(--border);border-radius:10px;padding:12px;text-align:center">
        <div style="font-size:10px;color:var(--muted)">Skellam</div>
        <div style="font-size:12px;font-weight:700;color:#3b82f6;margin:4px 0">36.9%</div><div style="font-size:10px;color:var(--muted)">México</div>
        <div style="font-size:12px;font-weight:700;color:#f59e0b;margin:4px 0">25.8%</div><div style="font-size:10px;color:var(--muted)">Empate</div>
        <div style="font-size:12px;font-weight:700;color:#6366f1;margin:4px 0">37.3%</div><div style="font-size:10px;color:var(--muted)">África do Sul</div>
      </div>
      <div style="background:var(--card2);border:1px solid #166534;border-radius:10px;padding:12px;text-align:center">
        <div style="font-size:10px;color:var(--muted)">Pinnacle (mercado)</div>
        <div style="font-size:14px;font-weight:900;color:#4ade80;margin:4px 0">69.0%</div><div style="font-size:10px;color:var(--muted)">México @1.45</div>
        <div style="font-size:14px;font-weight:900;color:#4ade80;margin:4px 0">22.2%</div><div style="font-size:10px;color:var(--muted)">Empate @4.50</div>
        <div style="font-size:14px;font-weight:900;color:#4ade80;margin:4px 0">12.5%</div><div style="font-size:10px;color:var(--muted)">África do Sul @8.02</div>
      </div>
    </div>
    <div class="source-line">λ México=1.685 (×1.25 home) · λ África=1.085 (×0.80) · Fat Tail Student-t ν=4 · Uncertainty 40/100</div>
  </div>

  <!-- PLACARES -->
  <div class="card">
    <div class="card-title">🏆 Top 5 Placares Mais Prováveis (Dixon-Coles)</div>
    <div class="scores-grid">
      <div class="score-item top"><div class="score-placar">1–1</div><div class="score-prob">13.5%</div></div>
      <div class="score-item"><div class="score-placar">1–2</div><div class="score-prob">8.3%</div></div>
      <div class="score-item"><div class="score-placar">2–1</div><div class="score-prob">8.3%</div></div>
      <div class="score-item"><div class="score-placar">0–0</div><div class="score-prob">8.0%</div></div>
      <div class="score-item"><div class="score-placar">0–1</div><div class="score-prob">7.9%</div></div>
    </div>
    <div class="source-line" style="margin-top:10px">Matriz DC 6×6 · correção τ (0-0×1.183 · 1-1×1.1 · 0-1×0.867 · 1-0×0.862) · 15% Fat Tail</div>
  </div>

  <!-- ESTATÍSTICAS DA TEMPORADA -->
  <div class="card">
    <div class="card-title">📊 Estatísticas da Temporada (Seleção)</div>
    <div class="grid2">
      <div class="inner-card">
        <div class="inner-title">🇲🇽 México</div>
        <div class="stat-row"><span class="stat-label">Jogos analisados</span><span class="stat-value">{st5_mx['jogos']}</span></div>
        <div class="stat-row"><span class="stat-label">Vitórias / Empates / Derrotas</span><span class="stat-value">{st5_mx['vitorias']}V {st5_mx['empates']}E {st5_mx['derrotas']}D</span></div>
        <div class="stat-row"><span class="stat-label">Gols marcados</span><span class="stat-value">{st5_mx['gols_marcados']} ({st5_mx['media_gols_m']}/jogo)</span></div>
        <div class="stat-row"><span class="stat-label">Gols sofridos</span><span class="stat-value">{st5_mx['gols_sofridos']} ({st5_mx['media_gols_s']}/jogo)</span></div>
        <div class="source-line">Fonte: Últimos {st5_mx['jogos']} jogos da seleção (amistosos + competições oficiais)</div>
      </div>
      <div class="inner-card">
        <div class="inner-title">🇿🇦 África do Sul</div>
        <div class="stat-row"><span class="stat-label">Jogos analisados</span><span class="stat-value">{st5_sa['jogos']}</span></div>
        <div class="stat-row"><span class="stat-label">Vitórias / Empates / Derrotas</span><span class="stat-value">{st5_sa['vitorias']}V {st5_sa['empates']}E {st5_sa['derrotas']}D</span></div>
        <div class="stat-row"><span class="stat-label">Gols marcados</span><span class="stat-value">{st5_sa['gols_marcados']} ({st5_sa['media_gols_m']}/jogo)</span></div>
        <div class="stat-row"><span class="stat-label">Gols sofridos</span><span class="stat-value">{st5_sa['gols_sofridos']} ({st5_sa['media_gols_s']}/jogo)</span></div>
        <div class="source-line">Fonte: Últimos {st5_sa['jogos']} jogos da seleção (amistosos + competições oficiais)</div>
      </div>
    </div>
  </div>

  <!-- PERFORMANCE CASA/FORA -->
  <div class="card">
    <div class="card-title">🏟️ Performance por Mando (últimos 10 jogos)</div>
    <div class="alerta-card green" style="margin-bottom:16px">
      <div class="alerta-icon">🏠</div>
      <div class="alerta-text">
        <div class="alerta-title">México joga em casa neste jogo</div>
        <div class="alerta-desc">⚠️ Altitude 2.240m · 85.000 torcedores · Estadio Banorte, Cidade do México. Times visitantes sofrem queda de ~10-15% na performance física nos primeiros 30 minutos em alta altitude.</div>
      </div>
    </div>
    <div class="grid2">
      <div class="inner-card">
        <div class="inner-title">🇲🇽 México em Casa</div>
        <div class="stat-row"><span class="stat-label">Jogos</span><span class="stat-value">{mx_casa['jogos']}</span></div>
        <div class="stat-row"><span class="stat-label">V/E/D</span><span class="stat-value">{mx_casa['vitorias']}V {mx_casa['empates']}E {mx_casa['derrotas']}D</span></div>
        <div class="stat-row"><span class="stat-label">Gols marcados</span><span class="stat-value">{mx_casa['gols_m']} ({mx_casa['media_gols_m']}/jogo)</span></div>
        <div class="stat-row"><span class="stat-label">Gols sofridos</span><span class="stat-value">{mx_casa['gols_s']} ({mx_casa['media_gols_s']}/jogo)</span></div>
      </div>
      <div class="inner-card">
        <div class="inner-title">🇿🇦 África do Sul Fora</div>
        <div class="stat-row"><span class="stat-label">Jogos</span><span class="stat-value">{sa_fora['jogos']}</span></div>
        <div class="stat-row"><span class="stat-label">V/E/D</span><span class="stat-value">{sa_fora['vitorias']}V {sa_fora['empates']}E {sa_fora['derrotas']}D</span></div>
        <div class="stat-row"><span class="stat-label">Gols marcados</span><span class="stat-value">{sa_fora['gols_m']} ({sa_fora['media_gols_m']}/jogo)</span></div>
        <div class="stat-row"><span class="stat-label">Gols sofridos</span><span class="stat-value">{sa_fora['gols_s']} ({sa_fora['media_gols_s']}/jogo)</span></div>
      </div>
    </div>
    <div class="source-line" style="margin-top:10px">Casa/fora baseado na designação da API-Football. Em internacionais, "casa" = time listado como home no fixture (nem sempre geograficamente em casa).</div>
  </div>

  <!-- FORMA RECENTE -->
  <div class="card">
    <div class="card-title">📈 Forma Recente — Últimos 5 Jogos</div>
    <div class="grid2">
      <div>
        <div style="font-size:13px;font-weight:700;margin-bottom:8px">Mexico &nbsp;{badges_mx}</div>
        {rows_mx}
      </div>
      <div>
        <div style="font-size:13px;font-weight:700;margin-bottom:8px">Africa do Sul &nbsp;{badges_sa}</div>
        {rows_sa}
      </div>
    </div>
  </div>

  <!-- H2H -->
  <div class="card">
    <div class="card-title">🤝 Histórico H2H</div>
    <div class="h2h-summary">
      <div class="h2h-stat"><div class="h2h-num" style="color:#3b82f6">0</div><div class="h2h-lbl">Vitórias México</div></div>
      <div class="h2h-div"></div>
      <div class="h2h-stat"><div class="h2h-num" style="color:#f59e0b">1</div><div class="h2h-lbl">Empates</div></div>
      <div class="h2h-div"></div>
      <div class="h2h-stat"><div class="h2h-num" style="color:#6366f1">0</div><div class="h2h-lbl">Vitórias África</div></div>
    </div>
    {h2h_rows}
    <div class="source-line">⚠️ 1 confronto histórico — confiança H2H = 0.85 (penalização de 15% no score final)</div>
  </div>

  <!-- ANÁLISE POR MERCADO -->
  <div class="card">
    <div class="card-title">📋 Análise por Mercado</div>
    <div style="display:flex;flex-direction:column;gap:12px">
      <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px">
        <div style="font-size:13px;font-weight:700;margin-bottom:10px">Resultado 1X2</div>
        <div class="odds-box">
          <div class="odds-item"><div class="odds-label">Vitória México</div><div class="odds-val" style="color:#3b82f6">1.45</div><div class="odds-impl">Modelo: 50.1%</div></div>
          <div class="odds-item"><div class="odds-label">Empate</div><div class="odds-val" style="color:#f59e0b">4.50</div><div class="odds-impl">Modelo: 26.4%</div></div>
          <div class="odds-item"><div class="odds-label">Vitória África Sul</div><div class="odds-val" style="color:#6366f1">8.02</div><div class="odds-impl">Modelo: 23.5%</div></div>
        </div>
        <div style="font-size:12px;color:var(--muted)">México em casa com home advantage aplicado. O Pinnacle precifica com mais altitude. <strong style="color:#f59e0b">Nível: MÉDIA</strong></div>
      </div>
      <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px">
        <div class="market-row"><span style="font-size:13px;font-weight:700">Over 1.5 Gols</span><div style="display:flex;gap:8px;align-items:center"><span class="market-pct" style="color:#22c55e">77.5%</span><span class="conf conf-alta">ALTA</span><span style="font-size:12px;color:var(--muted)">Odd: <span class="missing">XXX</span></span></div></div>
        <div class="prob-bar-bg"><div class="prob-bar" style="width:77.5%;background:linear-gradient(90deg,#16a34a,#22c55e)"></div></div>
        <div style="font-size:11px;color:var(--muted)">Sinal mais robusto — λ total = 2.77 · Fat Tail +1.2pp</div>
      </div>
      <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px">
        <div class="market-row"><span style="font-size:13px;font-weight:700">Over 2.5 Gols</span><div style="display:flex;gap:8px;align-items:center"><span class="market-pct" style="color:#f59e0b">50.6%</span><span class="conf conf-media">MÉDIA</span><span style="font-size:12px;color:var(--muted)">Odd: <span class="missing">XXX</span></span></div></div>
        <div class="prob-bar-bg"><div class="prob-bar" style="width:50.6%;background:linear-gradient(90deg,#d97706,#f59e0b)"></div></div>
        <div style="font-size:11px;color:var(--muted)">Praticamente 50/50. Rodada 1 favorece Under. Aguardar odd real para calcular value.</div>
      </div>
      <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:16px">
        <div class="market-row"><span style="font-size:13px;font-weight:700">Ambas Marcam — Sim</span><div style="display:flex;gap:8px;align-items:center"><span class="market-pct" style="color:#f59e0b">56.5%</span><span class="conf conf-media">MÉDIA</span><span style="font-size:12px;color:var(--muted)">Odd: <span class="missing">XXX</span></span></div></div>
        <div class="prob-bar-bg"><div class="prob-bar" style="width:56.5%;background:linear-gradient(90deg,#d97706,#f59e0b)"></div></div>
        <div style="font-size:11px;color:var(--muted)">África do Sul marcou em 7/10 últimos jogos. México BTTS 30% últimos 5.</div>
      </div>
    </div>
  </div>

  <!-- RATINGS -->
  <div class="card">
    <div class="card-title">📡 Camada 1 — Ratings (Elo + Pi + FIFA + Regional)</div>
    <div class="grid2">
      <div class="inner-card">
        <div class="inner-title">🇲🇽 México <span style="font-size:10px;padding:2px 8px;border-radius:99px;background:#1e3a5f;color:#60a5fa">CONCACAF</span></div>
        <div class="stat-row"><span class="stat-label">Elo</span><span class="stat-value" style="color:#3b82f6">1.841</span></div>
        <div class="stat-row"><span class="stat-label">Pi-rating</span><span class="stat-value" style="color:#22c55e">+1.029</span></div>
        <div class="stat-row"><span class="stat-label">FIFA Ranking</span><span class="stat-value">#15 mundial · #16/48 Copa</span></div>
        <div class="stat-row"><span class="stat-label">FIFA Normalizado</span><span class="stat-value">0.681</span></div>
        <div class="stat-row"><span class="stat-label">z-score CONCACAF</span><span class="stat-value" style="color:#22c55e">+0.88 (3º/7)</span></div>
        <div class="stat-row"><span class="stat-label">Rating Combinado</span><span class="stat-value" style="color:var(--accent)">+1.370</span></div>
        <div class="source-line">50% Elo + 30% Pi + 20% FIFA · Elo médio CONCACAF: 1715 ± 143</div>
      </div>
      <div class="inner-card">
        <div class="inner-title">🇿🇦 África do Sul <span style="font-size:10px;padding:2px 8px;border-radius:99px;background:#1a2e1a;color:#4ade80">CAF</span></div>
        <div class="stat-row"><span class="stat-label">Elo</span><span class="stat-value" style="color:#6366f1">1.641</span></div>
        <div class="stat-row"><span class="stat-label">Pi-rating</span><span class="stat-value" style="color:#ef4444">−0.094</span></div>
        <div class="stat-row"><span class="stat-label">FIFA Ranking</span><span class="stat-value">#68 mundial · #46/48 Copa</span></div>
        <div class="stat-row"><span class="stat-label">FIFA Normalizado</span><span class="stat-value">0.043</span></div>
        <div class="stat-row"><span class="stat-label">z-score CAF</span><span class="stat-value" style="color:#ef4444">−0.525 (8º/10)</span></div>
        <div class="stat-row"><span class="stat-label">Rating Combinado</span><span class="stat-value">+0.150</span></div>
        <div class="source-line">50% Elo + 30% Pi + 20% FIFA · Elo médio CAF: 1696 ± 106</div>
      </div>
    </div>
  </div>

  <!-- JOGADORES DE DESTAQUE -->
  <div class="card">
    <div class="card-title">⚽ Jogadores de Destaque (P90 × LSS)</div>
    <div style="margin-bottom:16px">
      <div style="font-size:13px;font-weight:700;margin-bottom:10px">🇲🇽 México</div>
      <div class="player-grid">
        <div class="player-card">
          <img src="https://media.api-sports.io/football/players/2887.png" style="width:40px;height:40px;border-radius:50%;margin-bottom:6px" onerror="this.style.display='none'">
          <div class="player-name">Raúl Jiménez</div>
          <div class="player-pos">FW · Fulham</div>
          <div class="player-stat">🥇 0.33 gols/90 adj</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">0.35 × 0.94 (CONCACAF GC) · 11 gols / 2795 min</div>
          <div style="font-size:10px;color:#f59e0b;margin-top:4px">Mercado: Marcar a qualquer momento</div>
        </div>
        <div class="player-card">
          <img src="https://media.api-sports.io/football/players/2889.png" style="width:40px;height:40px;border-radius:50%;margin-bottom:6px" onerror="this.style.display='none'">
          <div class="player-name">Alexis Vega</div>
          <div class="player-pos">FW · Toluca</div>
          <div class="player-stat">🥇 0.12 gols/90 adj</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">0.17 × 0.72 (Campeón) · 4 gols / 2074 min</div>
          <div style="font-size:10px;color:#f59e0b;margin-top:4px">Mercado: Marcar a qualquer momento</div>
        </div>
        <div class="player-card">
          <img src="https://media.api-sports.io/football/players/2881.png" style="width:40px;height:40px;border-radius:50%;margin-bottom:6px" onerror="this.style.display='none'">
          <div class="player-name">Jesús Gallardo</div>
          <div class="player-pos">DF · Toluca</div>
          <div class="player-stat">🎯 0.10 assists/90 adj</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">0.14 × 0.73 (Campeón) · 5 assists / 3293 min</div>
          <div style="font-size:10px;color:#f59e0b;margin-top:4px">Mercado: Dar assistência</div>
        </div>
      </div>
    </div>
    <div>
      <div style="font-size:13px;font-weight:700;margin-bottom:10px">🇿🇦 África do Sul</div>
      <div class="player-grid">
        <div class="player-card">
          <div class="player-name">Evidence Makgopa</div>
          <div class="player-pos">FW · Orlando Pirates</div>
          <div class="player-stat">🥇 0.24 gols/90 adj</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">0.49 × 0.48 · 8 gols / 1473 min</div>
          <div style="font-size:10px;color:#f59e0b;margin-top:4px">Mercado: Marcar a qualquer momento</div>
        </div>
        <div class="player-card">
          <div class="player-name">Oswin Appollis</div>
          <div class="player-pos">FW · Orlando Pirates</div>
          <div class="player-stat">🥇 0.20 gols/90 adj</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">0.40 × 0.50 · 15 gols / 3375 min</div>
          <div style="font-size:10px;color:#f59e0b;margin-top:4px">Mercado: Marcar a qualquer momento</div>
        </div>
        <div class="player-card">
          <div class="player-name">Teboho Mokoena</div>
          <div class="player-pos">MF · Mamelodi Sundowns</div>
          <div class="player-stat">🎯 0.05 assists/90 adj</div>
          <div style="font-size:10px;color:var(--muted);margin-top:2px">0.07 × 0.68 · 3 assists / 3770 min</div>
          <div style="font-size:10px;color:#f59e0b;margin-top:4px">Mercado: Dar assistência</div>
        </div>
      </div>
    </div>
    <div class="source-line" style="margin-top:10px">P90 = (total/min)×90 · mín 270 min · ajustado por LSS (League Strength Score) · copa_apenas excluído de categorias ofensivas</div>
  </div>

  <!-- ÁRBITRO -->
  <div class="card">
    <div class="card-title">🟨 Árbitro</div>
    <div style="background:var(--card2);border:1px solid var(--border);border-radius:12px;padding:20px;text-align:center">
      <div style="font-size:32px;margin-bottom:8px">🏟️</div>
      <div style="font-size:15px;font-weight:700;color:var(--muted)">Árbitro ainda não definido pela FIFA</div>
      <div style="font-size:12px;color:#475569;margin-top:6px">Anunciado 5-7 dias antes do jogo via /fixtures?id=1489369</div>
    </div>
  </div>

</div>

<footer>
  Palpites da IA v3 · API-Football v3 · The Odds API (Pinnacle) · Wikipedia Squads · Seed Copa 2026<br>
  Modelos: Dixon-Coles · Skellam · Fat Tail (Student-t ν=4) · Context+HomeAdvantage · Tail Risk (Taleb)<br>
  Ratings: Elo fallback · Pi-rating (0.98^dia) · FIFA Ranking · Normalização Regional por Confederação<br>
  Players: Wikipedia scraping · P90 × LSS · copa_apenas filter · player_id API search<br>
  <a href="https://palpitesdaia.lovable.app/partida/mexico-south-africa" target="_blank">palpitesdaia.lovable.app/partida/mexico-south-africa</a><br><br>
  ⚠️ Arquivo de teste estático v3. Probabilidades com home advantage. Odds Over/Under pendentes.
</footer>
</body>
</html>"""


asyncio.run(main())
