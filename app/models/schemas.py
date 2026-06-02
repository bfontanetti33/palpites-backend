from pydantic import BaseModel


# ── Sub-modelos ───────────────────────────────────────────────────────────────

class PerformanceLocal(BaseModel):
    """Performance separada por mando (casa ou fora)."""
    jogos: int | None = None
    vitorias: int | None = None
    empates: int | None = None
    derrotas: int | None = None
    gols_marcados: int | None = None
    gols_sofridos: int | None = None
    media_gols_marcados: float | None = None
    media_gols_sofridos: float | None = None


class EstatisticasTemporada(BaseModel):
    """
    Estatísticas de um time em uma Copa do Mundo anterior.
    Fonte: /teams/statistics (league=1, season=2022/2018/...).

    Nota sobre casa/fora: na Copa do Mundo todos jogam em campo neutro
    (sede do torneio), então o split casa/fora não é relevante e fica None.
    """
    fonte: str = ""
    dados_insuficientes: bool = False
    sede_neutra: bool = True   # Copa = campo neutro, split casa/fora ignorado

    # Totais históricos (Copa anterior)
    jogos: int | None = None
    vitorias: int | None = None
    empates: int | None = None
    derrotas: int | None = None
    gols_marcados: int | None = None
    gols_sofridos: int | None = None
    media_gols_marcados: float | None = None
    media_gols_sofridos: float | None = None

    # Casa/fora: sempre None para Copa (campo neutro)
    casa: PerformanceLocal | None = None
    fora: PerformanceLocal | None = None

    # Métricas de jogo
    clean_sheets: int | None = None
    media_amarelos: float | None = None
    media_vermelhos: float | None = None
    penaltis_marcados: int | None = None
    penaltis_total: int | None = None

    # Calculadas a partir dos últimos 10 jogos reais (qualquer competição)
    jogos_forma: int | None = None          # quantos jogos foram usados
    btts_pct: int | None = None             # % jogos em que ambos marcaram
    over25_pct: int | None = None           # % jogos com mais de 2.5 gols
    under25_pct: int | None = None
    media_gols_marcados_recente: float | None = None   # média últimos 10 jogos
    media_gols_sofridos_recente: float | None = None


class EntradaForma(BaseModel):
    data: str
    adversario: str
    placar_proprio: int | None = None
    placar_adversario: int | None = None
    resultado: str                          # "W", "D", "L"
    competicao: str


class PlacarProvavel(BaseModel):
    placar: str                             # ex: "1-0"
    probabilidade: float                    # 0.0-100.0


class Probabilidades(BaseModel):
    vitoria_casa: int
    empate: int
    vitoria_fora: int
    lambda_casa: float
    lambda_fora: float
    metodo: str = "poisson"
    dados_insuficientes: bool = False


class Arbitro(BaseModel):
    nome: str
    jogos_apitados: int | None = None
    media_amarelos: float | None = None
    media_vermelhos: float | None = None
    media_penaltis: float | None = None


# ── Modelos de partida ────────────────────────────────────────────────────────

class PartidaResumo(BaseModel):
    id: int
    slug: str
    rodada: str
    horario: str
    status: str
    estadio: str
    cidade: str
    time_casa_nome: str
    time_casa_logo: str
    time_fora_nome: str
    time_fora_logo: str
    gols_casa: int | None = None
    gols_fora: int | None = None


class Partida(PartidaResumo):
    time_casa_id: int
    time_fora_id: int

    # Stats históricas de cada time + métricas de forma recente
    stats_casa: EstatisticasTemporada = EstatisticasTemporada(dados_insuficientes=True)
    stats_fora: EstatisticasTemporada = EstatisticasTemporada(dados_insuficientes=True)

    # Forma recente (últimos 5 jogos em qualquer competição)
    forma_casa: list[EntradaForma] = []
    forma_fora: list[EntradaForma] = []

    # Confrontos históricos
    head_to_head: list[dict] = []

    # Probabilidades e placares via Poisson
    probabilidades: Probabilidades | None = None
    placares_provaveis: list[PlacarProvavel] = []   # top 3

    # Árbitro
    arbitro: Arbitro | None = None

    # Flag geral
    dados_insuficientes: bool = False


# ── Respostas da API ──────────────────────────────────────────────────────────

class RecomendacaoIA(BaseModel):
    partida_id: int
    mercado: str
    entrada: str
    confianca: str
    analise: str
    texto_completo: str


class RespostaCopa(BaseModel):
    total: int
    temporada: int
    partidas: list[PartidaResumo]
