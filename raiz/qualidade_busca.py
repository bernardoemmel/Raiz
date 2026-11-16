"""Portão do Release busca: SQLite, CSV e Markdown validados antes do primeiro upload.

O contrato contém somente registros/editais públicos. Identificação pessoal em
texto, documento, contato e segredo bloqueiam o lote; um rótulo de autoria não
comprova origem pública. O SQLite aprovado é recomposto para retirar restos apagados.
Não acessa rede nem publica arquivos. Falhas mostram apenas a regra violada.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

from raiz.privacidade import cnpj_valido, cpf_valido, mascarar

DOCUMENTO_URL = re.compile(
    r"(?<![A-Z0-9])(?:[0-9A-Z]{2}\.[0-9A-Z]{3}\.[0-9A-Z]{3}/[0-9A-Z]{4}-\d{2}|"
    r"\d{3}\.\d{3}\.\d{3}-\d{2}|[0-9A-Z]{12}\d{2}|\d{11})(?![A-Z0-9])",
    re.I,
)

COLUNAS_ITEM = (
    "fonte",
    "chave",
    "titulo",
    "url",
    "data",
    "orgao",
    "tipo",
    "marca",
    "detalhe_json",
    "primeira_vez",
    "ultima_vez",
    "ultima_mudanca",
)
COLUNAS_RODADA = ("id", "iniciada_em", "terminada_em", "resumo_json")
COLUNAS_CSV = ("tipo", "fonte", "chave", "titulo", "url", "data", "orgao", "marca", "marca_antes", "resumo")
DETALHES = {
    "verra": {"situacao", "categoria", "estado"},
    "sfb": {"lista", "termo"},
    "ideflor_bio": {"pagina"},
    "dou": {"secao", "tipo_ato", "edicao", "pagina", "termo", "resumo"},
}
_CONTATO = re.compile(r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}|(?:\+55\s*)?\(?\d{2}\)?[ -]?\d{4,5}[- ]\d{4}")
_SEGREDO = re.compile(
    r"(?i)(?:bearer\s+[\w.-]{8,}|(?:token|api[_-]?key|secret|password|senha)\s*[\"']?\s*[=:]\s*[\"']?[^\s\"',}]+"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:ghp_|github_pat_|sk_live_)[\w]+)"
)
_DONO = re.compile(r"(?i)\b(?:propriet[aá]ri[oa]|titular|dono|possuidor|benefici[aá]ri[oa])\s*(?:[:=]|(?:da|do|de)\s)")
_NOME_ARQUIVO = re.compile(r"novidades_(\d{4}-\d{2}-\d{2})\.(md|csv)")


class ErroQualidadeBusca(ValueError):
    """Mensagem publicável, sem valores dos arquivos."""


def _falhar(regra: str) -> None:
    raise ErroQualidadeBusca(f"publicação da busca bloqueada: {regra}; valores omitidos")


def _normalizar(texto: str) -> str:
    for _ in range(4):
        novo = html.unescape(unquote(texto))
        if novo == texto:
            return texto
        texto = novo
    if html.unescape(unquote(texto)) != texto:
        _falhar("texto com codificação excessiva")
    return texto


@lru_cache(maxsize=10000)
def _texto(texto: str, editorial: bool = False) -> None:
    texto = _normalizar(texto)
    if mascarar(texto) != texto or _CONTATO.search(texto) or _SEGREDO.search(texto):
        _falhar("documento, contato ou segredo")
    if not editorial or not texto:
        return
    from raiz.logs_seguros import sanitizar_log

    # Um rótulo editorial não comprova que o nome é de autor, e não do titular.
    if _DONO.search(texto) and sanitizar_log(texto) != texto:
        _falhar("identificação de dono em texto público")
    if sanitizar_log(texto) != texto:
        _falhar("texto pessoal ou não verificável")


def _string(valor, *, obrigatorio: bool = False, editorial: bool = False) -> None:
    if valor is None and not obrigatorio:
        return
    if not isinstance(valor, str) or (obrigatorio and not valor.strip()):
        _falhar("campo textual fora do contrato")
    _texto(valor, editorial)


def _data(valor, *, horario: bool = False, obrigatorio: bool = False) -> None:
    _string(valor, obrigatorio=obrigatorio)
    if not valor:
        return
    try:
        if horario:
            dt.datetime.fromisoformat(valor)
        else:
            dt.date.fromisoformat(valor)
    except ValueError:
        _falhar("data fora do contrato")


def _url(valor) -> None:
    _string(valor)
    if not valor:
        return
    try:
        partes = urlsplit(valor)
        if partes.scheme not in {"http", "https"} or not partes.hostname or partes.username or partes.password:
            _falhar("link fora do contrato público")
        _ = partes.port
    except ValueError:
        _falhar("link inválido")
    claro = _normalizar(valor)
    if any("." in d or cpf_valido(d) or cnpj_valido(d) for d in DOCUMENTO_URL.findall(claro)):
        _falhar("documento no link público")
    if re.search(r"(?i)(?:/|[-_])(?:proprietario|titular|dono|contato|cpf|cnpj|email|nome)(?:/|[-_=])", claro):
        _falhar("identificação pessoal no caminho do link")
    _texto(re.sub(r"[-_/]", " ", urlsplit(claro).path), editorial=True)
    if re.search(r"(?i)(?:[?&])(?:nome|cpf|cnpj|contato|email|telefone|owner|proprietario)=", _normalizar(valor)):
        _falhar("identificação pessoal no link")


def _json(texto: str, campos: set[str]) -> dict:
    try:

        def sem_repetidas(pares):
            d = {}
            for chave, valor in pares:
                if chave in d:
                    _falhar("chave JSON repetida")
                d[chave] = valor
            return d

        dado = json.loads(texto, object_pairs_hook=sem_repetidas)
    except (ValueError, TypeError):
        _falhar("JSON ilegível")
    if not isinstance(dado, dict) or not set(dado) <= campos:
        _falhar("JSON fora do contrato público")
    return dado


def _fontes() -> set[str]:
    from raiz.documentos.busca.fontes import config

    cfg = config()
    return set(DETALHES) | {p.get("nome") or p["url"] for p in cfg.get("paginas", [])}


def _item(item: dict, fontes: set[str]) -> dict:
    if item["fonte"] not in fontes or item["tipo"] not in {"projeto", "edital", "publicacao", "noticia", "documento"}:
        _falhar("fonte ou tipo fora do contrato")
    for chave in ("fonte", "chave", "titulo"):
        _string(item[chave], obrigatorio=True, editorial=chave == "titulo")
    for chave in ("orgao", "marca"):
        _string(item[chave], editorial=True)
    _url(item["url"])
    if item["fonte"] == "verra":
        if not re.fullmatch(r"\d{1,9}", item["chave"]):
            _falhar("identificador Verra fora do contrato")
    elif item["fonte"] == "dou":
        if not re.fullmatch(r"[A-Za-z0-9_-]+", item["chave"]) or not (item["url"] or "").endswith("/" + item["chave"]):
            _falhar("identificador DOU fora do contrato")
    elif item["chave"] != item["url"]:
        _falhar("identificador da página diferente do link")
    _data(item["data"])
    for chave in ("primeira_vez", "ultima_vez", "ultima_mudanca"):
        _data(item[chave], horario=True, obrigatorio=chave != "ultima_mudanca")
    detalhe = _json(item["detalhe_json"] or "{}", DETALHES.get(item["fonte"], {"pagina"}))
    for chave, valor in detalhe.items():
        if isinstance(valor, int | float) and not isinstance(valor, bool) and chave in {"edicao", "pagina"}:
            if not float(valor).is_integer() or valor < 0:
                _falhar("número de edição ou página inválido")
            _texto(str(int(valor)))
        elif isinstance(valor, list) and chave == "categoria":
            for categoria in valor:
                _string(categoria, editorial=True)
        else:
            _string(valor, editorial=True)
    return detalhe


def _sqlite(caminho: Path, fontes: set[str]) -> tuple[dict, int]:
    # Nem os nomes de tabelas nem consultas SQL vêm do arquivo auditado.
    uri = caminho.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.execute("pragma trusted_schema=off")
        if con.execute("pragma quick_check").fetchall() != [("ok",)]:
            _falhar("SQLite inválido")
        from raiz.documentos.busca.semanal import ESQUEMA

        def normalizar_sql(sql):
            return " ".join((sql or "").lower().replace("if not exists ", "").split())

        esperado = {normalizar_sql(sql) for sql in ESQUEMA.split(";") if sql.strip()}
        declarado = {normalizar_sql(r[0]) for r in con.execute("select sql from sqlite_schema where type='table'")}
        if declarado != esperado:
            _falhar("definição SQLite fora do contrato")
        objetos = con.execute("select type, name from sqlite_schema").fetchall()
        if set(objetos) != {("table", "item"), ("table", "rodada"), ("index", "sqlite_autoindex_item_1")}:
            _falhar("esquema SQLite fora do contrato")
        if tuple(r[1] for r in con.execute("pragma table_info(item)")) != COLUNAS_ITEM:
            _falhar("colunas SQLite de item fora do contrato")
        if tuple(r[1] for r in con.execute("pragma table_info(rodada)")) != COLUNAS_RODADA:
            _falhar("colunas SQLite de rodada fora do contrato")
        itens = {}
        for linha in con.execute("select * from item"):
            item = dict(zip(COLUNAS_ITEM, linha, strict=True))
            detalhe = _item(item, fontes)
            itens[item["fonte"], item["chave"]] = item | {"resumo": detalhe.get("resumo") or ""}
        rodadas = 0
        for rid, inicio, fim, resumo in con.execute("select * from rodada"):
            if not isinstance(rid, int) or rid < 1:
                _falhar("identificador da rodada inválido")
            _texto(str(rid))
            _data(inicio, horario=True, obrigatorio=True)
            _data(fim, horario=True, obrigatorio=True)
            for valores in _json(resumo, fontes).values():
                if not isinstance(valores, dict) or set(valores) != {"itens", "via", "erro"}:
                    _falhar("resumo da rodada fora do contrato")
                if type(valores["itens"]) is not int or valores["itens"] < 0:
                    _falhar("contagem da rodada inválida")
                _texto(str(valores["itens"]))
                if valores["via"] not in {None, "direto", "firecrawl", "direto,firecrawl"}:
                    _falhar("via de consulta fora do contrato")
                _string(valores["erro"], editorial=True)
            rodadas += 1
    return itens, rodadas


def _csv(caminho: Path, itens: dict) -> int:
    with caminho.open(newline="", encoding="utf-8") as arquivo:
        leitor = csv.DictReader(arquivo)
        if tuple(leitor.fieldnames or ()) != COLUNAS_CSV:
            _falhar("colunas CSV fora do contrato")
        vistos = set()
        for linha in leitor:
            if None in linha or any(v is None for v in linha.values()):
                _falhar("linha CSV incompleta")
            chave = (linha["fonte"], linha["chave"])
            if chave not in itens or chave in vistos or linha["tipo"] not in {"novo", "mudou"}:
                _falhar("novidade sem correspondência única no estado")
            for nome, valor in linha.items():
                _texto(valor, nome in {"titulo", "orgao", "marca", "marca_antes", "resumo"})
                if nome not in {"tipo", "marca_antes"} and valor != (itens[chave][nome] or ""):
                    _falhar("CSV divergente do estado")
            vistos.add(chave)
        return len(vistos)


def validar(sqlite: Path, markdown: Path, csv_path: Path) -> dict[str, int]:
    """Lê o pacote inteiro; nenhum arquivo é alterado quando uma validação falha."""
    if sqlite.name != "busca.sqlite":
        _falhar("nome do estado inválido")
    datas = []
    for caminho, extensao in ((markdown, "md"), (csv_path, "csv")):
        nome = _NOME_ARQUIVO.fullmatch(caminho.name)
        if not nome or nome[2] != extensao:
            _falhar("nome do relatório inválido")
        _data(nome[1])
        datas.append(nome[1])
    if datas[0] != datas[1]:
        _falhar("relatórios de datas diferentes")
    for caminho in (sqlite, markdown, csv_path):
        if not caminho.is_file() or caminho.is_symlink() or caminho.stat().st_size > 100 * 1024**2:
            _falhar("arquivo ausente, link ou maior que 100 MiB")
    if any(Path(str(sqlite) + sufixo).exists() for sufixo in ("-wal", "-shm", "-journal")):
        _falhar("SQLite com transação ou arquivo auxiliar pendente")
    itens, rodadas = _sqlite(sqlite, _fontes())
    novidades = _csv(csv_path, itens)
    texto = markdown.read_text(encoding="utf-8")
    _texto(texto, editorial=True)
    data = dt.date.fromisoformat(datas[0]).strftime("%d/%m/%Y")
    if not texto.startswith(f"# Registros e editais novos, semana de {data}\n") or not texto.rstrip().endswith(
        "Fontes públicas. Gerado por `python -m raiz.documentos busca semanal`."
    ):
        _falhar("Markdown fora do contrato")
    return {"arquivos": 3, "itens": len(itens), "rodadas": rodadas, "novidades": novidades}


def preparar(sqlite: Path, markdown: Path, csv_path: Path) -> dict[str, int]:
    """Valida tudo e recompõe só o SQLite, retirando páginas e conteúdo obsoletos."""
    resultado = validar(sqlite, markdown, csv_path)
    with tempfile.TemporaryDirectory(prefix=".busca-publica-", dir=sqlite.parent) as pasta:
        destino = Path(pasta) / "busca.sqlite"
        with closing(sqlite3.connect(sqlite.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            con.execute("pragma trusted_schema=off")
            con.execute("vacuum into ?", (str(destino),))
        os.chmod(destino, sqlite.stat().st_mode & 0o777)
        os.replace(destino, sqlite)
    return resultado


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sqlite", type=Path)
    parser.add_argument("markdown", type=Path)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    try:
        resultado = preparar(args.sqlite, args.markdown, args.csv)
    except Exception as exc:
        mensagem = (
            str(exc) if isinstance(exc, ErroQualidadeBusca) else "publicação da busca bloqueada: arquivo ilegível"
        )
        parser.exit(1, mensagem + "\n")
    print(json.dumps(resultado, ensure_ascii=False))


if __name__ == "__main__":
    main()
