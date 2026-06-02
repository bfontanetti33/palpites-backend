from pydantic import BaseModel


class EstatisticasTime(BaseModel):
    media_gols_marcados: float | None = None
    media_gols_sofridos: float | None = None
    vitorias: int | None = None
    empates: int | None = None
    derrotas: int | None = None
    jogos: int | None = None
    fonte: str = ""                   # ex: "Copa 2022", "Copa 2018"
    dados_insuficientes: bool = False


class EntradaForma(BaseModel):
    data: str
    adversario: str
    placar_proprio: int | None = None
    placar_adversario: int | None = None
    resultado: str                    # "W", "D", "L"
    competicao: str


class Probabilidades(BaseModel):
    vitoria_casa: int                 # 0-100
    empate: int
    vitoria_fora: int
    lambda_casa: float                # gols esperados casa (Poisson)
    lambda_fora: float
    metodo: str = "poisson"
    dados_insuficientes: bool = False


class PartidaResumo(BaseModel):
    id: int
    slug: str
    rodada: str
    horario: str
    status: str                       # "NS", "1H", "HT", "2H", "FT", "TBD"
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
    stats_casa: EstatisticasTime = EstatisticasTime(dados_insuficientes=True)
    stats_fora: EstatisticasTime = EstatisticasTime(dados_insuficientes=True)
    forma_casa: list[EntradaForma] = []
    forma_fora: list[EntradaForma] = []
    head_to_head: list[dict] = []
    probabilidades: Probabilidades | None = None
    dados_insuficientes: bool = False


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
