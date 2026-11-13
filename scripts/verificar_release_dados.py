#!/usr/bin/env python3
"""Verificação somente de leitura dos Releases Raíz, com saída sem registros individuais.

Execute com ``uv run --extra metadados python -m scripts.verificar_release_dados``.
GH_TOKEN é obrigatório; para um
destino diferente, RAIZ_DADOS_PRIVADOS_TOKEN pode fornecer a credencial privada.
Nenhum método de publicação, reparo ou trava é chamado. Os derivados do lote
são reproduzidos somente em uma pasta temporária, para comparação dos hashes.
"""

from __future__ import annotations

import argparse
import calendar
import contextlib
import csv
import datetime as dt
import hashlib
import json
import logging
import math
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import warnings
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

REPO_ATESTACAO = "bernardoemmel/Raiz"
CODIGO = Path(__file__).resolve().parents[1]
WORKFLOW = "bernardoemmel/Raiz/.github/workflows/publicar-metadados.yml"
WORKFLOWS_PERMITIDOS = (WORKFLOW, "bernardoemmel/Raiz/.github/workflows/processar-estados.yml")
SHA = re.compile(r"[a-f0-9]{64}")
CAR = re.compile(r"[A-Z]{2}-\d{7}-[A-Za-z0-9]+")


class FalhaSegura(Exception):
    def __init__(self, codigo: str):
        self.codigo = codigo
        super().__init__(codigo)


def exigir(condicao, codigo):
    if not condicao:
        raise FalhaSegura(codigo)


def sha_arquivo(caminho):
    h = hashlib.sha256()
    with Path(caminho).open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def ler_json(caminho):
    with Path(caminho).open(encoding="utf-8") as f:
        return json.load(f)


def gravar_json(caminho, dados):
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporario = caminho.with_name(caminho.name + f".{os.getpid()}.tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporario, caminho)


def progresso(**dados):
    print(json.dumps(dados, ensure_ascii=False), flush=True)


@contextlib.contextmanager
def silencioso():
    # Exceções e bibliotecas podem imprimir uma linha inválida ou uma URL assinada.
    with open(os.devnull, "w") as nulo, contextlib.redirect_stdout(nulo), contextlib.redirect_stderr(nulo):
        yield


def erro_seguro(erro):
    return erro.codigo if isinstance(erro, FalhaSegura) else "falha_" + type(erro).__name__


class Cache:
    def __init__(self, pasta, locais=()):
        self.pasta, self.locais = Path(pasta), [Path(p) for p in locais]
        self.objetos = self.pasta / "objetos"
        self.objetos.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.indice_path = self.pasta / "indice-cache.json"
        self.indice = ler_json(self.indice_path) if self.indice_path.exists() else {}

    def obter(self, armazem, asset):
        nome = asset["name"]
        exigir(isinstance(nome, str) and Path(nome).name == nome and "\n" not in nome, "nome_asset_invalido")
        esperado = (asset.get("digest") or "").removeprefix("sha256:").lower()
        exigir(not esperado or SHA.fullmatch(esperado), "digest_api_invalido")
        chave = json.dumps([armazem.repo, armazem.tag, asset["id"], asset.get("updated_at"), asset.get("size")])
        conhecido = esperado or self.indice.get(chave, "")
        candidatos = [self.objetos / conhecido] if SHA.fullmatch(conhecido or "") else []
        for local in self.locais:
            candidatos.append(local / nome)
            if conhecido:
                candidatos.extend([local / conhecido, local / "objetos" / conhecido])
        for caminho in candidatos:
            if not caminho.is_file() or caminho.is_symlink():
                continue
            if asset.get("size") is not None and caminho.stat().st_size != asset["size"]:
                continue
            digest = sha_arquivo(caminho)
            # Sem digest conhecido, um arquivo avulso com o mesmo nome não comprova sua origem.
            if conhecido and digest == conhecido:
                return caminho, digest, True
        if armazem.privado:
            armazem._exigir_privado()
        url = f"{armazem.API}/repos/{armazem.repo}/releases/assets/{int(asset['id'])}"
        h, tamanho, temporario = hashlib.sha256(), 0, None
        try:
            with tempfile.NamedTemporaryFile(dir=self.objetos, prefix="download-", delete=False) as saida:
                temporario = Path(saida.name)
                with armazem.cli.stream(
                    "GET", url, headers={**armazem._cabecalhos(), "Accept": "application/octet-stream"}
                ) as resposta:
                    resposta.raise_for_status()
                    for bloco in resposta.iter_bytes(1024 * 1024):
                        saida.write(bloco)
                        h.update(bloco)
                        tamanho += len(bloco)
            digest = h.hexdigest()
            exigir(asset.get("size") is None or tamanho == asset["size"], "tamanho_asset_divergente")
            exigir(not esperado or digest == esperado, "sha256_api_divergente")
            destino = self.objetos / digest
            os.replace(temporario, destino)
            self.indice[chave] = digest
            gravar_json(self.indice_path, self.indice)
            return destino, digest, False
        finally:
            if temporario:
                temporario.unlink(missing_ok=True)


def atestacao(caminho, nome, digest, gh, *, privado=False):
    if privado:
        exigir(isinstance(digest, str) and SHA.fullmatch(digest), "atestacao_digest_privado_invalido")
    assunto = f"privado-sha256-{digest}" if privado else nome
    erro_final = "atestacao_ausente_ou_invalida"
    for workflow in WORKFLOWS_PERMITIDOS:
        # Cada alternativa precisa comprovar a política inteira; não combina
        # identidade de uma tentativa com subject de outra.
        comando = [
            gh,
            "attestation",
            "verify",
            str(caminho),
            "--repo",
            REPO_ATESTACAO,
            "--signer-workflow",
            workflow,
            "--format",
            "json",
            "--deny-self-hosted-runners",
        ]
        try:
            p = subprocess.run(comando, capture_output=True, timeout=240, check=False)
        except subprocess.TimeoutExpired:
            continue
        if p.returncode:
            continue
        try:
            verificadas = json.loads(p.stdout)
            exigir(isinstance(verificadas, list) and verificadas, "atestacao_sem_resultados")
            correspondentes = 0
            for v in verificadas:
                statement = v.get("verificationResult", {}).get("statement", {})
                if statement.get("predicateType") != "https://slsa.dev/provenance/v1":
                    continue
                if any(
                    s.get("name") == assunto and s.get("digest", {}).get("sha256") == digest
                    for s in statement.get("subject", [])
                ):
                    correspondentes += 1
            if correspondentes:
                return {"verificadas": correspondentes, "workflow": workflow, "self_hosted_recusado": True}
            erro_final = "atestacao_sem_subject_nome_e_hash"
        except (ValueError, TypeError, AttributeError, FalhaSegura):
            erro_final = "atestacao_resposta_invalida"
    raise FalhaSegura(erro_final)


def validar_contidos(ficha, caminho, proveniencia=None, *, uf=None):
    exige_versoes = uf is not None or proveniencia is not None
    descritos = [
        d
        for d in ficha.get("distribution", [])
        if d.get("@type") == "cr:FileObject" and d.get("containedIn") == {"@id": "arquivo"}
    ]
    contidos = {d["contentUrl"]: d for d in descritos}
    exigir(len(contidos) == len(descritos), "csv_descrito_mais_de_uma_vez")
    if not contidos and uf is None:
        return 0
    vistos, manifesto = set(), None
    pastas = {uf} if uf else {nome.split("/")[0] for nome in contidos}
    with tarfile.open(caminho, "r|gz") as tar:
        for membro in tar:
            partes = Path(membro.name).parts
            exigir(not membro.name.startswith("/") and ".." not in partes, "membro_tar_invalido")
            if membro.isdir():
                continue
            exigir(membro.isfile(), "membro_tar_invalido")
            exigir(membro.name not in vistos, "membro_tar_duplicado")
            vistos.add(membro.name)
            if (
                exige_versoes
                and ficha.get("isAccessibleForFree") is False
                and membro.name in {f"{uf}/_versoes.json" for uf in pastas}
            ):
                with tar.extractfile(membro) as entrada:
                    dados = entrada.read()
                exigir(isinstance(json.loads(dados), dict), "manifesto_versoes_invalido")
                manifesto = membro.name
                exigir(hashlib.sha256(dados).hexdigest() == proveniencia, "hash_proveniencia_pacote_divergente")
                continue
            exigir(membro.name in contidos, "membro_tar_sem_ficha")
            d, h = contidos[membro.name], hashlib.sha256()
            with tar.extractfile(membro) as entrada:
                for bloco in iter(lambda: entrada.read(1024 * 1024), b""):
                    h.update(bloco)
            exigir(h.hexdigest() == d.get("sha256"), "sha256_csv_contido_divergente")
            exigir(str(membro.size) == str(d.get("contentSize")), "tamanho_csv_contido_divergente")
    exigir(vistos - ({manifesto} if manifesto else set()) == set(contidos), "csv_descrito_ausente_do_tar")
    if exige_versoes and ficha.get("isAccessibleForFree") is False:
        exigir(manifesto is not None, "manifesto_versoes_ausente")
    return len(contidos)


def validar_fichas(armazem, arquivos, registrar, metadados, referencias):
    catalogo = ler_json(arquivos["croissant.json"][0])
    partes = catalogo.get("hasPart", [])
    mapa = {p["name"]: p["url"] for p in partes}
    exigir(len(mapa) == len(partes), "catalogo_com_nomes_duplicados")
    produtos = {n for n in arquivos if not (n == "croissant.json" or n.startswith("croissant_"))}
    exigir(set(mapa) == produtos, "cobertura_catalogo_divergente")
    for produto, endereco in mapa.items():
        nome_ficha = endereco.rsplit("/", 1)[-1]
        exigir(
            nome_ficha.startswith("croissant_")
            and nome_ficha in arquivos
            and endereco == armazem.url_metadados(nome_ficha),
            "ficha_catalogada_ausente_ou_fora_do_release",
        )
        ficha = ler_json(arquivos[nome_ficha][0])
        externos = [
            d for d in ficha.get("distribution", []) if d.get("@type") == "cr:FileObject" and not d.get("containedIn")
        ]
        exigir(
            len(externos) == 1 and externos[0].get("contentUrl") == armazem.url_metadados(produto),
            "ficha_nao_descreve_produto_catalogado",
        )
    indice = ler_json(arquivos["estados.json"][0])
    for nome, ref in referencias(indice).items():
        endereco = ref if isinstance(ref, str) else ref["url"]
        exigir(mapa.get(nome) == endereco, "indice_catalogo_divergentes")
        if isinstance(ref, dict) and ref.get("sha256"):
            exigir(arquivos[endereco.rsplit("/", 1)[-1]][1] == ref["sha256"], "hash_ficha_no_indice_divergente")
    for nome, (caminho, _, _) in arquivos.items():
        if not (nome == "croissant.json" or nome.startswith("croissant_")):
            continue

        def conferir(nome=nome, caminho=caminho):
            ficha = ler_json(caminho)
            exigir(ficha.get("@type") == "sc:Dataset", "ficha_sem_schema_org_dataset")
            exigir(ficha.get("conformsTo") == metadados.CONFORMIDADE, "ficha_sem_croissant_1_1")
            exigir(ficha.get("isAccessibleForFree") is (not armazem.privado), "escopo_croissant_divergente")
            metadados.validar(ficha)
            contagem = 0
            for d in ficha.get("distribution", []):
                if d.get("@type") != "cr:FileObject" or d.get("containedIn"):
                    continue
                endereco = d.get("contentUrl", "")
                asset_nome = endereco.rsplit("/", 1)[-1]
                exigir(endereco == armazem.url_metadados(asset_nome), "distribuicao_fora_do_release")
                exigir(asset_nome in arquivos, "distribuicao_ausente_do_release")
                p, digest, tamanho = arquivos[asset_nome]
                exigir(d.get("sha256") == digest, "sha256_croissant_divergente")
                if d.get("contentSize") is not None:
                    exigir(str(d["contentSize"]) == str(tamanho), "tamanho_croissant_divergente")
                if nome != "croissant.json":
                    exigir(mapa.get(asset_nome) == armazem.url_metadados(nome), "ficha_fora_do_catalogo")
                    uf = re.fullmatch(r"raiz_([A-Z]{2})\.tar\.gz", asset_nome)
                    prov = indice.get("estados", {}).get(uf[1], {}).get("proveniencia_sha256") if uf else None
                    contagem += validar_contidos(ficha, p, prov, uf=uf[1] if uf else None)
            return {"croissant": "1.1", "schema_org": "Dataset", "csvs_com_hash_conferido": contagem}

        registrar(nome, "croissant", conferir)
    return indice


def validar_quantis(caminho, uf, metadados, globais, entrada, *, auxiliares=None):
    import duckdb
    import pandas as pd
    import pyarrow.parquet as pq

    from raiz import quantis

    exigir(metadados.get("exporter_version") == quantis.EXPORTADOR_VERSAO, "versao_exportador_quantis_divergente")
    exigir(metadados.get("reference_date_basis") == quantis.BASE_DATA, "base_temporal_quantis_divergente")
    exigir(pq.read_schema(caminho).equals(quantis.ESQUEMA_PUBLICO, check_metadata=False), "schema_quantis_divergente")
    con = duckdb.connect(config={"threads": 2, "memory_limit": "1GB"})
    try:
        con.read_parquet(str(caminho)).create_view("q")
        versoes = ["model_version", "source_model_version", "task_version", "quantile_method"]
        vazio = " OR ".join(f"{c} IS NULL OR trim({c})=''" for c in [*versoes, "model_id", "source_file"])
        defeitos = con.sql(f"""SELECT count(*) FROM q WHERE {vazio}
            OR reference_date IS NULL OR location IS NULL OR target IS NULL
            OR output_type IS DISTINCT FROM 'quantile' OR output_type_id IS NULL
            OR output_type_id NOT IN (0.1,0.5,0.9) OR value IS NULL OR NOT isfinite(value)
            OR NOT regexp_full_match(location, '{uf}-[0-9]{{7}}-[A-Za-z0-9]+')
            OR NOT regexp_full_match(source_file, '(desenvolvedor|flag)_[0-9]{{7}}\\.csv')
            OR model_id <> 'raiz-' || split_part(source_file, '_', 1) || '_' || substr(sha256(model_version),1,16)
            OR (target='flag_tco2_ano' AND value<0)
            OR ((split_part(source_file,'_',1)='flag') <> (target='flag_tco2_ano'))
            OR quantile_method <> CASE WHEN split_part(source_file,'_',1)='flag'
                THEN 'prior_triangular_nao_calibrado' ELSE 'quantis_publicados_p50_cenario_central' END
        """).fetchone()[0]
        exigir(defeitos == 0, "linhas_quantis_invalidas")
        alvos = set(con.sql("SELECT DISTINCT target FROM q").fetchnumpy()["target"])
        exigir(alvos <= set(quantis.ALVOS), "alvo_quantis_desconhecido")
        agregadas = con.sql("""SELECT count(*) FROM (
            SELECT model_id,reference_date,location,target,output_type FROM q
            GROUP BY ALL HAVING count(*)<>3 OR count(DISTINCT output_type_id)<>3
            OR max(value) FILTER(WHERE output_type_id=0.1)>min(value) FILTER(WHERE output_type_id=0.5)
            OR max(value) FILTER(WHERE output_type_id=0.5)>min(value) FILTER(WHERE output_type_id=0.9)
            OR count(DISTINCT model_version)<>1 OR count(DISTINCT source_model_version)<>1
            OR count(DISTINCT task_version)<>1 OR count(DISTINCT quantile_method)<>1
            OR count(DISTINCT source_file)<>1)""").fetchone()[0]
        exigir(agregadas == 0, "grupos_quantis_incompletos_ou_desordenados")
        modelos = metadados.get("modelos", {})
        resumos = con.sql(
            "SELECT DISTINCT model_id,model_version,source_model_version,task_version,quantile_method FROM q"
        ).fetchall()
        exigir(
            sorted(r[0] for r in resumos) == sorted(modelos) == entrada.get("quantis", {}).get("modelos"),
            "cobertura_modelos_quantis_divergente",
        )
        for mid, *valores in resumos:
            exigir(all(quantis._versao(v) for v in valores), "versao_quantis_sem_conteudo")
            exigir(
                mid in modelos and all(modelos[mid].get(c) == v for c, v in zip(versoes, valores, strict=True)),
                "versao_quantis_diverge_modelo",
            )
            exigir(
                globais.get("modelos", {}).get(mid) == modelos[mid], "modelo_estadual_ausente_ou_divergente_no_global"
            )
            exigir(
                modelos[mid].get("exporter_version") == quantis.EXPORTADOR_VERSAO, "versao_exportador_modelo_divergente"
            )
            exigir(modelos[mid].get("reference_date_basis") == quantis.BASE_DATA, "base_temporal_modelo_divergente")
            exigir(set(quantis.esquema_modelos()["required"]) <= set(modelos[mid]), "modelo_sem_campos_obrigatorios")
        fontes = metadados.get("fontes", [])
        exigir(len({f["arquivo"] for f in fontes}) == len(fontes), "fontes_quantiles_duplicadas")
        for f in fontes:
            # O exportador aceita tanto dia ISO explícito quanto timestamp com fuso.
            exigir(
                quantis._data(f["source_execution_time"]).isoformat() == f["reference_date"],
                "data_fonte_quantis_divergente",
            )
        if fontes:
            con.register("fontes", pd.DataFrame(fontes))
            erros = con.sql("""SELECT count(*) FROM q LEFT JOIN fontes f ON q.source_file=f.arquivo
                WHERE f.arquivo IS NULL OR q.task_version<>f.task_version
                OR q.reference_date<>CAST(f.reference_date AS DATE)""").fetchone()[0]
            exigir(erros == 0, "proveniencia_quantis_divergente")
        linhas = con.sql("SELECT count(*) FROM q").fetchone()[0]
        exigir(fontes or linhas == 0, "quantis_sem_fontes")
        exigir(entrada.get("quantis", {}).get("linhas") == linhas, "contagem_quantis_diverge_indice")
        if auxiliares is not None:
            exigir(auxiliares["schema"] == quantis.esquema_modelos(), "schema_modelos_publicado_divergente")
            diagnosticos = auxiliares["diagnosticos"]
            exigir(
                isinstance(diagnosticos, list)
                and all(isinstance(d, dict) for d in diagnosticos)
                and len(diagnosticos) == entrada["quantis"].get("diagnosticos"),
                "contagem_diagnosticos_divergente",
            )
            hashes = {}
            for distribuicao in auxiliares["ficha_pacote"].get("distribution", []):
                if distribuicao.get("@type") != "cr:FileObject" or "containedIn" not in distribuicao:
                    continue
                url, digest = distribuicao.get("contentUrl"), distribuicao.get("sha256")
                exigir(
                    distribuicao["containedIn"] == {"@id": "arquivo"}
                    and isinstance(url, str)
                    and re.fullmatch(rf"{uf}/[A-Za-z0-9_.-]+\.csv", url)
                    and isinstance(digest, str)
                    and SHA.fullmatch(digest),
                    "fonte_quantis_na_ficha_invalida",
                )
                exigir(url not in hashes, "fonte_quantis_na_ficha_duplicada")
                hashes[url] = digest
            for fonte in fontes:
                exigir(
                    hashes.get(f"{uf}/{fonte['arquivo']}") == fonte.get("sha256") and fonte.get("sha256"),
                    "hash_fonte_quantis_diverge_pacote",
                )
            for chave in ("tasks", "tasks_globais"):
                tarefa = auxiliares[chave]
                ids = tarefa["rounds"][0]["model_tasks"][0]["task_ids"]
                datas, locais = ids["reference_date"]["optional"], ids["location"]["optional"]
                exigir(tarefa == quantis.tasks(datas, locais), "estrutura_tasks_divergente")
                for coluna, valores in (("reference_date", datas), ("location", locais)):
                    con.register("permitidos", pd.DataFrame({"valor": valores}, dtype=str))
                    faltantes = con.sql(f"""SELECT count(*) FROM (
                        SELECT DISTINCT CAST({coluna} AS VARCHAR) AS valor FROM q
                        EXCEPT SELECT CAST(valor AS VARCHAR) FROM permitidos)""").fetchone()[0]
                    exigir(faltantes == 0, "tasks_omite_valores_observados")
                    if chave == "tasks":
                        extras = con.sql(f"""SELECT count(*) FROM (
                            SELECT CAST(valor AS VARCHAR) AS valor FROM permitidos
                            EXCEPT SELECT DISTINCT CAST({coluna} AS VARCHAR) FROM q)""").fetchone()[0]
                        exigir(extras == 0, "tasks_estadual_com_valores_nao_observados")
        return {"linhas": linhas, "grupos": linhas // 3, "modelos": len(resumos), "alvos": len(alvos)}
    finally:
        con.close()


def _origem_cadt(pacote, uf, pacote_sha, proveniencia_sha):
    """Confere os bytes e lê somente versão, cenário e total; não retém linhas individuais."""

    def objeto_unico(pares):
        objeto = {}
        for chave, valor in pares:
            exigir(chave not in objeto, "cadt_manifesto_fonte_duplicado")
            objeto[chave] = valor
        return objeto

    try:
        exigir(sha_arquivo(pacote) == pacote_sha, "cadt_hash_pacote_divergente")
        vistos, fontes, manifesto = set(), {}, None
        versoes, cenarios, total = set(), set(), 0
        with tarfile.open(pacote, "r|gz") as tar:
            for membro in tar:
                partes = Path(membro.name).parts
                exigir(
                    membro.isfile()
                    and len(partes) == 2
                    and partes[0] == uf
                    and ".." not in partes
                    and membro.name == f"{uf}/{partes[1]}",
                    "cadt_membro_tar_invalido",
                )
                exigir(membro.name not in vistos, "cadt_membro_tar_duplicado")
                vistos.add(membro.name)
                nome = partes[1]
                if nome == "_versoes.json":
                    with tar.extractfile(membro) as arquivo:
                        bruto = arquivo.read()
                    exigir(hashlib.sha256(bruto).hexdigest() == proveniencia_sha, "cadt_hash_proveniencia_divergente")
                    manifesto = json.loads(bruto, object_pairs_hook=objeto_unico)
                    exigir(isinstance(manifesto, dict), "cadt_manifesto_fonte_invalido")
                    continue
                if not re.fullmatch(r"desenvolvedor_\d{7}\.csv", nome):
                    exigir(not nome.startswith("desenvolvedor_"), "cadt_nome_fonte_invalido")
                    continue
                h, quantidade = hashlib.sha256(), 0
                with tar.extractfile(membro) as arquivo:

                    def linhas(entrada=arquivo, digest=h):
                        for numero, linha in enumerate(entrada):
                            digest.update(linha)
                            yield linha.decode("utf-8-sig" if numero == 0 else "utf-8")

                    leitor = csv.reader(linhas())
                    cabecalho = next(leitor, [])
                    exigir(len(set(cabecalho)) == len(cabecalho), "cadt_coluna_fonte_ausente_ou_duplicada")
                    campos = ("restauracao_versao", "restauracao_cenario", "credito_liquido_tco2_contrato")
                    exigir(all(cabecalho.count(c) == 1 for c in campos), "cadt_coluna_fonte_ausente_ou_duplicada")
                    indices = [cabecalho.index(c) for c in campos]
                    for linha in leitor:
                        exigir(len(linha) == len(cabecalho), "cadt_linha_fonte_invalida")
                        versao, cenario, credito = (linha[i] for i in indices)
                        exigir(bool(versao.strip()) and bool(cenario.strip()), "cadt_versao_ou_cenario_fonte_ausente")
                        versoes.add(versao)
                        cenarios.add(cenario)
                        exigir(len(versoes) == len(cenarios) == 1, "cadt_versao_ou_cenario_fonte_misto")
                        valor = Decimal(credito)
                        exigir(
                            valor.is_finite()
                            and 0 <= valor <= Decimal(str(sys.float_info.max))
                            and valor == valor.to_integral_value(),
                            "cadt_total_fonte_invalido",
                        )
                        if versao == "restauracao-2026b+cenarios-2026b+dbc2776a" and valor > 0:
                            campos_curva = ("credito_liquido_tco2_ha_contrato_p50", "credito_liquido_tco2_ha_horizonte")
                            exigir(
                                all(cabecalho.count(c) == 1 for c in campos_curva), "cadt_curva_fonte_nao_comprovada"
                            )
                            contrato, horizonte = (Decimal(linha[cabecalho.index(c)]) for c in campos_curva)
                            # Ambos foram arredondados a 0,1. Intervalos disjuntos
                            # demonstram N40 > N25 e excluem teto já atingido em25.
                            exigir(
                                contrato.is_finite()
                                and horizonte.is_finite()
                                and contrato >= 0
                                and horizonte >= 0
                                and horizonte - contrato > Decimal("0.1"),
                                "cadt_curva_fonte_nao_comprovada",
                            )
                        total += int(valor)
                        quantidade += 1
                fontes[nome] = {"sha256": h.hexdigest(), "linhas": quantidade}
        exigir(isinstance(manifesto, dict) and fontes and versoes, "cadt_origem_fonte_ausente")
        exigir(
            {n for n in manifesto if n.startswith("desenvolvedor_")} == set(fontes),
            "cadt_arquivos_manifesto_divergentes",
        )
        tarefas = set()
        for nome, fonte in fontes.items():
            meta = manifesto[nome]
            exigir(
                isinstance(meta, dict)
                and meta.get("tarefa") == "desenvolvedor"
                and isinstance(meta.get("versao"), str)
                and bool(meta["versao"].strip()),
                "cadt_tarefa_fonte_invalida",
            )
            exigir(meta.get("sha256") == fonte["sha256"], "cadt_sha256_fonte_divergente")
            tarefas.add(meta["versao"])
        exigir(len(tarefas) == 1, "cadt_tarefas_fonte_mistas")
        exigir(total <= sys.float_info.max, "cadt_total_fonte_invalido")
        return {
            "versao": next(iter(versoes)),
            "cenario": next(iter(cenarios)),
            "tarefa": next(iter(tarefas)),
            "arquivos": len(fontes),
            "credito_total": total,
        }
    except FalhaSegura:
        raise
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, csv.Error, tarfile.TarError):
        raise FalhaSegura("cadt_pacote_fonte_invalido") from None


def _vincular_origem_cadt(m, fonte):
    from raiz import restauracao
    from raiz.regras.historico import carregar

    versao = m.get("versoes", {}).get("versao_premissas")
    exigir(versao == fonte["versao"], "cadt_versao_diverge_fonte")
    exigir(m.get("cenario") == fonte["cenario"] == "central_r11", "cadt_cenario_diverge_fonte")
    registro = carregar(versao)
    historicos = {k for k in m if k.startswith("regra_source_") or k == "versao_tarefa_referencia"}
    if registro:
        prova = registro[1]
        exigir(
            historicos == set(prova) and all(m.get(k) == v for k, v in prova.items()),
            "cadt_prova_historica_divergente",
        )
        exigir(fonte["tarefa"] == prova["versao_tarefa_referencia"], "cadt_tarefa_historica_diverge_fonte")
    else:
        exigir(versao == restauracao.versao(), "cadt_versao_fonte_nao_suportada")
        exigir(not historicos, "cadt_prova_historica_contraditoria")
    if "versao_tarefa_fonte_verificada" in m:
        exigir(m["versao_tarefa_fonte_verificada"] == fonte["tarefa"], "cadt_tarefa_verificada_diverge_fonte")
    if "arquivos_fonte_verificados" in m:
        exigir(
            type(m["arquivos_fonte_verificados"]) is int and m["arquivos_fonte_verificados"] == fonte["arquivos"],
            "cadt_contagem_fontes_divergente",
        )


def validar_cadt(dado, uf, entrada, pacote_sha, url_pacote, url_catalogo, *, pacote=None):
    def sem_identificacao(valor):
        if isinstance(valor, dict):
            for chave, item in valor.items():
                exigir(
                    chave.lower()
                    not in {"cod_imovel", "cod_car", "location", "cpf", "cnpj", "proprietario", "nome_proprietario"},
                    "cadt_com_identificacao_individual",
                )
                sem_identificacao(item)
        elif isinstance(valor, list):
            for item in valor:
                sem_identificacao(item)
        elif isinstance(valor, str):
            exigir(CAR.search(valor) is None, "cadt_com_identificacao_individual")

    sem_identificacao(dado)
    exigir(entrada.get("cadt") == dado, "cadt_diverge_indice")
    exigir(dado.get("uf") == uf, "cadt_uf_divergente")
    m, projeto = dado.get("metadados", {}), dado.get("projeto")
    exigir(m.get("escopo") == "privado", "cadt_escopo_divergente")
    exigir(
        m.get("entradas")
        == {"pacote_sha256": pacote_sha, "proveniencia_sha256": entrada.get("proveniencia_sha256"), "url": url_pacote},
        "cadt_origem_divergente",
    )
    declara_origem = bool(m.get("versoes")) or any(
        k.startswith("regra_source_")
        or k
        in {
            "versao_tarefa_referencia",
            "versao_tarefa_fonte_verificada",
            "arquivos_fonte_verificados",
            "evidencia_tarefa",
            "metodo_cronograma",
            "probabilidade_historica_lote",
            "politica_selecao",
            "descontos_reaplicados_ao_p50",
        }
        for k in m
    )
    fonte = None
    if projeto is not None or declara_origem:
        exigir(pacote is not None, "cadt_pacote_fonte_ausente")
        fonte = _origem_cadt(pacote, uf, pacote_sha, entrada.get("proveniencia_sha256"))
        _vincular_origem_cadt(m, fonte)
    versao_2026b = "restauracao-2026b+cenarios-2026b+dbc2776a"
    metodo_2026b = "cronograma-deterministico-2026b-1"
    legado = m.get("versoes", {}).get("versao_premissas") == versao_2026b
    if legado:
        from raiz.regras.historico import carregar

        _, prova = carregar(versao_2026b)
        exigir(
            m.get("metodo_cronograma") == m["versoes"].get("versao_metodo_cronograma") == metodo_2026b
            and isinstance(m["versoes"].get("versao_premissas_selecao"), str)
            and bool(m["versoes"]["versao_premissas_selecao"])
            and m.get("probabilidade_historica_lote") == "nao_disponivel"
            and m.get("descontos_reaplicados_ao_p50") is False
            and m.get("politica_selecao") == "politica_atual_seleciona_carteira_sem_recalcular_creditos",
            "cadt_metodo_historico_incompativel",
        )
        exigir(
            all(m.get(chave) == valor for chave, valor in prova.items())
            and m.get("versao_tarefa_fonte_verificada") == prova["versao_tarefa_referencia"]
            and type(m.get("arquivos_fonte_verificados")) is int
            and m["arquivos_fonte_verificados"] == fonte["arquivos"]
            and m.get("evidencia_tarefa") == "metadados_do_arquivo_e_sha256_dos_bytes",
            "cadt_codigo_historico_nao_comprovado",
        )
    else:
        exigir(
            "metodo_cronograma" not in m
            and "versao_metodo_cronograma" not in m.get("versoes", {})
            and "regra_source_perfil" not in m
            and not {"probabilidade_historica_lote", "politica_selecao", "descontos_reaplicados_ao_p50"}.intersection(
                m
            ),
            "cadt_metodo_historico_incompativel",
        )
    if projeto is None:
        exigir(bool(dado.get("diagnosticos")), "cadt_ausente_sem_diagnostico")
        return {"projeto": False, "diagnosticos": len(dado["diagnosticos"])}
    exigir(dado.get("diagnosticos") == [], "cadt_projeto_com_diagnostico")
    esperados = {
        "sector": "Agriculture; forestry and fishing",
        "projectType": "Reforestation and Revegetation",
        "coveredByNDC": "Unknown",
        "projectStatus": "Listed",
        "unitMetric": "tCO2e",
        "methodology": "VCS - VM0047",
        "registryOfOrigin": "Raíz — catálogo de cenários",
    }
    exigir(all(projeto.get(k) == v for k, v in esperados.items()), "cadt_vocabulario_divergente")
    exigir(
        m.get("cenario") == "central_r11" and m.get("data_inicio_contratada") is False,
        "cadt_cenario_sem_marca_hipotetica",
    )
    exigir(
        m.get("data_historica_das_fontes") is None and m.get("previsoes_individuais_recalculadas") is False,
        "cadt_proveniencia_incompativel",
    )
    exigir(m.get("comercializacao", {}).get("situacao") == "pendente", "cadt_comercializacao_nao_pendente")
    identidade = {
        "uf": uf,
        "cenario": m["cenario"],
        "inicio": m["data_inicio_cenario"],
        "versoes": m["versoes"],
        "exportador": m["versao_exportador"],
    }
    h = hashlib.sha256(json.dumps(identidade, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    exigir(
        projeto.get("projectId") == projeto.get("originProjectId") == f"raiz-cenario-{uf}-{h}",
        "cadt_identidade_divergente",
    )
    exigir(projeto.get("projectLink") == url_catalogo + "#" + projeto["projectId"], "cadt_link_divergente")
    exigir(projeto.get("projectStatusDate") == m["data_simulacao"], "cadt_data_status_divergente")
    es = projeto.get("estimations", [])
    exigir(len(es) == 25, "cadt_prazo_diferente_de_25_anos")
    inicio = dt.date.fromisoformat(m["data_inicio_cenario"])

    def aniversario(n):
        ano = inicio.year + n
        return dt.date(ano, inicio.month, min(inicio.day, calendar.monthrange(ano, inicio.month)[1]))

    for n, estimativa in enumerate(es):
        exigir(
            set(estimativa) == {"creditingPeriodStart", "creditingPeriodEnd", "unitCount"},
            "cadt_campos_estimativa_invalidos",
        )
        exigir(type(estimativa["unitCount"]) is int and estimativa["unitCount"] >= 0, "cadt_unidades_invalidas")
        exigir(estimativa["creditingPeriodStart"] == aniversario(n).isoformat(), "cadt_inicio_periodo_divergente")
        exigir(
            estimativa["creditingPeriodEnd"] == (aniversario(n + 1) - dt.timedelta(days=1)).isoformat(),
            "cadt_fim_periodo_divergente",
        )
    total = sum(e["unitCount"] for e in es)
    credito = m["credito_contrato_p50"]
    exigir(
        (type(credito) is int or (type(credito) is float and math.isfinite(credito) and credito.is_integer()))
        and credito > 0,
        "cadt_credito_invalido",
    )
    exigir(credito <= fonte["credito_total"], "cadt_credito_supera_fonte")
    exigir(total == m["total_inteiro_tco2e"] == math.floor(credito + 0.5), "cadt_total_nao_conservado")
    marcos = m["marcos"]
    exigir([v["ano"] for v in marcos] == [7, 12, 17, 22, 25], "cadt_anos_marcos_divergentes")
    for marco in marcos:
        exigir(
            sum(e["unitCount"] for e in es[: marco["ano"]])
            == marco["acumulado_inteiro"]
            == math.floor(marco["acumulado_p50"] + 0.5),
            "cadt_marco_nao_conservado",
        )
    if legado:
        # Reconstrução racional independente do adaptador: pontos do YAML
        # auditado e cauda linear do código 2026b, sem executar código histórico.
        from fractions import Fraction

        pico, primeiro = Fraction(3029, 100), Fraction(336, 25)
        pesos = [Fraction(0)]
        for ano in range(1, 26):
            valor = (
                primeiro * (ano - 2) / 5
                if ano <= 7
                else primeiro + (pico - primeiro) * (ano - 7) / 7
                if ano <= 14
                else pico - Fraction(20027, 17550) * (ano - 14)
            )
            pesos.append(max(valor, 0))
        acumulado = Fraction(0)
        total_pesos = sum(pesos)
        inteiros = 0
        marcos_por_ano = {marco["ano"]: marco for marco in marcos}
        for ano, estimativa in enumerate(es, 1):
            acumulado += pesos[ano]
            esperado = float(acumulado / total_pesos) * credito
            inteiros += estimativa["unitCount"]
            exigir(abs(inteiros - esperado) <= 0.500001, "cadt_curva_historica_divergente")
            if ano in marcos_por_ano:
                exigir(
                    math.isclose(marcos_por_ano[ano]["acumulado_p50"], esperado, rel_tol=1e-12, abs_tol=1e-6),
                    "cadt_curva_historica_divergente",
                )
    return {"projeto": True, "anos": 25, "marcos": 5, "total_inteiro_tco2e": total}


@contextlib.contextmanager
def abrir_escopo(args, escopo, cache):
    import httpx

    from raiz.executor.armazem import ArmazemRelease, destino_privado

    privado = escopo == "privado"
    destino = destino_privado() or (args.repo_publico, "dados-privados")
    repo, tag = destino if privado else (args.repo_publico, args.tag_publica)
    token = (
        (os.environ.get("RAIZ_DADOS_PRIVADOS_TOKEN") or os.environ.get("GH_TOKEN"))
        if privado
        else os.environ.get("GH_TOKEN")
    )
    exigir(bool(token), "GH_TOKEN_ausente")

    def somente_get(request):
        exigir(request.method == "GET", "metodo_http_mutavel_bloqueado")

    cliente = httpx.Client(timeout=60, follow_redirects=True, event_hooks={"request": [somente_get]})
    armazem = ArmazemRelease(
        repo, tag, cache.pasta / "espelho-nao-usado", token=token, cliente=cliente, privado=privado
    )
    try:
        yield armazem
    finally:
        cliente.close()


def snapshot(armazem, publicador):
    """Duas leituras da identidade cercam a paginação dos produtos."""

    def identidade():
        r = armazem.cli.get(f"{armazem.API}/repos/{armazem.repo}", headers=armazem._cabecalhos())
        r.raise_for_status()
        privado_repo = r.json().get("private")
        release = armazem._release(listar_assets=False)
        if armazem.privado:
            exigir(privado_repo is True or release.get("draft") is True, "release_privado_exposto")
        else:
            exigir(privado_repo is False and release.get("draft") is False, "release_publico_nao_publicado")
        return {"release_id": release["id"], "draft": release.get("draft"), "repositorio_privado": privado_repo}

    inicio = identidade()
    todos = armazem._assets()
    ativos = publicador.arquivos_produto(SimpleNamespace(_assets=lambda: todos))
    if not armazem.privado:
        exigir(len(ativos) == len(todos), "infraestrutura_no_release_publico")
    exigir(inicio == identidade(), "release_alterado_durante_inventario")
    exigir(ativos, "release_sem_arquivos_produto")
    exigir(len({a["name"] for a in todos}) == len(todos), "nomes_assets_duplicados")
    exigir(len({a["id"] for a in todos}) == len(todos), "ids_assets_duplicados")
    inventario = sorted([[a["name"], a["id"], a.get("digest"), a.get("size"), a.get("updated_at")] for a in todos])
    return {**inicio, "inventario": inventario}, ativos


def executar_escopo(args, escopo, cache, relatorio, publicador, metadados):
    with abrir_escopo(args, escopo, cache) as armazem:
        _executar_escopo(args, escopo, cache, relatorio, publicador, metadados, armazem)


def _executar_escopo(args, escopo, cache, relatorio, publicador, metadados, armazem):
    import httpx

    from raiz.executor.publicacao_aberta import validar_asset_publico

    privado, repo, tag = armazem.privado, armazem.repo, armazem.tag
    metadados.base_release(repo, tag, escopo="privado" if privado else "publico_basico")
    saida = relatorio["escopos"][escopo] = {
        "repo": repo,
        "tag": tag,
        "arquivos": {},
        "erros": [],
        "snapshot_estavel": False,
    }
    arquivos = {}

    def salvar():
        gravar_json(args.relatorio, relatorio)

    def registrar(nome, etapa, fn):
        progresso(escopo=escopo, arquivo=nome, etapa=etapa, situacao="conferindo")
        try:
            with silencioso():
                resultado = fn()
            saida["arquivos"].setdefault(nome, {})[etapa] = resultado or {"ok": True}
        except Exception as erro:
            codigo = erro_seguro(erro)
            saida["erros"].append({"arquivo": nome, "etapa": etapa, "codigo": codigo})
            progresso(escopo=escopo, arquivo=nome, etapa=etapa, erro=codigo)
            if isinstance(erro, httpx.HTTPStatusError) and erro.response.status_code in {401, 403, 429}:
                salvar()
                raise FalhaSegura("api_acesso_ou_cota_bloqueada") from None
        salvar()

    try:
        inicial, ativos = snapshot(armazem, publicador)
        saida["snapshot"] = inicial
        saida["release_id"], saida["arquivos_produto"] = inicial["release_id"], len(ativos)
        for asset in sorted(ativos, key=lambda a: a["name"]):
            nome = asset["name"]

            def baixar(asset=asset, nome=nome):
                caminho, digest, reutilizado = cache.obter(armazem, asset)
                tamanho = caminho.stat().st_size
                arquivos[nome] = (caminho, digest, tamanho)
                return {
                    "sha256": digest,
                    "bytes": tamanho,
                    "cache": reutilizado,
                    "digest_api": bool(asset.get("digest")),
                }

            registrar(nome, "bytes", baixar)
            if nome not in arquivos:
                continue
            caminho, digest, _ = arquivos[nome]
            if not privado:
                registrar(
                    nome,
                    "contrato_publico",
                    lambda nome=nome, caminho=caminho: validar_asset_publico(
                        nome, caminho.read_bytes(), repo=repo, tag=tag
                    ),
                )
            if not args.sem_atestacao:
                registrar(
                    nome,
                    "atestacao",
                    lambda caminho=caminho, nome=nome, digest=digest: atestacao(
                        caminho, nome, digest, args.gh, privado=privado
                    ),
                )
        exigir(
            {"estados.json", "croissant.json", "cartao_modelo.md"} <= set(arquivos), "catalogo_indice_ou_cartao_ausente"
        )
        indice = validar_fichas(armazem, arquivos, registrar, metadados, publicador.referencias)
        if privado:
            from raiz.lote_publicado import eh_manifesto

            for nome in sorted(n for n in arquivos if eh_manifesto(n)):
                registrar(
                    nome,
                    "lote_publicado",
                    lambda nome=nome: validar_lote_publicado(
                        nome, arquivos, armazem.url_metadados(nome).removesuffix(nome)
                    ),
                )
            ufs = set(indice.get("estados", {}))
            for uf in ufs:
                obrigatorios = {
                    f"{prefixo}_{uf}{sufixo}"
                    for prefixo, sufixo in (
                        ("raiz", ".tar.gz"),
                        ("quantis", ".parquet"),
                        ("modelos", ".json"),
                        ("tasks", ".json"),
                        ("diagnosticos_quantis", ".json"),
                        ("hub", ".tar.gz"),
                        ("cadt", ".json"),
                    )
                }
                exigir(obrigatorios <= set(arquivos), "derivados_estaduais_ausentes")
            if ufs:
                exigir(
                    {"modelos.json", "tasks.json", "model-metadata-schema.json"} <= set(arquivos),
                    "configuracao_global_quantis_ausente",
                )
            globais = ler_json(arquivos["modelos.json"][0]) if "modelos.json" in arquivos else {}
            cadts = {}
            for nome in sorted(arquivos):
                if achado := re.fullmatch(r"quantis_([A-Z]{2})\.parquet", nome):
                    uf = achado[1]
                    registrar(
                        nome,
                        "quantis",
                        lambda nome=nome, uf=uf: validar_quantis(
                            arquivos[nome][0],
                            uf,
                            ler_json(arquivos[f"modelos_{uf}.json"][0]),
                            globais,
                            indice["estados"][uf],
                            auxiliares={
                                "schema": ler_json(arquivos["model-metadata-schema.json"][0]),
                                "diagnosticos": ler_json(arquivos[f"diagnosticos_quantis_{uf}.json"][0]),
                                "ficha_pacote": ler_json(arquivos[f"croissant_{uf}.json"][0]),
                                "tasks": ler_json(arquivos[f"tasks_{uf}.json"][0]),
                                "tasks_globais": ler_json(arquivos["tasks.json"][0]),
                            },
                        ),
                    )
                elif achado := re.fullmatch(r"cadt_([A-Z]{2})\.json", nome):
                    uf = achado[1]
                    dado = cadts[uf] = ler_json(arquivos[nome][0])
                    registrar(
                        nome,
                        "cronograma",
                        lambda dado=dado, uf=uf: validar_cadt(
                            dado,
                            uf,
                            indice["estados"][uf],
                            arquivos[f"raiz_{uf}.tar.gz"][1],
                            armazem.url_metadados(f"raiz_{uf}.tar.gz"),
                            armazem.url_metadados("cadt_lotes.json"),
                            pacote=arquivos[f"raiz_{uf}.tar.gz"][0],
                        ),
                    )

            def agregado():
                from raiz.cadt import combinar_estados

                exigir("cadt_lotes.json" in arquivos, "cadt_global_ausente")
                exigir(set(cadts) == ufs, "cadt_cobertura_estadual_divergente")
                exigir(
                    ler_json(arquivos["cadt_lotes.json"][0]) == combinar_estados(cadts), "cadt_global_diverge_estaduais"
                )
                return {"estados": len(cadts), "projetos": sum(bool(d.get("projeto")) for d in cadts.values())}

            registrar("cadt_lotes.json", "agregado", agregado)
        exigir(snapshot(armazem, publicador)[0] == inicial, "release_alterado_durante_verificacao")
        saida["snapshot_estavel"] = True
    except Exception as erro:
        codigo = erro_seguro(erro)
        saida["erros"].append({"etapa": "escopo", "codigo": codigo})
        progresso(escopo=escopo, erro=codigo)
    finally:
        saida["integridade_ok"] = not saida["erros"] and saida["snapshot_estavel"]
        salvar()


def validar_lote_publicado(nome, arquivos, base_url):
    """Reproduz somente a conversão dos produtos publicados; nunca executa o motor."""
    from raiz import lote_publicado as lote

    caminho, digest, _ = arquivos[nome]
    manifesto, conferido = lote.ler_manifesto(caminho, nome, base_url=base_url)
    exigir(digest == conferido, "lote_digest_manifesto_divergente")
    catalogo_nome = lote.namespace(digest) + "_catalogo.json"
    exigir(catalogo_nome in arquivos, "lote_catalogo_ausente")
    catalogo = ler_json(arquivos[catalogo_nome][0])
    exigir(all(r["nome"] in arquivos for r in manifesto["arquivos"].values()), "lote_pacotes_ausentes")
    pacotes = {tipo: arquivos[ref["nome"]][0] for tipo, ref in manifesto["arquivos"].items()}
    with tempfile.TemporaryDirectory(prefix="raiz-conferir-lote-") as temporaria:
        resultado = lote.gerar(
            caminho, nome, pacotes, Path(temporaria), base_url=base_url, data_inicio=catalogo.get("data_inicio_cenario")
        )
        for derivado, esperado in resultado["arquivos"].items():
            exigir(derivado in arquivos, "lote_derivado_ausente")
            real, sha_real, tamanho = arquivos[derivado]
            exigir(
                tamanho == esperado.stat().st_size
                and sha_real == lote.sha256(esperado)
                and lote.sha256(real) == sha_real,
                "lote_derivado_divergente_dos_originais",
            )
    return {
        "manifesto_sha256": digest,
        "derivados": len(resultado["arquivos"]),
        "contagens": resultado["catalogo"]["contagens"],
    }


def conferir_snapshots_finais(args, cache, relatorio, publicador):
    """Reconfere também o primeiro canal após terminar de ler o segundo."""
    for escopo, saida in relatorio["escopos"].items():
        saida["snapshot_final_estavel"] = False
        try:
            exigir("snapshot" in saida, "snapshot_inicial_ausente")
            with abrir_escopo(args, escopo, cache) as armazem:
                exigir(snapshot(armazem, publicador)[0] == saida["snapshot"], "release_alterado_antes_do_fim")
            saida["snapshot_final_estavel"] = True
        except Exception as erro:
            codigo = erro_seguro(erro)
            saida["erros"].append({"etapa": "snapshot_final", "codigo": codigo})
            progresso(escopo=escopo, erro=codigo)
            saida["integridade_ok"] = False
            saida["snapshot_estavel"] = False


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--escopo", choices=("publico", "privado", "ambos"), default="ambos")
    p.add_argument(
        "--sem-atestacao", action="store_true", help="Confere conteúdo; relatório marca atestações pendentes."
    )
    cache_padrao = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "raiz" / "verificacao-release"
    p.add_argument("--cache", type=Path, default=cache_padrao)
    p.add_argument(
        "--arquivos-locais",
        type=Path,
        action="append",
        default=[],
        help="Pasta opcional com assets já salvos; só reutiliza após conferir hash.",
    )
    p.add_argument("--relatorio", type=Path, help="Padrão: relatorio.json dentro de --cache.")
    p.add_argument("--repo-publico", default=REPO_ATESTACAO)
    p.add_argument("--tag-publica", default="dados")
    p.add_argument(
        "--gh", default="gh", help="Executável GitHub CLI com attestation verify e --deny-self-hosted-runners."
    )
    args = p.parse_args(argv)
    args.relatorio = args.relatorio or args.cache / "relatorio.json"
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    warnings.simplefilter("ignore")
    sys.path.insert(0, str(CODIGO))
    os.environ["PYTHONPATH"] = str(CODIGO) + os.pathsep + os.environ.get("PYTHONPATH", "")
    inicio = time.monotonic()
    relatorio = {
        "inicio_utc": dt.datetime.now(dt.UTC).isoformat(),
        "escopo": args.escopo,
        "somente_leitura": True,
        "atestacao_solicitada": not args.sem_atestacao,
        "workflows_atestacao_permitidos": list(WORKFLOWS_PERMITIDOS),
        "escopos": {},
    }
    try:
        from raiz import metadados
        from scripts import publicar_metadados as publicador

        codigo = subprocess.run(
            ["git", "-C", str(CODIGO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        relatorio["codigo_commit"] = codigo
        relatorio["publicador_sha256"] = sha_arquivo(CODIGO / "scripts/publicar_metadados.py")
        relatorio["validador_sha256"] = sha_arquivo(__file__)
        relatorio["modulos_codigo_sha256"] = {
            n: sha_arquivo(CODIGO / n)
            for n in (
                "raiz/executor/armazem.py",
                "raiz/executor/publicacao_aberta.py",
                "raiz/metadados.py",
                "raiz/quantis.py",
                "raiz/cadt.py",
                "raiz/lote_publicado.py",
                "raiz/quantis_lote.py",
                "raiz/metadados_lote.py",
            )
        }
        relatorio["filtro_infraestrutura"] = "scripts/publicar_metadados.py:arquivos_produto"
        cache = Cache(args.cache, args.arquivos_locais)
        for escopo in ("publico", "privado") if args.escopo == "ambos" else (args.escopo,):
            executar_escopo(args, escopo, cache, relatorio, publicador, metadados)
        conferir_snapshots_finais(args, cache, relatorio, publicador)
        esperados = {"publico", "privado"} if args.escopo == "ambos" else {args.escopo}
        relatorio["integridade_ok"] = set(relatorio["escopos"]) == esperados and all(
            e.get("integridade_ok") and e.get("snapshot_estavel") and e.get("snapshot_final_estavel")
            for e in relatorio["escopos"].values()
        )
        relatorio["verificacao_completa"] = relatorio["integridade_ok"] and not args.sem_atestacao
    except Exception as erro:
        relatorio.update(integridade_ok=False, verificacao_completa=False, erro=erro_seguro(erro))
    relatorio["duracao_segundos"] = round(time.monotonic() - inicio, 1)
    relatorio["fim_utc"] = dt.datetime.now(dt.UTC).isoformat()
    gravar_json(args.relatorio, relatorio)
    progresso(
        relatorio=str(args.relatorio),
        integridade_ok=relatorio["integridade_ok"],
        verificacao_completa=relatorio["verificacao_completa"],
    )
    if not relatorio["integridade_ok"]:
        return 1
    return 0 if relatorio["verificacao_completa"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
