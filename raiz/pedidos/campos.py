"""O pedido do cliente, no formato do contrato com o front (front/compartilhado/pedidos/tipos.ts, CamposPedido).
Campos que faltam ganham o padrão da cena-alvo (1 milhão de créditos, ProFloresta+, Amazônia)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

TipoMeta = Literal["creditos", "hectares", "flag_t_ano"]
Metodo = Literal["regeneracao_assistida", "semeadura_direta", "plantio_total", "agrofloresta", "silvipastoril"]
CaminhoFront = Literal["matricula_conferida", "matricula_a_conferir", "concessao", "assentamento", "posse_em_titulacao"]
FiltroInteresse = Literal["qualquer", "interessados", "com_aceite"]
Exclusao = Literal["embargo", "terra_indigena", "uc_protecao_integral", "projeto_carbono"]

METODOS: tuple[str, ...] = (
    "regeneracao_assistida",
    "semeadura_direta",
    "plantio_total",
    "agrofloresta",
    "silvipastoril",
)
CAMINHOS: tuple[str, ...] = ("matricula_conferida", "matricula_a_conferir", "concessao", "assentamento",
                             "posse_em_titulacao")  # fmt: skip
EXCLUSOES: tuple[str, ...] = ("embargo", "terra_indigena", "uc_protecao_integral", "projeto_carbono")


class Meta(BaseModel):
    tipo: TipoMeta = "creditos"
    valor: float = Field(1_000_000, gt=0)


class Raio(BaseModel):
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-90, le=90)
    km: float = Field(gt=0, le=2000)


class Onde(BaseModel):
    biomas: list[str] = Field(default_factory=lambda: ["Amazônia"])
    ufs: list[str] = Field(default_factory=list)
    municipios: list[str] = Field(default_factory=list)
    raio: Raio | None = None
    poligono: list[tuple[float, float]] | None = None
    so_fornecedores_cadeia: bool = False
    # códigos CAR dos fornecedores da cadeia (FLAG), quando so_fornecedores_cadeia
    fornecedores: list[str] = Field(default_factory=list)

    @field_validator("ufs")
    @classmethod
    def _ufs(cls, v: list[str]) -> list[str]:
        return [u.strip().upper() for u in v if u.strip()]

    @field_validator("poligono")
    @classmethod
    def _anel(cls, v):
        if v is not None and len(v) < 4:
            raise ValueError("o polígono precisa de pelo menos 3 pontos e fechar no primeiro")
        return v


class Dinheiro(BaseModel):
    custo_max_usd_credito: float | None = Field(None, gt=0)
    tir_min: float | None = None  # % ao ano
    preco_venda_usd: float = Field(55, gt=0)
    fracao_financiada: float = Field(0.5, ge=0, le=1)


class Forma(BaseModel):
    distancia_max_km: float | None = Field(None, gt=0)
    max_donos: int | None = Field(None, gt=0)
    area_min_contigua_ha: float | None = Field(None, gt=0)


class MarcoProprio(BaseModel):
    ano: int = Field(gt=0, le=60)
    fracao: float = Field(gt=0, le=1)


class CamposPedido(BaseModel):
    meta: Meta = Field(default_factory=Meta)
    cronograma: Literal["profloresta", "livre", "proprio"] = "profloresta"
    marcos_proprios: list[MarcoProprio] | None = None
    onde: Onde = Field(default_factory=Onde)
    dinheiro: Dinheiro = Field(default_factory=Dinheiro)
    metodos: list[Metodo] = Field(default_factory=lambda: ["regeneracao_assistida", "semeadura_direta",
                                                           "plantio_total"])  # fmt: skip
    terra: list[CaminhoFront] = Field(default_factory=lambda: ["matricula_conferida", "matricula_a_conferir",
                                                               "concessao"])  # fmt: skip
    forma: Forma = Field(default_factory=Forma)
    interesse: FiltroInteresse = "qualquer"
    exclusoes: list[Exclusao] = Field(default_factory=lambda: list(EXCLUSOES))
    reserva_dias: int = Field(60, gt=0, le=365)

    @field_validator("metodos", "terra")
    @classmethod
    def _nao_vazio(cls, v):
        if not v:
            raise ValueError("escolha pelo menos um")
        return list(dict.fromkeys(v))


def titulo(c: CamposPedido) -> str:
    """Frase curta para "Meus pedidos": "1 milhão de créditos no PA"."""
    v = c.meta.valor
    num = f"{v / 1e6:g} milhão" if v >= 1e6 and v < 2e6 else (f"{v / 1e6:g} milhões" if v >= 2e6 else f"{v:,.0f}")
    num = num.replace(",", ".").replace(".", ",", 1) if v < 1e6 and "," in num else num.replace(".", ",")
    unidade = {"creditos": "de créditos", "hectares": "de hectares", "flag_t_ano": "t FLAG por ano"}[c.meta.tipo]
    onde = ", ".join(c.onde.ufs or c.onde.biomas or ["Brasil"])
    return f"{num} {unidade} em {onde}"
