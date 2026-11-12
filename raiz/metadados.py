"""Fichas Croissant 1.1/schema.org do Release, sem exemplos nem dados pessoais.

O baker lê os CSV do espelho; a distribuição aponta para o pacote publicado.
Cada CSV mantém seu próprio esquema, para que uma coluna nova não torne
ilegível a parte antiga do estado. A licença dos dados derivados não é
presumida a partir da licença do código ou das fontes.
"""

from __future__ import annotations

import copy
import csv
import datetime as dt
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
CONDICOES_PRIVADAS = (
    "Arquivo privado, disponível somente a processos autorizados do servidor Raíz. "
    "A URI release-github identifica repositório, Release e arquivo; o servidor resolve o asset pela API "
    "autenticada do GitHub e confere repositório privado ou Release não publicado antes do acesso. "
    "O leitor Croissant precisa receber o arquivo local autorizado; não há download público nativo dessa URI. "
    "A licença de redistribuição dos dados derivados da Raíz ainda não foi definida; "
    "as fontes conservam os termos e créditos registrados no NOTICE.md."
)
_PROIBIDAS = re.compile(r"(^|_)(cpf|cnpj|nome|proprietario|titular|email|telefone)($|_)", re.I)
LIMITE_CAMPOS = 1500
LIMITE_NOS = 6000
# tar vazio com gzip determinístico (mtime=0), também usado pela projeção pública.
TAR_VAZIO_SHA256 = "b94b4d079a0a84bdf416bc4a472ccff4775bb999858da78e854446f0d5221b84"


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


def _escopo(escopo: str) -> None:
    if escopo not in {"publico_basico", "privado"}:
        raise ValueError("escopo de acesso inválido")


def base_release(repo: str, tag: str, *, escopo: str) -> str:
    """Endereço lógico sem token; o destino privado é resolvido pelo servidor autorizado."""
    _escopo(escopo)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not re.fullmatch(r"[A-Za-z0-9_.-]+", tag):
        raise ValueError("destino do catálogo inválido")
    if escopo == "privado":
        return f"release-github://{repo}/{tag}/"
    return f"https://github.com/{repo}/releases/download/{tag}/"


def _url_acesso(url: str, *, escopo: str) -> None:
    _escopo(escopo)
    u = urlparse(url)
    if u.username or u.password or u.query or u.fragment or not u.netloc:
        raise ValueError("endereço de acesso inválido ou contém credencial")
    if escopo == "privado":
        if not re.fullmatch(r"release-github://[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", url):
            raise ValueError("arquivo privado exige URI release-github sem segredo")
    elif u.scheme != "https":
        raise ValueError("arquivo público exige URL HTTPS")


def _base(nome: str, url: str, descricao: str, repo: str, *, escopo: str) -> dict:
    repo = REPO if repo.lower() == REPO.lower() else repo
    _url_acesso(url, escopo=escopo)
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
        "conditionsOfAccess": CONDICOES if escopo == "publico_basico" else CONDICOES_PRIVADAS,
        "isAccessibleForFree": escopo == "publico_basico",
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
    escopo: str,
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
    acesso = "básicos públicos" if escopo == "publico_basico" else "privados"
    ficha = _base(nome, url, descricao or f"Arquivo {nome} do conjunto de dados {acesso} da Raíz.", repo, escopo=escopo)
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


def croissant_uf(pasta: str | Path, uf: str, entrada: dict, *, escopo: str) -> dict:
    """Descreve os CSV diretos de ``pasta`` contidos em ``raiz_<UF>.tar.gz``.

    ``entrada`` traz url, sha256, tamanho, versao e atualizado_em do pacote
    efetivamente publicado; repo é opcional. Tipos vêm do croissant-baker
    0.8.3; o padrão não inclui exemplos/valores nem os arquivos .meta.json.
    """
    _escopo(escopo)
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
        if escopo == "publico_basico":
            _cabecalho_publico(arquivo.name, colunas, uf)
        quantidades[arquivo] = len(colunas)

    ficha = ficha_arquivo(
        f"raiz_{uf}.tar.gz",
        entrada["url"],
        entrada.get("sha256"),
        entrada.get("tamanho"),
        escopo=escopo,
        descricao=(
            (
                f"Tabelas básicas públicas da Raíz em {uf}: situação básica por CAR e agregados municipais. "
                if escopo == "publico_basico"
                else (
                    f"Tabelas privadas da Raíz por imóvel e município de {uf}: cadastro ambiental, "
                    "restrições territoriais e estimativas de restauração. "
                )
            )
            + "Inferência de tipos pelo croissant-baker; não contém amostras de valores. "
            "O processamento pode estar parcial; consulte estados.json."
        ),
        versao=entrada.get("versao"),
        atualizado_em=entrada.get("atualizado_em"),
        formato=["application/x-tar", "application/gzip"],
        repo=entrada.get("repo_codigo", REPO),
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


def croissant_release(
    indice: dict, repo: str = REPO, tag: str = "dados", *, escopo: str, repo_codigo: str = REPO
) -> dict:
    """Catálogo do Release com links apenas para fichas já publicadas.

    Cada ``estados[UF].croissant`` pode ser uma URL ou um objeto com url,
    sha256 e tamanho. Artefatos adicionais seguem o mesmo contrato no mapa
    ``indice['fichas']`` e ``estados[UF]['fichas']`` (nome do arquivo ->
    referência da sua ficha).
    """
    base = base_release(repo, tag, escopo=escopo)
    ficha = _base(
        "Dados do Brasil — Raíz",
        base + "croissant.json",
        f"Catálogo das fichas do Release {tag} ({escopo}).",
        repo_codigo,
        escopo=escopo,
    )
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
        if not url.startswith(base) or "/" in url.removeprefix(base):
            raise ValueError("referência de ficha fora do destino e escopo do catálogo")
        _url_acesso(url, escopo=escopo)
        ficha["hasPart"].append({"@type": "sc:Dataset", "@id": url, "url": url, "name": nome})
        if referencia.get("sha256"):
            arquivo = ficha_arquivo(
                url.rsplit("/", 1)[-1],
                url,
                referencia["sha256"],
                referencia.get("tamanho"),
                escopo=escopo,
                formato="application/ld+json",
                repo=repo_codigo,
            )["distribution"][0]
            arquivo["@id"] = f"fichas/{quote(nome, safe='_-')}"
            ficha["distribution"].append(arquivo)
    return ficha


def _cabecalho_publico(nome: str, colunas: list[str], uf: str) -> None:
    from raiz.executor.publicacao_aberta import COLUNAS_BASICAS, COLUNAS_RESUMO, COLUNAS_SEM_IMOVEIS

    erro = "cabeçalho fora do contrato básico público"
    if not colunas or any(not isinstance(c, str) for c in colunas) or len(set(colunas)) != len(colunas):
        raise ValueError(erro)
    if re.fullmatch(r"imoveis_basicos_[0-9]{7}\.csv", nome):
        valido = tuple(colunas) == COLUNAS_BASICAS
    elif nome in {f"resumo_{uf}.csv", f"sem_imoveis_{uf}.csv"}:
        permitidas = COLUNAS_RESUMO if nome.startswith("resumo_") else COLUNAS_SEM_IMOVEIS
        # A projeção usa a ordem da lista positiva, mesmo quando faltam colunas.
        valido = colunas == [c for c in permitidas if c in colunas]
    else:
        valido = False
    if not valido:
        raise ValueError(erro)


def validar_ficha_publica(nome: str, dados: bytes, *, repo: str = REPO, tag: str = "dados") -> None:
    """Aceita apenas o documento exato que o gerador público pode produzir.

    Contexto, textos, nomes, IDs, origens e URLs são reconstruídos, não filtrados.
    Valores/linhas, propriedades extras, aliases JSON-LD e URIs privadas falham.
    Não é necessário executar mlcroissant: este é o limite de publicação; a
    validação Croissant independente continua no gerador antes do upload.
    """
    erro = "ficha fora do contrato básico público"

    def exigir(condicao):
        if not condicao:
            raise ValueError(erro)

    def objeto(pares):
        resultado = {}
        for chave, valor in pares:
            exigir(chave not in resultado)
            resultado[chave] = valor
        return resultado

    def constante(_):
        raise ValueError(erro)

    exigir(isinstance(dados, bytes) and isinstance(nome, str))
    try:
        ficha = json.loads(dados, object_pairs_hook=objeto, parse_constant=constante)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError(erro) from None
    exigir(isinstance(ficha, dict))
    exigir(ficha.get("isAccessibleForFree") is True)
    exigir(isinstance(repo, str) and re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo))
    exigir(isinstance(tag, str) and re.fullmatch(r"[A-Za-z0-9_.-]+", tag))
    # Sem referência ao destino privado mesmo se um chamador o configurar por engano.
    exigir("privad" not in tag.lower() and "private" not in tag.lower())
    ufs = set("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())

    def nome_ficha(asset):
        exigir(isinstance(asset, str))
        m = re.fullmatch(r"raiz_(geo_)?([A-Z]{2})\.tar\.gz", asset)
        if m:
            exigir(m[2] in ufs)
            return f"croissant_{asset}.json" if m[1] else f"croissant_{m[2]}.json"
        exigir(asset in {"estados.json", "cartao_modelo.md"})
        return "croissant_estados.json" if asset == "estados.json" else "croissant_cartao_modelo.md.json"

    def url_publica(valor, asset):
        exigir(isinstance(valor, str))
        m = re.fullmatch(
            r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/releases/download/([A-Za-z0-9_.-]+)/([^/?#]+)",
            valor,
        )
        exigir(m and m[1].lower() == repo.lower() and m[2] == tag and m[3] == asset)
        return valor

    def extras_raiz():
        extra = {}
        if "version" in ficha:
            v = ficha["version"]
            exigir(
                isinstance(v, str)
                and re.fullmatch(r"(?:(?:[a-f0-9]{16}|[a-f0-9]{40}|[a-f0-9]{64})|v?[0-9]{1,4}(?:\.[0-9]{1,4}){0,3})", v)
            )
            extra["version"] = v
        if "dateModified" in ficha:
            v = ficha["dateModified"]
            exigir(
                isinstance(v, str)
                and re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|\+00:00)", v
                )
            )
            try:
                dt.datetime.fromisoformat(v)
            except ValueError:
                raise ValueError(erro) from None
            extra["dateModified"] = v
        return extra

    def arquivo(recebido, identificador, arquivo_nome, url, formato, pai=None):
        exigir(isinstance(recebido, dict))
        digest = recebido.get("sha256")
        exigir(isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest))
        esperado = {
            "@id": identificador,
            "@type": "cr:FileObject",
            "name": arquivo_nome,
            "contentUrl": url,
            "encodingFormat": formato,
            "sha256": digest,
        }
        if "contentSize" in recebido:
            tamanho = recebido["contentSize"]
            exigir(isinstance(tamanho, str) and re.fullmatch(r"(?:0|[1-9][0-9]{0,19})", tamanho))
            esperado["contentSize"] = tamanho
        if pai:
            esperado["containedIn"] = {"@id": pai}
        exigir(recebido == esperado)
        return esperado

    def base(dataset_nome, url, descricao):
        esperado = _base(dataset_nome, url, descricao, REPO, escopo="publico_basico")
        esperado.update(extras_raiz())
        return esperado

    distribuicoes = ficha.get("distribution")
    registros = ficha.get("recordSet")
    exigir(isinstance(distribuicoes, list) and isinstance(registros, list))
    if nome == "croissant.json":
        url = url_publica(ficha.get("url"), nome)
        esperado = base("Dados do Brasil — Raíz", url, f"Catálogo das fichas do Release {tag} (publico_basico).")
        partes = ficha.get("hasPart")
        exigir(isinstance(partes, list))
        por_nome, partes_esperadas = {}, []
        for parte in partes:
            exigir(isinstance(parte, dict))
            asset = parte.get("name")
            ficha_nome = nome_ficha(asset)
            endereco = url_publica(parte.get("url"), ficha_nome)
            exigir(asset not in por_nome)
            por_nome[asset] = (ficha_nome, endereco)
            partes_esperadas.append({"@type": "sc:Dataset", "@id": endereco, "url": endereco, "name": asset})
        exigir(partes == partes_esperadas and not registros)
        vistas = set()
        for d in distribuicoes:
            exigir(isinstance(d, dict) and isinstance(d.get("@id"), str))
            asset = d["@id"].removeprefix("fichas/")
            exigir(asset in por_nome and asset not in vistas)
            vistas.add(asset)
            ficha_nome, endereco = por_nome[asset]
            arquivo(d, f"fichas/{asset}", ficha_nome, endereco, "application/ld+json")
        esperado.update(hasPart=partes_esperadas, distribution=distribuicoes)
        exigir(ficha == esperado)
        return

    asset = ficha.get("name")
    exigir(nome_ficha(asset) == nome)
    url = url_publica(ficha.get("url"), asset)
    tabular = re.fullmatch(r"raiz_([A-Z]{2})\.tar\.gz", asset)
    vazio = bool(
        tabular
        and not registros
        and len(distribuicoes) == 1
        and isinstance(distribuicoes[0], dict)
        and distribuicoes[0].get("sha256") == TAR_VAZIO_SHA256
        and distribuicoes[0].get("contentSize") == "45"
    )
    descricao = f"Arquivo {asset} do conjunto de dados básicos públicos da Raíz."
    if tabular and not vazio:
        uf = tabular[1]
        descricao = (
            f"Tabelas básicas públicas da Raíz em {uf}: situação básica por CAR e agregados municipais. "
            "Inferência de tipos pelo croissant-baker; não contém amostras de valores. "
            "O processamento pode estar parcial; consulte estados.json."
        )
    esperado = base(asset, url, descricao)
    formato = (
        ["application/x-tar", "application/gzip"]
        if asset.endswith(".tar.gz")
        else "application/json"
        if asset == "estados.json"
        else "text/markdown"
    )
    exigir(bool(distribuicoes))
    arquivo(distribuicoes[0], "arquivo", asset, url, formato)
    if not tabular or vazio:
        exigir(len(distribuicoes) == 1 and not registros)
        esperado["distribution"] = distribuicoes
        exigir(ficha == esperado)
        return

    # Cada CSV deve ter exatamente um RecordSet, a origem própria e só os
    # FileSets determinísticos do gerador. Nunca aceitar uma ficha genérica
    # sem esquema para o pacote tabular.
    exigir(bool(registros))
    csvs, tabelas, campos_ids = {}, {}, set()
    tipos_numericos = {"sc:Text", "sc:Integer", "sc:Float", "cr:Int64", "cr:Float64"}
    for r in registros:
        exigir(isinstance(r, dict) and isinstance(r.get("name"), str) and isinstance(r.get("field"), list))
        registro = r["name"]
        csv_nome = registro + ".csv"
        colunas = [c.get("name") if isinstance(c, dict) else None for c in r["field"]]
        _cabecalho_publico(csv_nome, colunas, uf)
        exigir(csv_nome not in csvs)
        csvs[csv_nome] = r
        tabela = "imoveis_basicos" if csv_nome.startswith("imoveis_basicos_") else registro
        tabelas.setdefault(tabela, []).append(csv_nome)
        for c, coluna in zip(r["field"], colunas, strict=True):
            tipo = c.get("dataType")
            permitidos = (
                {"sc:Text"}
                if coluna in {"cod_imovel", "cod_ibge", "municipio", "uf", "situacao_basica"}
                else {"sc:Text", "sc:Date", "sc:DateTime"}
                if coluna == "verificado_em"
                else tipos_numericos
            )
            exigir(isinstance(tipo, str) and tipo in permitidos)
            campo_id = f"{registro}/{coluna}"
            exigir(campo_id not in campos_ids)
            campos_ids.add(campo_id)
            exigir(
                c
                == {
                    "@type": "cr:Field",
                    "@id": campo_id,
                    "name": coluna,
                    "description": f"Coluna {coluna}; definição em docs/colunas.md quando documentada.",
                    "dataType": tipo,
                    "source": {"fileObject": {"@id": f"arquivos/{csv_nome}"}, "extract": {"column": coluna}},
                }
            )
        exigir(
            r
            == {
                "@type": "cr:RecordSet",
                "@id": registro,
                "name": registro,
                "description": f"Registros de {registro} em {uf}.",
                "field": r["field"],
            }
        )
    exigir([r["@id"] for r in registros] == sorted(r["@id"] for r in registros))
    por_id = {}
    for d in distribuicoes[1:]:
        exigir(isinstance(d, dict) and isinstance(d.get("@id"), str) and d["@id"] not in por_id)
        por_id[d["@id"]] = d
    exigir(set(por_id) == {f"arquivos/{c}" for c in csvs} | {f"tabelas/{t}" for t in tabelas})
    for csv_nome in csvs:
        arquivo(
            por_id[f"arquivos/{csv_nome}"], f"arquivos/{csv_nome}", csv_nome, f"{uf}/{csv_nome}", "text/csv", "arquivo"
        )
    for tabela, nomes in tabelas.items():
        inclui = (
            [f"{uf}/imoveis_basicos_{'[0-9]' * 7}.csv"]
            if tabela == "imoveis_basicos"
            else [f"{uf}/{n}" for n in sorted(nomes)]
        )
        exigir(
            por_id[f"tabelas/{tabela}"]
            == {
                "@type": "cr:FileSet",
                "@id": f"tabelas/{tabela}",
                "name": tabela,
                "description": f"Arquivos da tabela {tabela}; o esquema de cada CSV está em seu RecordSet.",
                "containedIn": {"@id": "arquivo"},
                "encodingFormat": "text/csv",
                "includes": inclui,
            }
        )
    esperado.update(distribution=distribuicoes, recordSet=registros)
    exigir(ficha == esperado)


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
