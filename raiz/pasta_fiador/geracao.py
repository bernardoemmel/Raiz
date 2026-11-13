"""Duas saídas Jinja locais do mesmo retrato validado; não aceita modelo externo."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

from jinja2 import FileSystemLoader, StrictUndefined, select_autoescape
from jinja2.sandbox import SandboxedEnvironment

from raiz.prospeccao_acesso import ErroAcesso
from raiz.prospeccao_protecao import MarcaExportacao, validar_marca

from .esquema import Pasta
from .validacao import validar

_MODELOS = Path(__file__).with_name("modelos")
_ROTULOS = {
    "conferencia_concluida": "Conferência concluída",
    "documento_apresentado": "Documento apresentado",
    "nao_verificado": "Não verificado",
    "regeneracao_assistida": "Regeneração assistida",
    "semeadura_direta": "Semeadura direta",
    "plantio_total": "Plantio total",
    "agrofloresta": "Agrofloresta",
    "silvipastoril": "Silvipastoril",
    "area_elegivel": "Área elegível",
    "previsao": "Previsão",
    "preco": "Preço",
}


def _numero(valor):
    # Formatação sem float nem arredondamento de preço.
    return format(Decimal(valor), ",f").replace(",", "_").replace(".", ",").replace("_", ".")


def gerar(pacote: dict, marca: MarcaExportacao) -> bytes:
    validar_marca(marca)
    pasta = Pasta.model_validate(pacote["dados"])
    relatorio = validar(pasta)
    if not relatorio.pronto or not pacote["validacao"]["pronto"]:
        raise ErroAcesso(409, "A pasta tem campos ou documentos pendentes; geração interrompida.")
    dados = pasta.model_dump(mode="json")
    # Só campos conhecidos; um dicionário não pode acrescentar modelos, contatos ou instruções ao ZIP.
    contexto = {
        "dados": dados,
        "pasta_id": pacote["pasta_id"],
        "versao_id": pacote["versao_id"],
        "numero": pacote["numero"],
        "assinatura": pacote["assinatura"],
        "validacao": relatorio.model_dump(mode="json"),
        "previsoes": pacote["previsoes"],
        "protecao": marca.metadados(),
    }
    ambiente = SandboxedEnvironment(
        loader=FileSystemLoader(_MODELOS),
        undefined=StrictUndefined,
        autoescape=select_autoescape(["html"]),
        enable_async=False,
    )
    ambiente.globals.clear()
    ambiente.filters.update(numero=_numero, rotulo=lambda v: _ROTULOS.get(v, v.replace("_", " ")))
    arquivos = {}
    for publico in ("banco", "comprador"):
        arquivos[publico + ".html"] = ambiente.get_template(publico + ".html").render(**contexto).encode()
    arquivos["dados-conferidos.json"] = json.dumps(contexto, ensure_ascii=False, indent=2, allow_nan=False).encode()
    arquivos["validacao.json"] = json.dumps(
        {"protecao": contexto["protecao"], **contexto["validacao"]}, ensure_ascii=False, indent=2
    ).encode()
    manifesto = {
        "pasta_id": contexto["pasta_id"],
        "versao_id": contexto["versao_id"],
        "protecao": contexto["protecao"],
        "modelos_sha256": {
            nome: hashlib.sha256((_MODELOS / nome).read_bytes()).hexdigest()
            for nome in ("base.html", "banco.html", "comprador.html")
        },
        "arquivos": {nome: hashlib.sha256(b).hexdigest() for nome, b in arquivos.items()},
    }
    arquivos["manifesto.json"] = json.dumps(manifesto, ensure_ascii=False, indent=2).encode()
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", compression=zipfile.ZIP_DEFLATED) as zipado:
        for nome, conteudo in arquivos.items():
            zipado.writestr(nome, conteudo)
    return saida.getvalue()
