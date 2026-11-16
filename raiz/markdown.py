"""Representação Markdown das leituras da API, com negociação HTTP sem mudar a autorização.

O renderizador recebe a mesma projeção já limpa que a rota entrega em JSON. A ficha pública usa sua própria
lista de campos, em ``publico.py``: nunca se deve passar o registro bruto do banco para este módulo.
"""

from __future__ import annotations

import html
import math
import re

from fastapi.responses import Response

from raiz.privacidade import mascarar


def prefere_markdown(accept: str | None, padrao: str = "application/json") -> bool:
    """Só troca o formato quando há pedido explícito de Markdown com qualidade suficiente.

    Uma regra específica vale mais que um curinga, inclusive ``text/markdown;q=0``. Em empate entre dois pedidos
    explícitos preservamos JSON/HTML; ``text/markdown, */*`` escolhe Markdown. Sem Accept, mantém o contrato antigo.
    """
    faixas = []
    for item in (accept or "").lower().split(","):
        tipo, *parametros = (p.strip() for p in item.split(";"))
        qualidade = 1.0
        for parametro in parametros:
            chave, _, valor = parametro.partition("=")
            if chave.strip() == "q":
                try:
                    qualidade = float(valor)
                except ValueError:
                    qualidade = 0.0
                if not math.isfinite(qualidade) or not 0 <= qualidade <= 1:
                    qualidade = 0.0
        faixas.append((tipo, qualidade))

    def preferencia(tipo: str) -> tuple[float, int]:
        encontrado = (0.0, -1)
        for faixa, qualidade in faixas:
            especificidade = 2 if faixa == tipo else 1 if faixa == tipo.split("/")[0] + "/*" else 0
            if faixa not in (tipo, tipo.split("/")[0] + "/*", "*/*"):
                continue
            if especificidade > encontrado[1]:
                encontrado = (qualidade, especificidade)
        return encontrado

    md, original = preferencia("text/markdown"), preferencia(padrao)
    return md[1] == 2 and md[0] > 0 and (md[0] > original[0] or (md[0] == original[0] and md[1] > original[1]))


def texto(valor: object) -> str:
    """Texto literal: máscara de documento, sem HTML ou sintaxe de link vindos do dado."""
    if valor is None:
        return "não informado"
    if isinstance(valor, bool):
        return "sim" if valor else "não"
    if isinstance(valor, float) and not math.isfinite(valor):
        return "não informado"
    valor = html.escape(mascarar(str(valor)), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+|])", r"\\\1", valor).replace("\n", " ").replace("\r", " ")


_ROTULOS = {
    "cod_imovel": "Código do CAR",
    "cod_ibge": "Código IBGE",
    "cod_municipio_ibge": "Código IBGE do município",
    "uf": "UF",
    "ha": "Área (ha)",
    "carbono_ha": "Área para carbono (ha)",
    "n_imoveis": "Número de imóveis",
    "municipio": "Município",
    "situacao": "Situação",
    "versao_dado": "Versão dos dados",
    "para_quem_restaura": "Para quem restaura",
}


def documento(dado: object, titulo: str) -> str:
    """Campos da mesma resposta JSON em texto estruturado, sem arquivos ou rede adicionais."""
    partes = [f"# {texto(titulo)}", ""]

    def bloco(valor: object, nivel: int = 2) -> None:
        if isinstance(valor, dict):
            for chave, item in valor.items():
                if str(chave).startswith("_"):
                    continue
                rotulo = texto(_ROTULOS.get(chave, str(chave).replace("_", " ").capitalize()))
                if isinstance(item, (dict, list)):
                    partes.extend(["", f"{'#' * min(nivel, 6)} {rotulo}", ""])
                    bloco(item, nivel + 1)
                else:
                    partes.append(f"- **{rotulo}:** {texto(item)}")
            partes.append("")
        elif isinstance(valor, list):
            if not valor:
                partes.extend(["Nenhum registro.", ""])
            for indice, item in enumerate(valor, 1):
                if isinstance(item, (dict, list)):
                    partes.extend([f"{'#' * min(nivel, 6)} Registro {indice}", ""])
                    bloco(item, nivel + 1)
                else:
                    partes.append(f"- {texto(item)}")
            partes.append("")
        else:
            partes.extend([texto(valor), ""])

    bloco(dado)
    return "\n".join(partes).rstrip() + "\n"


def resposta(conteudo: str) -> Response:
    return Response(conteudo, media_type="text/markdown", headers={"Vary": "Accept"})
