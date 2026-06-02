"""
Agente IA premium — gera recomendação de aposta usando Claude.
Recebe um objeto Partida com stats reais e probabilidades calculadas por Poisson.
"""
import os
import anthropic
from app.models.schemas import Partida, RecomendacaoIA

_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

SYSTEM_PROMPT = """Você é um analista especializado em apostas esportivas de futebol.
Sua função é analisar dados estatísticos reais de seleções nacionais e recomendar
a entrada com maior valor esperado antes de uma partida da Copa do Mundo.

Regras:
- Seja direto. O apostador quer saber O QUE apostar e POR QUÊ.
- Base sua análise nas estatísticas fornecidas — não invente dados.
- Se os dados forem insuficientes, diga claramente e recomende cautela.
- Indique sempre: mercado, entrada específica e nível de confiança (Alta/Média/Baixa).
- Explique em 2-3 frases simples usando os dados disponíveis.
- Nunca garanta resultados. Sempre mencione que é análise estatística.
- Responda SEMPRE em português brasileiro.
"""


async def gerar_recomendacao(partida: Partida) -> RecomendacaoIA:
    prompt = _montar_prompt(partida)
    message = _client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    texto = message.content[0].text
    return _parsear_resposta(texto, partida)


def _montar_prompt(p: Partida) -> str:
    # Probabilidades
    prob_txt = "Probabilidades indisponíveis (dados insuficientes)."
    if p.probabilidades and not p.probabilidades.dados_insuficientes:
        prob_txt = (
            f"Calculadas por modelo de Poisson (λ baseado em médias históricas de gols):\n"
            f"  - Vitória {p.time_casa_nome}: {p.probabilidades.vitoria_casa}%  "
            f"(λ={p.probabilidades.lambda_casa} gols esperados)\n"
            f"  - Empate: {p.probabilidades.empate}%\n"
            f"  - Vitória {p.time_fora_nome}: {p.probabilidades.vitoria_fora}%  "
            f"(λ={p.probabilidades.lambda_fora} gols esperados)"
        )

    # Stats históricas
    def fmt_stats(stats, nome):
        if stats.dados_insuficientes:
            return f"  {nome}: dados insuficientes na API"
        return (
            f"  {nome} ({stats.fonte}, {stats.jogos} jogos):\n"
            f"    Média gols marcados: {stats.media_gols_marcados}\n"
            f"    Média gols sofridos: {stats.media_gols_sofridos}\n"
            f"    Aproveitamento: {stats.vitorias}V {stats.empates}E {stats.derrotas}D"
        )

    stats_txt = fmt_stats(p.stats_casa, p.time_casa_nome) + "\n" + fmt_stats(p.stats_fora, p.time_fora_nome)

    # Forma recente
    def fmt_forma(forma, nome):
        if not forma:
            return f"  {nome}: sem dados de forma recente"
        linhas = [f"  {nome}:"]
        for j in forma:
            linhas.append(
                f"    {j.data} vs {j.adversario}: {j.placar_proprio}-{j.placar_adversario} [{j.resultado}] ({j.competicao})"
            )
        return "\n".join(linhas)

    forma_txt = fmt_forma(p.forma_casa, p.time_casa_nome) + "\n" + fmt_forma(p.forma_fora, p.time_fora_nome)

    # H2H
    h2h_txt = "Sem histórico de confrontos diretos disponível."
    if p.head_to_head:
        linhas = ["Últimos confrontos diretos:"]
        for h in p.head_to_head[:5]:
            linhas.append(
                f"  {h['data']} — {h['casa']} {h['gols_casa']} x {h['gols_fora']} {h['fora']} ({h['competicao']})"
            )
        h2h_txt = "\n".join(linhas)

    aviso_dados = ""
    if p.dados_insuficientes:
        aviso_dados = "\n⚠️ AVISO: alguns dados estão indisponíveis na API. Baseie a análise apenas no que foi fornecido.\n"

    return f"""Analise a partida e dê a melhor recomendação de aposta:

PARTIDA: {p.time_casa_nome} x {p.time_fora_nome}
Copa do Mundo FIFA 2026  |  {p.rodada}
Data/hora: {p.horario}
Local: {p.estadio}, {p.cidade}
{aviso_dados}
PROBABILIDADES:
{prob_txt}

ESTATÍSTICAS HISTÓRICAS (Copas do Mundo anteriores):
{stats_txt}

FORMA RECENTE (últimos 5 jogos):
{forma_txt}

HISTÓRICO H2H:
{h2h_txt}

Responda exatamente neste formato:
MERCADO: [tipo do mercado]
ENTRADA: [o que apostar]
CONFIANÇA: [Alta/Média/Baixa]
ANÁLISE: [2-3 frases usando os dados acima]
"""


def _parsear_resposta(texto: str, partida: Partida) -> RecomendacaoIA:
    linhas = {}
    for linha in texto.splitlines():
        if ":" in linha:
            k, v = linha.split(":", 1)
            linhas[k.strip()] = v.strip()

    return RecomendacaoIA(
        partida_id=partida.id,
        mercado=linhas.get("MERCADO", "Resultado (1X2)"),
        entrada=linhas.get("ENTRADA", "—"),
        confianca=linhas.get("CONFIANÇA", linhas.get("CONFIANCA", "Média")),
        analise=linhas.get("ANÁLISE", linhas.get("ANALISE", texto)),
        texto_completo=texto,
    )
