"""Chave do registro e achados no formato do CFPB (registro, regra, campo, valor, gravidade, fase).

Gravidade, no padrão HMDA:
  reprova    precisa corrigir antes de seguir (o imóvel não avança naquele caminho);
  confirmar  gente confere e registra quem confirmou e quando (titulo.confirmacao);
  info       evidência e contexto, para o laudo.
Situação de cada regra: ok, falta, impede, conferir ou nao_se_aplica (como o Pelican: N/A quando não se aplica).

achados_<mun>.csv tem uma linha por (imóvel, fase, regra), com a versão da regra que gerou.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from raiz.privacidade import mascarar

FASES = ("formato", "geometria", "coerencia", "referencia", "cadeia", "regularizacao")
GRAVIDADES = ("reprova", "confirmar", "info")
SITUACOES = ("ok", "falta", "impede", "conferir", "nao_se_aplica")
COLUNAS = [
    "registro",
    "cod_imovel",
    "fase",
    "regra",
    "campo",
    "valor",
    "situacao",
    "gravidade",
    "mensagem",
    "fonte",
    "base",
    "regra_versao",
]


def _norm(s) -> str:
    return "".join(ch for ch in str(s) if ch.isalnum()).upper().lstrip("0") or "0"


def chave_registro(cod_imovel: str, matriculas: list[tuple[str, str]] = (), parcelas_sigef: list[str] = ()) -> str:
    """CAR + parcelas SIGEF + matrículas (CNS/número), em ordem: a mesma terra dá sempre a mesma chave."""
    partes = [f"car:{cod_imovel}"]
    if parcelas_sigef:
        partes.append("sigef:" + ",".join(sorted({str(p) for p in parcelas_sigef})))
    if matriculas:
        partes.append("mat:" + ",".join(sorted({f"{_norm(c)}/{_norm(m)}" for c, m in matriculas})))
    return "|".join(partes)


def gravidade_da_situacao(situacao: str, gravidade_falta: str = "falta") -> str:
    if situacao in ("ok", "nao_se_aplica"):
        return "info"
    if situacao == "conferir":
        return "confirmar"
    if situacao == "impede":
        return "reprova"
    return {"impede": "reprova", "falta": "reprova", "confirmar": "confirmar"}.get(gravidade_falta, "reprova")


@dataclass
class Achado:
    registro: str
    cod_imovel: str
    fase: str
    regra: str
    situacao: str
    gravidade: str
    mensagem: str
    campo: str | None = None
    valor: str | None = None
    fonte: str | None = None
    base: str | None = None
    regra_versao: str | None = None

    def __post_init__(self):
        if self.fase not in FASES:
            raise ValueError(f"fase desconhecida: {self.fase}")
        if self.gravidade not in GRAVIDADES:
            raise ValueError(f"gravidade desconhecida: {self.gravidade}")
        if self.situacao not in SITUACOES:
            raise ValueError(f"situação desconhecida: {self.situacao}")
        self.mensagem = mascarar(self.mensagem or "")
        if self.valor is not None:
            self.valor = mascarar(str(self.valor))

    def linha(self) -> dict:
        return asdict(self)


# --- achados da certidão (raiz/documentos) -----------------------------------------------------------------------

# código do motivo da conferência da certidão -> fase
FASE_DA_CERTIDAO = {
    "nao_e_certidao": "formato",
    "ilegivel": "formato",
    "paginas_ilegiveis": "formato",
    "confianca_baixa": "formato",
    "nao_inteiro_teor": "formato",
    "certidao_antiga": "formato",
    "matricula_cancelada": "cadeia",
    "matricula_bloqueada": "cadeia",
    "quebra_cadeia": "cadeia",
    "donos_atuais": "cadeia",
    "cancelamento_sem_alvo": "cadeia",
    "onus_grave": "cadeia",
    "onus_ativo": "cadeia",
    "contrato_averbado": "cadeia",
    "origem_para": "cadeia",
    "titulo_publico_grande": "cadeia",
    "cns_diferente": "referencia",
    "matricula_diferente": "referencia",
    "fora_do_motor": "referencia",
    "sem_cns": "referencia",
    "municipio_diferente": "referencia",
    "car_diferente": "referencia",
    "area_menor": "coerencia",
    "area_maior": "coerencia",
    "area_unidade": "coerencia",
    "sem_georreferenciamento": "coerencia",
}


def da_certidao(linha: dict, regra_versao: str | None = None) -> list[Achado]:
    """Achados de uma linha do matricula_conferencia_<mun>.csv (coluna motivos_json, já sem nome nem CPF)."""
    cod = linha.get("cod_imovel")
    if not cod or not linha.get("motivos_json"):
        return []
    try:
        motivos = json.loads(linha["motivos_json"])
    except (TypeError, json.JSONDecodeError):
        return []
    reg = chave_registro(cod, [(linha.get("registro_cns") or "", linha.get("registro_matricula") or "")])
    out = []
    for m in motivos:
        g = m.get("gravidade", "info")
        out.append(
            Achado(
                registro=reg,
                cod_imovel=cod,
                fase=FASE_DA_CERTIDAO.get(m.get("codigo"), "referencia"),
                regra=f"certidao.{m.get('codigo')}",
                situacao={"reprova": "falta", "confirmar": "conferir"}.get(g, "ok"),
                gravidade=g if g in GRAVIDADES else "info",
                mensagem=m.get("texto") or "",
                campo="matricula",
                valor=f"{linha.get('registro_cns')}/{linha.get('registro_matricula')}",
                fonte=f"certidão lida em {str(linha.get('lido_em') or '')[:10]} ({linha.get('modelo') or '?'})",
                regra_versao=regra_versao or linha.get("regras_versao"),
            )
        )
    return out
