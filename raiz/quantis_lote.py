"""Quantis privados dos produtos congelados do lote PA, sem recalcular previsões.

Os três perfis conservam seus valores e versões originais. A data comum é a de
montagem/consolidação declarada nos resumos, não a execução de cada município.
O pacote municipal não registra a versão da tarefa: ela permanece nula, com
diagnóstico explícito. Os hubs e Parquet são escritos em lotes limitados.
"""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import json
import os
import re
import tarfile
import tempfile
from collections import Counter
from contextlib import ExitStack
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from raiz import metadados as M
from raiz import metadados_lote as ML
from raiz import quantis as Q

VERSAO = "quantis-lote-1"
OPCOES = ("barata", "segura", "compacta")
PERFIS = ("resumos", "previsoes", "opcoes")
PAPEIS = {"titular", "reserva", "mitigacao", "em_espera"}
TAMANHO_LOTE = 32_768
LIMITE_JSON = 64 * 1024**2
METODO = "quantis_publicados_copiados_sem_recalculo"
DATAS = {
    "resumos": "data_de_montagem_declarada_nos_resumos_do_lote",
    "previsoes": "data_de_consolidacao_do_lote_nao_data_da_execucao_individual",
    "opcoes": "data_de_consolidacao_do_lote_nao_data_da_execucao_individual",
}
ALVOS = {
    "resumos": {"creditos_lote": ("tCO2e", "Créditos do lote até o fim do contrato", ("p10", "p50", "p90"))},
    "previsoes": {
        alvo: (unidade, descricao, Q._colunas("desenvolvedor", alvo))
        for alvo, (unidade, descricao, _) in Q.ALVOS.items()
        if alvo != "flag_tco2_ano"
    },
    "opcoes": {
        "credito_contrato": (
            "tCO2e",
            "Créditos do imóvel publicados na opção",
            ("credito_p10", "credito_p50", "credito_p90"),
        ),
        "tir_pct": ("%/ano", "TIR publicada na tabela da opção", ("tir_p10", "tir_p50", "tir_p90")),
    },
}
EXTRAS = [
    "model_id",
    "model_version",
    "source_model_version",
    "task_version",
    "quantile_method",
    "source_file",
    "source_archive_sha256",
    "source_member_sha256",
    "source_manifest_sha256",
    "opcao",
    "papel",
    "reference_date_source",
]
_RETOMADA = (
    "execucao_origem",
    "sha_origem",
    "execucao_atual",
    "sha_orquestrador",
    "fatias_reusadas",
    "fatias_calculadas",
)


def esquema(perfil: str) -> pa.Schema:
    return pa.schema(
        [
            *Q.ESQUEMA_SAIDA,
            *[pa.field(c, pa.string(), nullable=c != "task_version" or perfil == "previsoes") for c in EXTRAS],
        ]
    )


def esquema_modelos(perfil: str) -> dict:
    campos = {
        "team_name": {"type": "string"},
        "team_abbr": {"const": "raiz"},
        "model_name": {"type": "string"},
        "model_abbr": {"type": "string", "pattern": "^[A-Za-z0-9_+]+$"},
        "model_version": {"type": "string", "minLength": 1},
        "source_model_version": {"type": "string", "minLength": 1},
        "task_version": {"type": ["string", "null"] if perfil == "previsoes" else "string", "minLength": 1},
        "exporter_version": {"const": VERSAO},
        "profile": {"const": perfil},
        "quantile_method": {"const": METODO},
        "reference_date_source": {"const": DATAS[perfil]},
        "source_manifest_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "proveniencia": {"type": "object"},
        "license_status": {"const": "licenca_dos_dados_derivados_nao_definida"},
        "model_details": {"type": "object", "required": ["data_inputs", "methods", "methods_long"]},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"Metadados dos quantis privados do lote: {perfil}",
        "type": "object",
        "properties": campos,
        "required": list(campos),
        "additionalProperties": True,
    }


def tasks(perfil: str, data: dt.date, locais) -> dict:
    alvos = ALVOS[perfil]
    return {
        "schema_version": Q.ESQUEMA_TASKS,
        "output_type_id_datatype": "double",
        "rounds": [
            {
                "round_id_from_variable": True,
                "round_id": "reference_date",
                "model_tasks": [
                    {
                        "task_ids": {
                            "reference_date": {"required": None, "optional": [data.isoformat()]},
                            "location": {"required": None, "optional": sorted(locais)},
                            "target": {"required": None, "optional": list(alvos)},
                        },
                        "output_type": {
                            "quantile": {
                                "output_type_id": {"required": list(Q.QUANTIS)},
                                "value": {"type": "double"},
                                "is_required": True,
                            }
                        },
                        "target_metadata": [
                            {
                                "target_id": alvo,
                                "target_name": descricao,
                                "target_units": unidade,
                                "target_keys": {"target": alvo},
                                "target_type": "continuous",
                                "is_step_ahead": False,
                                "description": "Valor publicado no horizonte original, sem vencimento inferido.",
                                "additional_metadata": {
                                    "source_columns": list(colunas),
                                    "reference_date_source": DATAS[perfil],
                                },
                            }
                            for alvo, (unidade, descricao, colunas) in alvos.items()
                        ],
                    }
                ],
                "submissions_due": {"relative_to": "reference_date", "start": 0, "end": 3650},
                "additional_metadata": {"reference_date_source": DATAS[perfil]},
            }
        ],
    }


class _Diagnosticos:
    def __init__(self):
        self.contagens = Counter()
        self.linhas = {}

    def adicionar(self, perfil, fonte, codigo, *, opcao=None, alvo=None, linha=None):
        chave = (perfil, fonte, opcao, alvo, codigo)
        self.contagens[chave] += 1
        if linha is not None:
            extremos = self.linhas.setdefault(chave, [linha, linha])
            extremos[1] = linha

    def resultado(self):
        return [
            {
                "perfil": perfil,
                "source_file": fonte,
                "opcao": opcao,
                "target": alvo,
                "codigo": codigo,
                "ocorrencias": quantidade,
                "primeira_linha": self.linhas.get(chave, [None, None])[0],
                "ultima_linha": self.linhas.get(chave, [None, None])[1],
            }
            for chave, quantidade in self.contagens.items()
            for perfil, fonte, opcao, alvo, codigo in [chave]
        ]


def _proveniencia(manifesto: dict, digest: str) -> dict:
    retomada = manifesto.get("retomada") or {}
    return {
        "manifesto": {"sha256": digest, "commit": manifesto.get("commit"), "execucao": manifesto.get("execucao")},
        "retomada": {k: retomada[k] for k in _RETOMADA if k in retomada},
        "limite": "Commit de consolidação/orquestração não identifica sozinho a execução de cada CSV municipal.",
    }


def _json(caminho: Path, dados) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    caminho.write_bytes(Q._json(dados))


def _hub(pasta: Path, destino: Path) -> None:
    """Empacota os Parquet por fluxo, sem materializar seus bytes em memória."""
    with (
        destino.open("wb") as saida,
        gzip.GzipFile(fileobj=saida, mode="wb", mtime=0, filename="", compresslevel=6) as gz,
    ):
        with tarfile.open(fileobj=gz, mode="w|") as tar:
            for arquivo in sorted(pasta.rglob("*")):
                if not arquivo.is_file():
                    continue
                info = tarfile.TarInfo(arquivo.relative_to(pasta).as_posix())
                info.size, info.mtime, info.mode = arquivo.stat().st_size, 0, 0o600
                with arquivo.open("rb") as entrada:
                    tar.addfile(info, entrada)


class _Perfil:
    def __init__(self, perfil, pasta, prefixo, data, digest, proveniencia, base_url):
        self.perfil, self.pasta, self.prefixo = perfil, pasta, f"{prefixo}_{perfil}"
        self.data, self.digest, self.proveniencia, self.base_url = data, digest, proveniencia, base_url
        self.hub = pasta / f"hub-{perfil}"
        self.schema = esquema(perfil)
        self.arquivo = pasta / f"{self.prefixo}_quantis.parquet"
        self.escritor = pq.ParquetWriter(self.arquivo, self.schema, compression="zstd")
        self.modelos, self.chaves, self.fontes = {}, {}, {}
        self.buffers, self.escritores, self.locais = {}, {}, set()
        self.linhas = self.lidos = self.validos = 0

    def modelo(self, versao, original, tarefa, opcao):
        chave = (versao, original, tarefa, opcao)
        if chave in self.chaves:
            return self.chaves[chave]
        identidade = hashlib.sha256(Q._json([self.perfil, self.digest, *chave])).hexdigest()[:16]
        mid = f"raiz-lote_{self.perfil}_{opcao or 'municipios'}_{self.digest[:16]}_{identidade}"
        self.chaves[chave] = mid
        self.modelos[mid] = {
            "team_name": "Raíz",
            "team_abbr": "raiz",
            "model_name": f"Raíz: lote PA — {self.perfil}",
            "model_abbr": mid.split("-", 1)[1],
            "model_version": versao,
            "source_model_version": original,
            "task_version": tarefa,
            "exporter_version": VERSAO,
            "profile": self.perfil,
            "opcao": opcao,
            "quantile_method": METODO,
            "reference_date_source": DATAS[self.perfil],
            "source_manifest_sha256": self.digest,
            "proveniencia": self.proveniencia,
            "license_status": "licenca_dos_dados_derivados_nao_definida",
            "repo_url": Q.REPO,
            "model_details": {
                "data_inputs": "Produtos privados publicados do lote PA, identificados por hashes e caminhos internos.",
                "methods": "Cópia de P10/P50/P90 publicados, sem ordenar faixas ou recalcular números.",
                "methods_long": "P50 preserva o valor central publicado, sem alegar mediana amostral ou calibração. "
                "A data é de montagem/consolidação do lote; a execução individual municipal não foi registrada.",
            },
        }
        self.buffers[mid] = {coluna: [] for coluna in self.schema.names}
        arquivo = self.hub / "model-output" / mid / f"{self.data}-{mid}.parquet"
        arquivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.escritores[mid] = pq.ParquetWriter(arquivo, Q.ESQUEMA_SAIDA, compression="zstd")
        return mid

    def emitir(self, mid, local, alvo, valores, fonte, opcao, papel):
        modelo, buffer = self.modelos[mid], self.buffers[mid]
        extras = {
            "model_id": mid,
            "model_version": modelo["model_version"],
            "source_model_version": modelo["source_model_version"],
            "task_version": modelo["task_version"],
            "quantile_method": METODO,
            "source_file": fonte["source_file"],
            "source_archive_sha256": fonte["source_archive_sha256"],
            "source_member_sha256": fonte["source_member_sha256"],
            "source_manifest_sha256": self.digest,
            "opcao": opcao,
            "papel": papel,
            "reference_date_source": DATAS[self.perfil],
        }
        for coluna, valor in {
            "reference_date": self.data,
            "location": local,
            "target": alvo,
            "output_type": "quantile",
            **extras,
        }.items():
            buffer[coluna].extend([valor] * 3)
        buffer["output_type_id"].extend(Q.QUANTIS)
        buffer["value"].extend(valores)
        self.linhas += 3
        self.locais.add(local)
        self.fontes[(fonte["source_archive_sha256"], fonte["source_file"])] = fonte
        if len(buffer["value"]) >= TAMANHO_LOTE:
            self.despejar(mid)

    def despejar(self, mid):
        buffer = self.buffers[mid]
        if not buffer["value"]:
            return
        tabela = pa.Table.from_pydict(buffer, schema=self.schema)
        self.escritor.write_table(tabela)
        self.escritores[mid].write_table(tabela.select(Q.COLUNAS))
        for valores in buffer.values():
            valores.clear()

    def fechar(self):
        try:
            for mid in sorted(self.buffers):
                self.despejar(mid)
        finally:
            self.escritor.close()
            for escritor in self.escritores.values():
                escritor.close()

    def finalizar(self):
        configuracao, schema = tasks(self.perfil, self.data, self.locais), esquema_modelos(self.perfil)
        metadados = {
            "exporter_version": VERSAO,
            "profile": self.perfil,
            "reference_date": str(self.data),
            "reference_date_source": DATAS[self.perfil],
            "source_manifest_sha256": self.digest,
            "proveniencia": self.proveniencia,
            "modelos": self.modelos,
            "fontes": list(self.fontes.values()),
            "quantis_url": self.base_url + self.arquivo.name,
        }
        objetos = {"tasks.json": configuracao, "modelos.json": metadados, "model-metadata-schema.json": schema}
        arquivos = {self.arquivo.name: self.arquivo}
        for sufixo, objeto in objetos.items():
            arquivo = self.pasta / f"{self.prefixo}_{sufixo}"
            _json(arquivo, objeto)
            arquivos[arquivo.name] = arquivo
        _json(self.hub / "hub-config/tasks.json", configuracao)
        _json(self.hub / "hub-config/model-metadata-schema.json", schema)
        admin = Q.admin()
        admin["name"] = f"Raíz: produtos privados do lote PA — {self.perfil}"
        admin["additional_metadata"] = {"reference_date_source": DATAS[self.perfil], "profile": self.perfil}
        _json(self.hub / "hub-config/admin.json", admin)
        for mid, modelo in self.modelos.items():
            arquivo = self.hub / "model-metadata" / f"{mid}.yml"
            arquivo.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            arquivo.write_text(yaml.safe_dump(modelo, allow_unicode=True, sort_keys=True), encoding="utf-8")
        pacote = self.pasta / f"{self.prefixo}_hub.tar.gz"
        _hub(self.hub, pacote)
        arquivos[pacote.name] = pacote
        return arquivos


def _referencia(manifesto, opcao):
    arquivos = manifesto.get("arquivos") or {}
    if opcao in arquivos:
        referencia = dict(arquivos[opcao])
    else:
        candidatos = [(nome, info) for nome, info in arquivos.items() if nome.endswith(f"_{opcao}.tar.gz")]
        if len(candidatos) != 1:
            raise ValueError("referencia_do_pacote_ausente_ou_ambigua")
        nome, info = candidatos[0]
        referencia = {**info, "nome": nome}
    if not re.fullmatch(r"[a-fA-F0-9]{64}", referencia.get("sha256") or ""):
        raise ValueError("sha256_do_pacote_ausente")
    return referencia


def _conteudo(tar, membros, nome):
    membro = membros.get(nome)
    if membro is None or membro.size > LIMITE_JSON:
        raise ValueError("json_de_proveniencia_ausente_ou_excessivo")
    with tar.extractfile(membro) as entrada:
        bruto = entrada.read()
    try:
        objeto = json.loads(bruto)
    except (ValueError, UnicodeError):
        raise ValueError("json_de_proveniencia_invalido") from None
    return objeto, hashlib.sha256(bruto).hexdigest()


def _csv(tar, membro, destino, esperado=None):
    digest = hashlib.sha256()
    with tar.extractfile(membro) as entrada, destino.open("wb") as saida:
        for bloco in iter(lambda: entrada.read(1024**2), b""):
            digest.update(bloco)
            saida.write(bloco)
    sha = digest.hexdigest()
    if esperado is not None and sha != esperado:
        raise ValueError("sha256_csv_diverge_de_municipios_json")
    return sha


def _valores(linha, colunas, diag, perfil, fonte, opcao, alvo, numero):
    try:
        valores = tuple(Q._numero(linha.get(coluna)) for coluna in colunas)
    except ValueError as erro:
        diag.adicionar(perfil, fonte, str(erro), opcao=opcao, alvo=alvo, linha=numero)
        return None
    if not valores[0] <= valores[1] <= valores[2]:
        diag.adicionar(perfil, fonte, "quantis_cruzados", opcao=opcao, alvo=alvo, linha=numero)
        return None
    return valores


def _linhas(perfil, arquivo, fonte, diag, *, opcao=None, versoes=None, vistos=None):
    vistos = vistos if vistos is not None else set()
    with arquivo.open(encoding="utf-8-sig", newline="") as entrada:
        leitor = csv.DictReader(entrada)
        cabecalho = leitor.fieldnames or []
        if len(set(cabecalho)) != len(cabecalho) or "cod_imovel" not in cabecalho:
            raise ValueError("cabecalho_csv_invalido")
        completos = {}
        for alvo, (_, _, colunas) in ALVOS[perfil.perfil].items():
            if not set(colunas) <= set(cabecalho):
                diag.adicionar(perfil.perfil, fonte["source_file"], "coluna_de_quantil_ausente", opcao=opcao, alvo=alvo)
            else:
                completos[alvo] = colunas
        for numero, linha in enumerate(leitor, 2):
            perfil.lidos += 1
            codigo = None
            car = str(linha.get("cod_imovel") or "").strip()
            original = Q._versao(linha.get("restauracao_versao"))
            papel = linha.get("papel") if opcao else None
            if None in linha:
                codigo = "linha_csv_invalida"
            elif not Q._CAR.fullmatch(car) or not car.startswith("PA-"):
                codigo = "codigo_car_ausente_ou_incompativel"
            elif car in vistos:
                codigo = "codigo_car_duplicado"
            elif not original:
                codigo = "versao_do_modelo_ausente"
            elif versoes and original != versoes[1]:
                codigo = "versao_do_modelo_divergente"
            elif opcao and papel not in PAPEIS:
                codigo = "papel_ausente_ou_desconhecido"
            if codigo:
                diag.adicionar(perfil.perfil, fonte["source_file"], codigo, opcao=opcao, linha=numero)
                continue
            vistos.add(car)
            versao, tarefa = (versoes[0], versoes[2]) if opcao else (original, None)
            mid, algum = None, False
            for alvo, colunas in completos.items():
                valores = _valores(linha, colunas, diag, perfil.perfil, fonte["source_file"], opcao, alvo, numero)
                if valores is None:
                    continue
                mid = mid or perfil.modelo(versao, original, tarefa, opcao)
                perfil.emitir(mid, car, alvo, valores, fonte, opcao, papel)
                algum = True
            perfil.validos += int(algum)


def exportar(manifesto: dict, manifesto_sha256: str, pacotes: dict[str, Path], destino: Path, *, base_url: str) -> dict:
    """Exporta os quatro TAR verificados para três perfis namespaced privados.

    ``manifesto_sha256`` identifica os bytes originais do manifesto, conferidos
    pelo chamador. ``pacotes`` usa as chaves barata/segura/compacta/previsoes.
    ``base_url`` é a raiz release-github privada, terminada em barra. O destino
    deve ser uma pasta privada; os arquivos só são promovidos após a conclusão.
    """
    if not re.fullmatch(r"[a-fA-F0-9]{64}", manifesto_sha256 or ""):
        raise ValueError("sha256_do_manifesto_invalido")
    digest = manifesto_sha256.lower()
    if manifesto.get("uf") != "PA" or manifesto.get("cenario") != "central_r11":
        raise ValueError("manifesto_de_lote_incompativel")
    if not base_url.endswith("/"):
        raise ValueError("base_privada_invalida")
    M._url_acesso(base_url + "arquivo.json", escopo="privado")
    resumos = manifesto.get("resumos") or {}
    if set(resumos) != set(OPCOES):
        raise ValueError("tres_resumos_obrigatorios")
    datas = {resumos[opcao].get("data") for opcao in OPCOES}
    if len(datas) != 1:
        raise ValueError("datas_dos_resumos_divergentes")
    try:
        data = dt.date.fromisoformat(next(iter(datas)))
    except (TypeError, ValueError):
        raise ValueError("data_de_consolidacao_ausente_ou_invalida") from None
    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destino.is_symlink() or destino.stat().st_mode & 0o077:
        raise ValueError("destino_deve_ser_pasta_privada")
    prefixo = f"lote_PA_central_r11_{digest[:16]}"
    proveniencia, diag = _proveniencia(manifesto, digest), _Diagnosticos()
    with tempfile.TemporaryDirectory(prefix="quantis-lote-", dir=destino) as temporario, ExitStack() as pilha:
        pasta, abertos, referencias = Path(temporario), {}, {}
        for opcao in (*OPCOES, "previsoes"):
            pacote, referencia = Path(pacotes[opcao]), _referencia(manifesto, opcao)
            if pacote.stat().st_size > ML.LIMITE_BYTES_PACOTE:
                raise ValueError("limite_de_pacote_excedido")
            if referencia.get("bytes") is not None and pacote.stat().st_size != referencia["bytes"]:
                raise ValueError("tamanho_do_pacote_divergente")
            if ML._sha256(pacote) != referencia["sha256"].lower():
                raise ValueError("sha256_do_pacote_divergente")
            tar = pilha.enter_context(tarfile.open(pacote, "r:gz"))
            abertos[opcao] = (tar, {m.name: m for m in ML._membros(tar)})
            referencias[opcao] = referencia
        perfis = {p: _Perfil(p, pasta, prefixo, data, digest, proveniencia, base_url) for p in PERFIS}
        try:
            for opcao in OPCOES:
                resumo = resumos[opcao]
                versoes = tuple(
                    Q._versao(resumo.get(c)) for c in ("versao_modelo_lote", "versao_premissas", "versao_otimizador")
                )
                if not all(versoes):
                    raise ValueError("versoes_originais_do_lote_ausentes")
                tar, membros = abertos[opcao]
                nome = f"{opcao}/lote_PA.json"
                publicado, sha = _conteudo(tar, membros, nome)
                campos = ("data", "creditos_lote_faixa", "versao_modelo_lote", "versao_premissas", "versao_otimizador")
                if any(publicado.get(c) != resumo.get(c) for c in campos):
                    raise ValueError("resumo_do_pacote_diverge_do_manifesto")
                fonte = {
                    "source_file": nome,
                    "source_archive_sha256": referencias[opcao]["sha256"].lower(),
                    "source_member_sha256": sha,
                }
                perfil = perfis["resumos"]
                perfil.lidos += 1
                valores = _valores(
                    resumo.get("creditos_lote_faixa") or {},
                    ("p10", "p50", "p90"),
                    diag,
                    "resumos",
                    nome,
                    opcao,
                    "creditos_lote",
                    None,
                )
                if valores is not None:
                    mid = perfil.modelo(*versoes, opcao)
                    perfil.emitir(mid, "PA", "creditos_lote", valores, fonte, opcao, None)
                    perfil.validos += 1
                nome_csv = f"{opcao}/lote_PA.csv"
                if nome_csv not in membros:
                    raise ValueError("csv_da_opcao_ausente")
                arquivo = pasta / "fonte.csv"
                sha = _csv(tar, membros[nome_csv], arquivo)
                fonte = {**fonte, "source_file": nome_csv, "source_member_sha256": sha}
                _linhas(perfis["opcoes"], arquivo, fonte, diag, opcao=opcao, versoes=versoes)
            tar, membros = abertos["previsoes"]
            municipios, sha_municipios = _conteudo(tar, membros, "municipios.json")
            esperados = {}
            for municipio in municipios:
                for nome, sha in municipio["arquivos"].items():
                    if re.fullmatch(r"desenvolvedor_\d{7}\.csv", nome):
                        if nome in esperados or not re.fullmatch(r"[a-f0-9]{64}", sha):
                            raise ValueError("proveniencia_municipal_invalida")
                        esperados[nome] = (sha, municipio.get("modelo_versao"))
            csvs = {
                Path(nome).name: membro
                for nome, membro in membros.items()
                if re.fullmatch(r"previsoes/desenvolvedor_\d{7}\.csv", nome)
            }
            if not esperados or set(csvs) != set(esperados):
                raise ValueError("cobertura_csv_diverge_de_municipios_json")
            if manifesto.get("municipios_calculados") is not None and len(csvs) != manifesto["municipios_calculados"]:
                raise ValueError("cobertura_csv_diverge_do_manifesto")
            vistos = set()
            for nome, membro in sorted(csvs.items()):
                esperado, original = esperados[nome]
                if not Q._versao(original):
                    raise ValueError("versao_municipal_ausente")
                arquivo = pasta / "fonte.csv"
                sha = _csv(tar, membro, arquivo, esperado)
                fonte = {
                    "source_file": membro.name,
                    "source_archive_sha256": referencias["previsoes"]["sha256"].lower(),
                    "source_member_sha256": sha,
                    "municipios_json_sha256": sha_municipios,
                }
                diag.adicionar("previsoes", membro.name, "versao_da_tarefa_individual_ausente")
                _linhas(perfis["previsoes"], arquivo, fonte, diag, versoes=(original, original, None), vistos=vistos)
        finally:
            for perfil in perfis.values():
                perfil.fechar()
        arquivos = {}
        for perfil in perfis.values():
            arquivos.update(perfil.finalizar())
        diagnosticos = pasta / f"{prefixo}_diagnosticos_quantis.json"
        _json(
            diagnosticos,
            {"source_manifest_sha256": digest, "proveniencia": proveniencia, "diagnosticos": diag.resultado()},
        )
        arquivos[diagnosticos.name] = diagnosticos
        contagens = {
            p: {
                "linhas": x.linhas,
                "registros_lidos": x.lidos,
                "registros_com_quantis": x.validos,
                "fontes": len(x.fontes),
                "modelos": len(x.modelos),
            }
            for p, x in perfis.items()
        }
        contagens["diagnosticos"] = sum(diag.contagens.values())
        for nome, arquivo in arquivos.items():
            os.chmod(arquivo, 0o600)
            arquivo.replace(destino / nome)
        return {"arquivos": {nome: destino / nome for nome in arquivos}, "contagens": contagens}
