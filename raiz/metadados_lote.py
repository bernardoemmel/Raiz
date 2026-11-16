"""Fichas privadas de TAR publicados: bytes exatos e esquemas dos CSV, sem amostras.

Os caminhos do pacote nunca são destinos de escrita. Após conferir todos os
membros, somente CSVs regulares são copiados com nomes locais gerados. Os demais
arquivos recebem hash, tamanho e formato, sem interpretação de seu conteúdo.
"""

from __future__ import annotations

import csv
import gc
import hashlib
import re
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from raiz import metadados as M

LIMITE_MEMBROS = 100_000
LIMITE_BYTES_PACOTE = 8 * 1024**3
LIMITE_BYTES_MEMBRO = 4 * 1024**3
LIMITE_BYTES_CONTEUDO = 16 * 1024**3
_BLOCO = 1024 * 1024
_FORMATOS = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".pdf": "application/pdf",
    ".html": "text/html",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".parquet": "application/vnd.apache.parquet",
    ".xml": "application/xml",
}


def _membros(tar: tarfile.TarFile) -> list[tarfile.TarInfo]:
    """Valida o inventário integral antes de abrir qualquer membro para copiar."""
    membros, nomes, regulares, total = [], set(), set(), 0
    for membro in tar:
        if len(membros) >= LIMITE_MEMBROS:
            raise ValueError("limite de membros do pacote excedido")
        nome = membro.name
        caminho = PurePosixPath(nome)
        if (
            not (membro.isfile() or membro.isdir())
            or membro.issparse()
            or (membro.isdir() and membro.size != 0)
            or caminho.is_absolute()
            or not caminho.parts
            or any(parte in {"", ".", ".."} for parte in nome.split("/"))
            or "\\" in nome
            or any(ord(c) < 32 or ord(c) == 127 for c in nome)
            or ":" in caminho.parts[0]
            or caminho.as_posix() != nome
            or nome in nomes
        ):
            raise ValueError("membro inválido no pacote privado")
        if not 0 <= membro.size <= LIMITE_BYTES_MEMBRO:
            raise ValueError("limite de bytes por membro excedido")
        total += membro.size
        if total > LIMITE_BYTES_CONTEUDO:
            raise ValueError("limite de bytes do conteúdo excedido")
        nomes.add(nome)
        membros.append(membro)
        if membro.isfile():
            regulares.add(nome)
    # Um arquivo regular não pode também ser ancestral de outro membro.
    if any(str(pai) in regulares for nome in nomes for pai in PurePosixPath(nome).parents if str(pai) != "."):
        raise ValueError("membros com caminhos conflitantes no pacote privado")
    return sorted((membro for membro in membros if membro.isfile()), key=lambda membro: membro.name)


def _sha256(arquivo: Path) -> str:
    h = hashlib.sha256()
    with arquivo.open("rb") as entrada:
        for bloco in iter(lambda: entrada.read(_BLOCO), b""):
            h.update(bloco)
    return h.hexdigest()


def _cabecalho(arquivo: Path) -> list[str]:
    try:
        with arquivo.open(encoding="utf-8-sig", newline="") as entrada:
            colunas = next(csv.reader(entrada), [])
    except (UnicodeError, csv.Error):
        raise ValueError("cabeçalho CSV inválido no pacote privado") from None
    if (
        not colunas
        or any(not coluna.strip() or M._PROIBIDAS.search(coluna.strip()) for coluna in colunas)
        or len(set(colunas)) != len(colunas)
    ):
        raise ValueError("cabeçalho vazio, duplicado ou coluna pessoal proibida no pacote privado")
    return colunas


def _esquemas(ficha: dict, pasta: Path, csvs: dict[str, dict]) -> None:
    quantidades = {nome: len(_cabecalho(pasta / nome)) for nome in csvs}
    isolado = sum(quantidades.values()) > M.LIMITE_CAMPOS
    for grupo in M._lotes(sorted(csvs), quantidades.__getitem__, M.LIMITE_CAMPOS):
        gerada = M._executar_lote(
            "baker",
            {
                "pasta": str(pasta.resolve()),
                "arquivos": grupo,
                "nome": "Tabelas privadas do lote Raíz",
                "descricao": ficha["description"],
            },
            isolado=isolado,
        )
        origens = {}
        for arquivo in gerada["distribution"]:
            origem = csvs[arquivo["name"]]
            if arquivo["sha256"] != origem["sha256"] or str(arquivo["contentSize"]) != origem["contentSize"]:
                raise ValueError("CSV da inferência diverge do membro publicado")
            origens[arquivo["@id"]] = origem
        for registro in gerada["recordSet"]:
            campos, fonte = [], None
            for campo in registro["field"]:
                origem = origens[campo["source"]["fileObject"]["@id"]]
                if fonte is not None and fonte != origem:
                    raise ValueError("esquema CSV mistura membros do pacote")
                fonte = origem
                registro_id = f"registros/{quote(origem['name'], safe='_-')}"
                nome = campo["name"]
                tipo = "sc:Text" if nome == "cod_imovel" or nome.startswith("cod_") else campo["dataType"]
                campos.append(
                    {
                        "@type": "cr:Field",
                        "@id": f"{registro_id}/campo-{quote(nome, safe='_-')}",
                        "name": nome,
                        "description": f"Coluna {nome}; definição em docs/colunas.md quando documentada.",
                        "dataType": [str(t) for t in tipo] if isinstance(tipo, list) else str(tipo),
                        "source": {"fileObject": {"@id": origem["@id"]}, "extract": {"column": nome}},
                    }
                )
            if fonte is None:
                raise ValueError("esquema CSV sem campos")
            ficha["recordSet"].append(
                {
                    "@type": "cr:RecordSet",
                    "@id": registro_id,
                    "name": fonte["name"],
                    "description": "Esquema do CSV publicado, sem amostras de valores.",
                    "field": campos,
                }
            )
        del gerada
        gc.collect()
    ficha["recordSet"].sort(key=lambda registro: registro["@id"])


def _validar(ficha: dict) -> None:
    """Reserva um nó para o TAR ancestral em cada partição de seus membros."""
    M._ids_globais(ficha)
    M._perfil_plano(ficha)
    registros = {}
    for registro in ficha["recordSet"]:
        origem = registro["field"][0]["source"]["fileObject"]["@id"]
        registros.setdefault(origem, []).append(registro)
    cabecalho = {k: v for k, v in ficha.items() if k not in {"distribution", "recordSet"}}
    raiz, *membros = ficha["distribution"]
    for grupo in M._lotes(membros, lambda _: 1, M.LIMITE_CAMPOS - 1):
        M.validar(
            {
                **cabecalho,
                "distribution": [raiz, *grupo],
                "recordSet": [registro for membro in grupo for registro in registros.get(membro["@id"], [])],
            }
        )
    if not membros:
        M.validar(ficha)


def croissant_tar_csv(pacote: Path, nome: str, entrada: dict) -> dict:
    """Descreve um TAR privado exato e todos seus membros regulares.

    ``entrada`` exige ``url`` privada e ``sha256`` do TAR; ``tamanho`` (ou
    ``bytes``), ``versao``, ``atualizado_em`` e ``repo_codigo`` são opcionais.
    O digest e o tamanho informado são conferidos antes da leitura do conteúdo.
    Não altera o pacote, não usa rede e não recalcula nenhum dado do produto.
    """
    pacote = Path(pacote)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", nome) or nome in {".", ".."}:
        raise ValueError("nome do pacote inválido")
    if entrada["url"].rsplit("/", 1)[-1] != nome:
        raise ValueError("nome do pacote diverge da URI privada")
    tamanho = pacote.stat().st_size
    if tamanho > LIMITE_BYTES_PACOTE:
        raise ValueError("limite de bytes do pacote excedido")
    ficha = M.ficha_arquivo(
        nome,
        entrada["url"],
        entrada.get("sha256"),
        tamanho,
        escopo="privado",
        descricao=(
            "Produto privado do lote Raíz. Hash e tamanho dos membros publicados; "
            "esquemas dos CSV inferidos pelo croissant-baker, sem amostras de valores. "
            "Os demais formatos são descritos como arquivos, sem esquema tabular presumido."
        ),
        versao=entrada.get("versao"),
        atualizado_em=entrada.get("atualizado_em"),
        formato=["application/x-tar", "application/gzip"],
        repo=entrada.get("repo_codigo", M.REPO),
    )
    for campo in ("tamanho", "bytes"):
        if campo in entrada and entrada[campo] != tamanho:
            raise ValueError("tamanho do pacote diverge da referência")
    if _sha256(pacote) != entrada["sha256"].lower():
        raise ValueError("SHA-256 do pacote diverge da referência")
    with tarfile.open(pacote, "r:gz") as tar:
        membros = _membros(tar)
        with tempfile.TemporaryDirectory(prefix="raiz-lote-csv-") as temporario:
            pasta, csvs = Path(temporario), {}
            for indice, membro in enumerate(membros):
                extensao = PurePosixPath(membro.name).suffix.lower()
                local = f"tabela_{indice:06d}.csv" if extensao == ".csv" else None
                destino = (pasta / local).open("xb") if local else None
                digest, lidos = hashlib.sha256(), 0
                try:
                    with tar.extractfile(membro) as fonte:
                        for bloco in iter(lambda: fonte.read(_BLOCO), b""):
                            lidos += len(bloco)
                            digest.update(bloco)
                            if destino:
                                destino.write(bloco)
                finally:
                    if destino:
                        destino.close()
                if lidos != membro.size:
                    raise ValueError("tamanho do membro diverge do inventário")
                arquivo = {
                    "@type": "cr:FileObject",
                    "@id": f"membros/{quote(membro.name, safe='_-')}",
                    "name": membro.name,
                    "contentUrl": membro.name,
                    "containedIn": {"@id": "arquivo"},
                    "encodingFormat": _FORMATOS.get(extensao, "application/octet-stream"),
                    "sha256": digest.hexdigest(),
                    "contentSize": str(lidos),
                }
                ficha["distribution"].append(arquivo)
                if local:
                    csvs[local] = arquivo
            _esquemas(ficha, pasta, csvs)
    _validar(ficha)
    return ficha
