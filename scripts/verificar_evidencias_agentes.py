"""Portão de upload: aceita somente os arquivos sanitizados produzidos pelo runner.

Não publica, não move arquivos e não imprime conteúdo. Não substitui as projeções
da API nem o Presidio; impede credenciais e blocos de raciocínio bruto no artefato.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import yaml

_SEGREDO = re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}|\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
_LINK_TOKEN = re.compile(r"/(?:v1/)?(?:reservas/confirmar|cobrancas)/[A-Za-z0-9_-]{24,128}")
_OPACO = re.compile(r"__RAIZ_(?:THINKING|SIGNATURE|DATA)_SHA256_[a-f0-9]{64}__")
_NOME = re.compile(r"trace-[a-z0-9_]+-[1-4]\.json")
_CASSETE = re.compile(r"[a-z0-9_]+-[1-4]\.yaml")
FIXOS = {"relatorio.json", "execucoes.jsonl", "configuracao.json", "recursos.json"}


def _validar_conteudo(dado, *, chave_api: str, nivel: int = 0) -> None:
    if nivel > 40:
        raise ValueError("profundidade inesperada na evidência")
    if isinstance(dado, bytes):
        dado = dado.decode("utf-8")
    if isinstance(dado, str):
        if (chave_api and chave_api in dado) or _SEGREDO.search(dado) or _LINK_TOKEN.search(dado):
            raise ValueError("credencial ou token de link encontrado na evidência")
        if dado.startswith(("{", "[")):
            try:
                interno = json.loads(dado)
            except ValueError:
                return
            _validar_conteudo(interno, chave_api=chave_api, nivel=nivel + 1)
    elif isinstance(dado, list):
        for item in dado:
            _validar_conteudo(item, chave_api=chave_api, nivel=nivel + 1)
    elif isinstance(dado, dict):
        if dado.get("type") in {"thinking", "redacted_thinking"}:
            for chave, valor in dado.items():
                if chave != "type" and (not isinstance(valor, str) or not _OPACO.fullmatch(valor)):
                    raise ValueError("bloco de raciocínio ou assinatura em texto bruto")
        for chave, valor in dado.items():
            if str(chave).lower() in {"authorization", "x-api-key", "x-chave-api", "access_token", "refresh_token"}:
                raise ValueError("campo de credencial encontrado na evidência")
            _validar_conteudo(valor, chave_api=chave_api, nivel=nivel + 1)


def verificar(saida: Path, cassetes: Path, *, chave_api: str = "") -> int:
    arquivos = []
    if not saida.is_dir():
        raise ValueError("pasta de evidências ausente")
    for caminho in saida.iterdir():
        if caminho.resolve() == cassetes.resolve() and caminho.is_dir():
            continue
        if caminho.name not in FIXOS and not _NOME.fullmatch(caminho.name):
            raise ValueError("arquivo fora da lista de evidências autorizadas")
        arquivos.append(caminho)
    if cassetes.exists():
        for caminho in cassetes.iterdir():
            if not _CASSETE.fullmatch(caminho.name):
                raise ValueError("arquivo fora da lista de cassetes autorizadas")
            arquivos.append(caminho)
    if not arquivos:
        raise ValueError("nenhuma evidência para conferir")
    for caminho in arquivos:
        if caminho.is_symlink() or not caminho.is_file() or caminho.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("evidência não regular ou maior que o limite")
        bruto = caminho.read_text(encoding="utf-8")
        if caminho.suffix == ".jsonl":
            dados = [json.loads(linha) for linha in bruto.splitlines()]
        elif caminho.suffix == ".yaml":
            dados = yaml.safe_load(bruto)
            for interacao in dados.get("interactions", []):
                pedido, resposta = interacao.get("request", {}), interacao.get("response", {})
                if set(pedido.get("headers", {})) - {"content-type"}:
                    raise ValueError("cabeçalhos inesperados na cassette")
                if set(resposta.get("headers", {})) - {"content-type", "x-raiz-inferencia-segundos"}:
                    raise ValueError("cabeçalhos inesperados na cassette")
                corpo = json.loads(pedido["body"])
                if set(corpo) != {"raiz_requisicao_sha256"} or not re.fullmatch(
                    r"[a-f0-9]{64}", corpo["raiz_requisicao_sha256"]
                ):
                    raise ValueError("a cassette não pode conter o prompt bruto")
        else:
            dados = json.loads(bruto)
        if _NOME.fullmatch(caminho.name) and "mensagens" in dados:
            raise ValueError("trace exportável não deve conter o diálogo interno")
        _validar_conteudo(dados, chave_api=chave_api)
    return len(arquivos)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--saida", type=Path, required=True)
    p.add_argument("--cassetes", type=Path, required=True)
    a = p.parse_args(argv)
    try:
        quantidade = verificar(a.saida, a.cassetes, chave_api=os.environ.get("ANTHROPIC_API_KEY", ""))
    except Exception:
        print(json.dumps({"seguro_para_upload": False, "erro": "Evidência fora do contrato de sanitização."}))
        return 1
    print(json.dumps({"seguro_para_upload": True, "arquivos_conferidos": quantidade}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
