"""Fichas Croissant 1.1/schema.org do Release, sem exemplos nem dados pessoais.

O baker lê os CSV do espelho; a distribuição aponta para o pacote publicado.
Cada CSV mantém seu próprio esquema, para que uma coluna nova não torne
ilegível a parte antiga do estado. A licença dos dados derivados não é
presumida a partir da licença do código ou das fontes.
"""

from __future__ import annotations

import copy
import csv
import gc
import json
import os
import re
import subprocess
import sys
import tempfile
from glob import escape
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

REPO = "bernardoemmel/Raiz"
CONFORMIDADE = "http://mlcommons.org/croissant/1.1"
CONDICOES = (
    "Arquivo público para consulta. A licença de redistribuição dos dados derivados da Raíz ainda não foi definida; "
    "as fontes conservam os termos e créditos registrados no NOTICE.md. Disponibilidade pública não concede "
    "licença adicional."
)
_PROIBIDAS = re.compile(r"(^|_)(cpf|cnpj|nome|proprietario|titular|email|telefone)($|_)", re.I)
LIMITE_CAMPOS = 1500
LIMITE_NOS = 6000


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


class _ForaDoPerfil(ValueError):
    """Estrutura genérica que requer validação integral, se pequena."""


def _objetos(valor):
    if isinstance(valor, dict):
        yield valor
        for chave, filho in valor.items():
            if chave != "@context":
                yield from _objetos(filho)
    elif isinstance(valor, list):
        for filho in valor:
            yield from _objetos(filho)


def _ids_globais(ficha: dict) -> int:
    """Não deixa a divisão em lotes ocultar colisões entre definições."""
    ids, nos = set(), 0
    contexto = ficha.get("@context")
    jsons = {
        k
        for k, v in (contexto.items() if isinstance(contexto, dict) else [])
        if isinstance(v, dict) and v.get("@type") == "@json"
    }

    def contexto_local(valor):
        if not isinstance(valor, dict) or any(k in valor for k in ("@import", "@propagate")):
            raise ValueError("contexto remoto não é permitido na validação estática")
        for chave, filho in valor.items():
            if chave == "@context":
                raise ValueError("contexto remoto ou aninhado não é permitido na validação estática")
            elif isinstance(filho, dict):
                contexto_local(filho)

    def visitar(valor, literal=False):
        nonlocal nos
        if isinstance(valor, list):
            for filho in valor:
                visitar(filho, literal)
        elif isinstance(valor, dict):
            nos += 1
            if not literal:
                if "@context" in valor:
                    if valor is not ficha:
                        raise ValueError("contexto remoto ou aninhado não é permitido na validação estática")
                    contexto_local(valor["@context"])
                identificador = valor.get("@id")
                if identificador is not None and not isinstance(identificador, str):
                    raise ValueError("identificador Croissant inválido")
                if identificador is not None and set(valor) != {"@id"}:
                    # JSON-LD normaliza ./ e ../ nas IRIs relativas.
                    canonico = urljoin("https://raiz.invalid/cr_base_iri/", identificador)
                    if canonico in ids:
                        raise ValueError("identificador Croissant definido mais de uma vez")
                    ids.add(canonico)
            for chave, filho in valor.items():
                if chave != "@context" or literal:
                    visitar(filho, literal or chave in jsons)

    visitar(ficha)
    return nos


def _referencia(valor) -> str:
    if not isinstance(valor, dict) or set(valor) != {"@id"} or not isinstance(valor["@id"], str):
        raise _ForaDoPerfil("referência estrutural fora do perfil plano")
    return valor["@id"]


def _identificador_local(valor) -> None:
    if (
        not isinstance(valor, str)
        or not re.fullmatch(r"[A-Za-z0-9_%.+/-]+", valor)
        or any(p in {"", ".", ".."} for p in valor.split("/"))
        or re.search(r"%(?![0-9A-Fa-f]{2})", valor)
    ):
        raise _ForaDoPerfil("identificador não canônico fora do perfil plano")


def _literais(objeto: dict, estruturas: set[str]) -> None:
    for chave, valor in objeto.items():
        if chave in estruturas:
            continue
        valores = valor if isinstance(valor, list) else [valor]
        if any(not isinstance(v, (str, int, float, bool, type(None))) for v in valores):
            raise _ForaDoPerfil("valor estruturado fora do perfil plano")


def _perfil_plano(ficha: dict):
    """Confere todas as relações antes de construir qualquer grafo parcial.

    Somente o perfil gerado aqui é particionado. Junções, campos aninhados e
    contextos alternativos precisam do grafo integral; não são ignorados.
    """
    permitidos = {
        "@context",
        "@type",
        "@id",
        "name",
        "description",
        "url",
        "conformsTo",
        "inLanguage",
        "creator",
        "publisher",
        "conditionsOfAccess",
        "isAccessibleForFree",
        "citation",
        "citeAs",
        "distribution",
        "recordSet",
        "version",
        "dateModified",
        "datePublished",
    }
    if ficha.get("@context") != _contexto() or set(ficha) - permitidos:
        raise _ForaDoPerfil("contexto ou metadados fora do perfil plano")
    _literais(ficha, {"@context", "distribution", "recordSet", "creator", "publisher"})
    for chave in ("creator", "publisher"):
        organizacao = ficha.get(chave)
        if organizacao is not None:
            if not isinstance(organizacao, dict) or set(organizacao) - {"@type", "name", "url"}:
                raise _ForaDoPerfil("organização fora do perfil plano")
            _literais(organizacao, set())
    for objeto in _objetos(ficha):
        if objeto is not ficha and any(k.startswith("@") and k not in {"@id", "@type"} for k in objeto):
            raise _ForaDoPerfil("expansão JSON-LD fora do perfil plano")
    distribuicoes = ficha.get("distribution", [])
    registros = ficha.get("recordSet", [])
    if not isinstance(distribuicoes, list) or not isinstance(registros, list):
        raise _ForaDoPerfil("distribution e recordSet devem ser listas")
    dist, pais = {}, {}
    for d in distribuicoes:
        if not isinstance(d, dict) or set(d) - {
            "@id",
            "@type",
            "name",
            "description",
            "contentUrl",
            "encodingFormat",
            "sha256",
            "md5",
            "contentSize",
            "containedIn",
            "includes",
        }:
            raise _ForaDoPerfil("distribuição fora do perfil plano")
        _identificador_local(d.get("@id"))
        _literais(d, {"containedIn"})
        if not isinstance(d.get("@type"), str) or d["@type"] not in {"cr:FileObject", "cr:FileSet"}:
            raise _ForaDoPerfil("tipo de distribuição fora do perfil plano")
        dist[d["@id"]] = d
        if "containedIn" in d:
            pais[d["@id"]] = _referencia(d["containedIn"])
    for pai in pais.values():
        if pai not in dist or dist[pai].get("@type") != "cr:FileObject":
            raise ValueError("containedIn não aponta para FileObject definido")

    def fechar(ids):
        out = set()
        for identificador in ids:
            caminho = set()
            while identificador is not None:
                if identificador in caminho:
                    raise ValueError("ciclo em containedIn")
                caminho.add(identificador)
                out.add(identificador)
                identificador = pais.get(identificador)
        return out

    for identificador in dist:
        fechar([identificador])
    fontes = {}
    for r in registros:
        if not isinstance(r, dict) or set(r) - {"@id", "@type", "name", "description", "field"}:
            raise _ForaDoPerfil("RecordSet fora do perfil plano")
        _identificador_local(r.get("@id"))
        _literais(r, {"field"})
        if r.get("@type") != "cr:RecordSet" or not isinstance(r.get("field"), list):
            raise _ForaDoPerfil("RecordSet fora do perfil plano")
        dependencias = set()
        for campo in r["field"]:
            if not isinstance(campo, dict) or set(campo) - {
                "@id",
                "@type",
                "name",
                "description",
                "dataType",
                "source",
            }:
                raise _ForaDoPerfil("Field fora do perfil plano")
            _identificador_local(campo.get("@id"))
            _literais(campo, {"source"})
            origem = campo.get("source")
            if (
                campo.get("@type") != "cr:Field"
                or not isinstance(origem, dict)
                or set(origem) != {"fileObject", "extract"}
            ):
                raise _ForaDoPerfil("origem do campo fora do perfil plano")
            extrair = origem["extract"]
            if not isinstance(extrair, dict) or set(extrair) != {"column"} or not isinstance(extrair["column"], str):
                raise _ForaDoPerfil("extração fora do perfil plano")
            identificador = _referencia(origem["fileObject"])
            if identificador not in dist or dist[identificador].get("@type") != "cr:FileObject":
                raise ValueError("source.fileObject não aponta para FileObject definido")
            dependencias.add(identificador)
        fontes[r["@id"]] = fechar(dependencias)
    return dist, registros, fontes, fechar


def _lotes(itens, peso, limite):
    lote, total = [], 0
    for item in itens:
        n = max(1, peso(item))
        if n > limite:
            raise ValueError("um único elemento excede o limite de campos da validação")
        if lote and total + n > limite:
            yield lote
            lote, total = [], 0
        lote.append(item)
        total += n
    if lote:
        yield lote


def _executar_lote(tarefa: str, dados: dict, *, isolado: bool):
    """Um filho síncrono por grafo: seu término libera também os alocadores nativos.

    stdout/stderr de bibliotecas podem conter valores de CSV inválido. O canal
    de retorno é um JSON local; erros atravessam somente como classe/código.
    """
    if not isolado:
        return _processar_lote(tarefa, copy.deepcopy(dados))
    with tempfile.TemporaryDirectory(prefix="raiz-croissant-") as temporario:
        pedido, resposta = Path(temporario) / "pedido.json", Path(temporario) / "resposta.json"
        pedido.write_text(json.dumps({"tarefa": tarefa, "dados": dados}, ensure_ascii=False), encoding="utf-8")
        processo = subprocess.run(
            [sys.executable, "-m", "raiz.metadados", str(pedido), str(resposta)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if processo.returncode or not resposta.exists():
            raise ValueError("processo de metadados não concluiu o lote")
        resultado = json.loads(resposta.read_text(encoding="utf-8"))
        if not resultado["ok"]:
            codigo = "baker não descreveu todos os CSV do lote" if tarefa == "baker" else "ficha Croissant inválida"
            raise ValueError(f"{codigo} ({resultado['erro']})")
        return resultado["valor"]


def _processar_lote(tarefa: str, dados: dict):
    if tarefa == "validar":
        import mlcroissant

        mlcroissant.Dataset(dados)
        return None
    if tarefa != "baker":
        raise ValueError("tarefa de metadados desconhecida")
    from croissant_baker.handlers.csv_handler import CSVHandler
    from croissant_baker.handlers.registry import HandlerRegistry
    from croissant_baker.metadata_generator import MetadataGenerator

    class CSVCompleto(CSVHandler):
        def _stream_csv(self, source, count_rows=False):
            # A inferência lê inclusive decimais/texto depois do primeiro bloco.
            # O extract continua aceitando CSV somente com cabeçalho.
            return super()._stream_csv(source, count_rows=True)

    # A pasta de links contém somente este lote. Evita varrer milhares de CSV
    # para cada grupo; nomes, bytes e IDs do baker continuam os mesmos.
    with tempfile.TemporaryDirectory(prefix="raiz-baker-") as temporario:
        for nome in dados["arquivos"]:
            os.symlink(Path(dados["pasta"]) / nome, Path(temporario) / nome)
        baker = MetadataGenerator(
            temporario,
            name=dados["nome"],
            description=dados["descricao"],
            creators=[{"name": "Raíz"}],
            max_workers=1,
            handlers=HandlerRegistry([CSVCompleto()]),
        )
        gerada = baker.generate_metadata()
        if any(f["outcome"] != "described" for f in baker.scan_report.to_dict()["files"]):
            raise ValueError("baker não descreveu todos os CSV do lote")
        return gerada


def _validar_parte(ficha: dict, *, isolado: bool = False) -> None:
    try:
        _executar_lote("validar", ficha, isolado=isolado)
    finally:
        gc.collect()


def validar(ficha: dict) -> None:
    """Valida com mlcroissant em grafos limitados, preservando a ficha integral.

    Cada RecordSet entra inteiro uma vez; cada distribuição, mesmo sem uso,
    entra em algum lote com todos os ancestrais. Invariantes globais são
    verificadas antes. Fichas pequenas genéricas de contexto estático usam o validador integral;
    fichas grandes com relações não suportadas falham explicitamente.
    """
    nos = _ids_globais(ficha)
    try:
        dist, registros, fontes, fechar = _perfil_plano(ficha)
    except _ForaDoPerfil as ex:
        if nos > LIMITE_NOS:
            raise ValueError("ficha grande fora do perfil particionável; validação integral recusada") from ex
        _validar_parte(ficha)
        return
    # Materializa só os grupos de referências, nunca um segundo grafo completo.
    grupos = list(_lotes(registros, lambda r: len(r["field"]), LIMITE_CAMPOS))
    cabecalho = {k: v for k, v in ficha.items() if k not in {"distribution", "recordSet"}}
    validadas = set()
    for grupo in grupos:
        ids = set().union(*(fontes[r["@id"]] for r in grupo))
        if len(ids) > LIMITE_CAMPOS:
            raise ValueError("fechamento de distribuições excede o limite da validação")
        parte = {**cabecalho, "distribution": [d for k, d in dist.items() if k in ids], "recordSet": grupo}
        _validar_parte(parte, isolado=nos > LIMITE_NOS)
        validadas.update(ids)
    restantes = [k for k in dist if k not in validadas]
    for grupo in _lotes(restantes, lambda _: 1, LIMITE_CAMPOS):
        ids = fechar(grupo)
        if len(ids) > LIMITE_CAMPOS:
            raise ValueError("fechamento de distribuições excede o limite da validação")
        _validar_parte(
            {**cabecalho, "distribution": [d for k, d in dist.items() if k in ids], "recordSet": []},
            isolado=nos > LIMITE_NOS,
        )
    if not registros and not dist:
        _validar_parte(ficha)


def croissant_uf(pasta: str | Path, uf: str, entrada: dict) -> dict:
    """Descreve os CSV diretos de ``pasta`` contidos em ``raiz_<UF>.tar.gz``.

    ``entrada`` traz url, sha256, tamanho, versao e atualizado_em do pacote
    efetivamente publicado; repo é opcional. Tipos vêm do croissant-baker
    0.8.3; o padrão não inclui exemplos/valores nem os arquivos .meta.json.
    """
    pasta, uf = Path(pasta), uf.upper()
    if not re.fullmatch(r"[A-Z]{2}", uf):
        raise ValueError("UF deve ter duas letras")
    arquivos = sorted(pasta.glob("*.csv"))
    if not arquivos:
        raise ValueError(f"nenhum CSV para descrever em {uf}")
    quantidades = {}
    for arquivo in arquivos:
        with arquivo.open(encoding="utf-8-sig", newline="") as f:
            colunas = next(csv.reader(f), [])
        if not colunas or any(_PROIBIDAS.search(c.strip()) for c in colunas):
            raise ValueError(f"cabeçalho vazio ou coluna pessoal proibida em {arquivo.name}")
        quantidades[arquivo] = len(colunas)

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
    tabelas = {}
    for grupo in _lotes(arquivos, quantidades.__getitem__, LIMITE_CAMPOS):
        gerada = _executar_lote(
            "baker",
            {
                "pasta": str(pasta.resolve()),
                "arquivos": [a.name for a in grupo],
                "nome": f"Dados da Raíz — {uf}",
                "descricao": ficha["description"],
            },
            isolado=sum(quantidades.values()) > LIMITE_CAMPOS,
        )
        # mlcroissant 1.1.1 só lê propriedades de arquivo de um FileSet contido
        # num tar. FileObjects individuais permitem carregar de fato os CSV;
        # FileSets continuam descrevendo a organização por tabela.
        origens = {}
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
        del gerada
        gc.collect()
    for tabela, nomes in sorted(tabelas.items()):
        if all(re.fullmatch(re.escape(tabela) + r"_\d{7}\.csv", nome) for nome in nomes):
            inclui = [f"{uf}/{escape(tabela)}_{'[0-9]' * 7}.csv"]
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
    ficha["recordSet"].sort(key=lambda r: r["@id"])
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


def _trabalhador() -> None:
    """Protocolo interno de um lote, sem devolver mensagens brutas de bibliotecas."""
    pedido = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        valor = _processar_lote(pedido["tarefa"], pedido["dados"])
        resultado = {"ok": True, "valor": valor}
    except Exception as ex:  # noqa: BLE001 - a classe basta; parser pode incluir valores pessoais na mensagem
        resultado = {"ok": False, "erro": type(ex).__name__}
    Path(sys.argv[2]).write_text(json.dumps(resultado, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    _trabalhador()
