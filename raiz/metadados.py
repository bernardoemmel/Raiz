"""Fichas Croissant 1.1/schema.org do Release, sem exemplos nem dados pessoais.

O baker lê os CSV do espelho; a distribuição aponta para o pacote publicado.
Cada CSV mantém seu próprio esquema, para que uma coluna nova não torne
ilegível a parte antiga do estado. A licença dos dados derivados não é
presumida a partir da licença do código ou das fontes.
"""

from __future__ import annotations

import copy
import csv
import re
from glob import escape
from pathlib import Path
from urllib.parse import quote, urlparse

REPO = "bernardoemmel/Raiz"
CONFORMIDADE = "http://mlcommons.org/croissant/1.1"
CONDICOES = (
    "Arquivo público para consulta. A licença de redistribuição dos dados derivados da Raíz ainda não foi definida; "
    "as fontes conservam os termos e créditos registrados no NOTICE.md. Disponibilidade pública não concede "
    "licença adicional."
)
_PROIBIDAS = re.compile(r"(^|_)(cpf|cnpj|nome|proprietario|titular|email|telefone)($|_)", re.I)


def _contexto() -> dict:
    contexto = {
        "@language": "pt-BR",
        "@vocab": "https://schema.org/",
        "sc": "https://schema.org/",
        "cr": "http://mlcommons.org/croissant/",
        "rai": "http://mlcommons.org/croissant/RAI/",
        "dct": "http://purl.org/dc/terms/",
        "conformsTo": "dct:conformsTo",
        "dataType": {"@id": "cr:dataType", "@type": "@vocab"},
    }
    for termo in (
        "citeAs",
        "recordSet",
        "field",
        "source",
        "fileSet",
        "fileObject",
        "extract",
        "column",
        "includes",
        "containedIn",
        "equivalentProperty",
        "fileProperty",
        "format",
        "isLiveDataset",
        "jsonPath",
        "key",
        "md5",
        "parentField",
        "path",
        "references",
        "regex",
        "repeated",
        "replace",
        "samplingRate",
        "separator",
        "subField",
        "transform",
    ):
        contexto[termo] = f"cr:{termo}"
    for termo in ("data", "examples"):
        contexto[termo] = {"@id": f"cr:{termo}", "@type": "@json"}
    return contexto


def _base(nome: str, url: str, descricao: str, repo: str) -> dict:
    return {
        "@context": _contexto(),
        "@type": "sc:Dataset",
        "@id": f"{url}#dataset",
        "name": nome,
        "description": descricao,
        "url": url,
        "conformsTo": CONFORMIDADE,
        "inLanguage": "pt-BR",
        "creator": {"@type": "sc:Organization", "name": "Raíz", "url": f"https://github.com/{repo}"},
        "publisher": {"@type": "sc:Organization", "name": "Raíz", "url": f"https://github.com/{repo}"},
        "conditionsOfAccess": CONDICOES,
        "isAccessibleForFree": True,
        "citation": f"https://github.com/{repo}/blob/main/NOTICE.md",
        "citeAs": f"Raíz. {nome}. {url}. Fontes e créditos: https://github.com/{repo}/blob/main/NOTICE.md.",
        "distribution": [],
        "recordSet": [],
    }


def ficha_arquivo(
    nome: str,
    url: str,
    sha256: str,
    tamanho: int | None = None,
    *,
    descricao: str | None = None,
    versao: str | None = None,
    atualizado_em: str | None = None,
    formato: str | list[str] = "application/octet-stream",
    repo: str = REPO,
) -> dict:
    """Ficha de um arquivo exato, inclusive artefatos sem estrutura tabular.

    O SHA é sempre dos bytes publicados; não aceita o hash abreviado da versão
    nem um hash do conteúdo descompactado no lugar do hash do pacote.
    """
    if not re.fullmatch(r"[a-fA-F0-9]{64}", sha256 or ""):
        raise ValueError(f"SHA-256 completo ausente ou inválido para {nome}")
    if urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc:
        raise ValueError(f"URL pública inválida para {nome}")
    ficha = _base(nome, url, descricao or f"Arquivo {nome} do conjunto de dados públicos da Raíz.", repo)
    arquivo = {
        "@id": "arquivo",
        "@type": "cr:FileObject",
        "name": nome,
        "contentUrl": url,
        "encodingFormat": formato,
        "sha256": sha256.lower(),
    }
    if tamanho is not None:
        if tamanho < 0:
            raise ValueError("tamanho do arquivo não pode ser negativo")
        arquivo["contentSize"] = str(tamanho)
    ficha["distribution"] = [arquivo]
    if versao:
        ficha["version"] = versao
    if atualizado_em:
        ficha["dateModified"] = atualizado_em
    return ficha


def validar(ficha: dict) -> None:
    """Valida o grafo com mlcroissant, sem materializar/baixar os registros."""
    import mlcroissant

    mlcroissant.Dataset(copy.deepcopy(ficha))


def croissant_uf(pasta: str | Path, uf: str, entrada: dict) -> dict:
    """Descreve os CSV diretos de ``pasta`` contidos em ``raiz_<UF>.tar.gz``.

    ``entrada`` traz url, sha256, tamanho, versao e atualizado_em do pacote
    efetivamente publicado; repo é opcional. Tipos vêm do croissant-baker
    0.8.3; o padrão não inclui exemplos/valores nem os arquivos .meta.json.
    """
    from croissant_baker.handlers.csv_handler import CSVHandler
    from croissant_baker.handlers.registry import HandlerRegistry
    from croissant_baker.metadata_generator import MetadataGenerator

    class CSVCompleto(CSVHandler):
        def _stream_csv(self, source, count_rows=False):
            # A inferência precisa enxergar também um decimal/texto que só
            # aparece após o primeiro bloco. O extract continua aceitando CSV
            # só com cabeçalho (município sem registros), sem erro de vazio.
            return super()._stream_csv(source, count_rows=True)

    pasta, uf = Path(pasta), uf.upper()
    if not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError("UF deve ter duas letras")
    arquivos = sorted(pasta.glob("*.csv"))
    if not arquivos:
        raise ValueError(f"nenhum CSV para descrever em {uf}")
    for arquivo in arquivos:
        with arquivo.open(encoding="utf-8-sig", newline="") as f:
            colunas = next(csv.reader(f), [])
        if not colunas or any(_PROIBIDAS.search(c.strip()) for c in colunas):
            raise ValueError(f"cabeçalho vazio ou coluna pessoal proibida em {arquivo.name}")

    ficha = ficha_arquivo(
        f"raiz_{uf}.tar.gz",
        entrada["url"],
        entrada.get("sha256"),
        entrada.get("tamanho"),
        descricao=(
            f"Tabelas da Raíz por imóvel e município de {uf}: cadastro ambiental, restrições territoriais e "
            "estimativas de restauração. Inferência de tipos pelo croissant-baker; não contém amostras de valores. "
            "O processamento pode estar parcial; consulte estados.json."
        ),
        versao=entrada.get("versao"),
        atualizado_em=entrada.get("atualizado_em"),
        formato=["application/x-tar", "application/gzip"],
        repo=entrada.get("repo", REPO),
    )
    baker = MetadataGenerator(
        str(pasta),
        name=f"Dados da Raíz — {uf}",
        description=ficha["description"],
        creators=[{"name": "Raíz"}],
        includes=[a.name for a in arquivos],
        max_workers=1,
        handlers=HandlerRegistry([CSVCompleto()]),
    )
    gerada = baker.generate_metadata()
    falhas = [f["path"] for f in baker.scan_report.to_dict()["files"] if f["outcome"] != "described"]
    if falhas:
        # Não copiar mensagens do parser, que podem trazer valores pessoais.
        raise ValueError(f"baker não descreveu todos os CSV: {', '.join(falhas)}")
    # mlcroissant 1.1.1 só lê propriedades de arquivo de um FileSet contido
    # num tar. FileObjects individuais permitem carregar de fato os CSV;
    # FileSets continuam descrevendo a organização por tabela.
    origens, tabelas = {}, {}
    for arquivo in sorted(gerada["distribution"], key=lambda d: d["name"]):
        nome = arquivo["name"]
        identificador = f"arquivos/{quote(nome, safe='_-')}"
        origens[arquivo["@id"]] = identificador
        ficha["distribution"].append(
            {
                "@type": "cr:FileObject",
                "@id": identificador,
                "name": nome,
                "contentUrl": f"{uf}/{nome}",
                "containedIn": {"@id": "arquivo"},
                "encodingFormat": "text/csv",
                "sha256": arquivo["sha256"],
                "contentSize": arquivo["contentSize"],
            }
        )
        tabela = re.sub(r"_\d{7}\.csv$", "", nome) if re.search(r"_\d{7}\.csv$", nome) else Path(nome).stem
        tabelas.setdefault(tabela, []).append(nome)
    for tabela, nomes in sorted(tabelas.items()):
        if all(re.fullmatch(re.escape(tabela) + r"_\d{7}\.csv", nome) for nome in nomes):
            inclui = [f"{uf}/{escape(tabela)}_*.csv"]
        else:
            inclui = [f"{uf}/{escape(nome)}" for nome in sorted(nomes)]
        ficha["distribution"].append(
            {
                "@type": "cr:FileSet",
                "@id": f"tabelas/{quote(tabela, safe='_-')}",
                "name": tabela,
                "description": f"Arquivos da tabela {tabela}; o esquema de cada CSV está em seu RecordSet.",
                "containedIn": {"@id": "arquivo"},
                "encodingFormat": "text/csv",
                "includes": inclui,
            }
        )
    for registro in sorted(gerada["recordSet"], key=lambda r: r["@id"]):
        campos = []
        for campo in registro["field"]:
            nome = campo["name"]
            tipo = "sc:Text" if nome == "cod_imovel" or nome.startswith("cod_") else campo["dataType"]
            tipo = [str(t) for t in tipo] if isinstance(tipo, list) else str(tipo)
            campos.append(
                {
                    "@type": "cr:Field",
                    "@id": campo["@id"],
                    "name": nome,
                    "description": f"Coluna {nome}; definição em docs/colunas.md quando documentada.",
                    "dataType": tipo,
                    "source": {
                        "fileObject": {"@id": origens[campo["source"]["fileObject"]["@id"]]},
                        "extract": {"column": nome},
                    },
                }
            )
        ficha["recordSet"].append(
            {
                "@type": "cr:RecordSet",
                "@id": registro["@id"],
                "name": registro["name"],
                "description": f"Registros de {registro['name']} em {uf}.",
                "field": campos,
            }
        )
    validar(ficha)
    return ficha


def croissant_release(indice: dict, repo: str = REPO, tag: str = "dados") -> dict:
    """Catálogo do Release com links apenas para fichas já publicadas.

    Cada ``estados[UF].croissant`` pode ser uma URL ou um objeto com url,
    sha256 e tamanho. Artefatos adicionais seguem o mesmo contrato no mapa
    ``indice['fichas']`` e ``estados[UF]['fichas']`` (nome do arquivo ->
    referência da sua ficha).
    """
    base = f"https://github.com/{repo}/releases/download/{quote(tag, safe='')}/"
    ficha = _base("Dados do Brasil — Raíz", base + "croissant.json", "Catálogo das fichas do Release dados.", repo)
    if indice.get("gerado_em"):
        ficha["dateModified"] = indice["gerado_em"]
    referencias = dict(indice.get("fichas") or {})
    for uf, entrada in sorted(indice.get("estados", {}).items()):
        referencias.update(entrada.get("fichas") or {})
        if entrada.get("croissant"):
            referencias[f"raiz_{uf}.tar.gz"] = entrada["croissant"]
    ficha["hasPart"] = []
    for nome, referencia in sorted(referencias.items()):
        referencia = {"url": referencia} if isinstance(referencia, str) else referencia
        url = referencia["url"]
        ficha["hasPart"].append({"@type": "sc:Dataset", "@id": url, "url": url, "name": nome})
        if referencia.get("sha256"):
            arquivo = ficha_arquivo(
                url.rsplit("/", 1)[-1],
                url,
                referencia["sha256"],
                referencia.get("tamanho"),
                formato="application/ld+json",
            )["distribution"][0]
            arquivo["@id"] = f"fichas/{quote(nome, safe='_-')}"
            ficha["distribution"].append(arquivo)
    return ficha
